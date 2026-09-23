"""会话目录、消息持久化和 Redis 恢复的应用服务。"""

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.conversations.models import ChatConversation
from backend.app.conversations.redaction import redact_persistent_text
from backend.app.conversations.repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from backend.app.conversations.recovery import restore_if_missing
from backend.app.conversations.titles import generate_conversation_title
from backend.app.memory.conversation import ConversationStore, ConversationSubject
from backend.app.memory.conversation.serialization import memory_to_payload
from backend.app.services.access_control import AccessContext
from backend.app.services.audit import write_audit_log


logger = logging.getLogger(__name__)


def subject_from_context(context: AccessContext) -> ConversationSubject:
    return ConversationSubject(context.tenant_id, context.user_id, context.role)


class ConversationHistoryService:
    """把事务和安全边界集中起来，路由与聊天编排不直接操作 ORM。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ConversationRepository(session)

    def create(
        self, context: AccessContext, *, title: str | None = None
    ) -> ChatConversation:
        subject = subject_from_context(context)
        normalized_title = redact_persistent_text(title or "新会话", max_length=80)
        conversation = self.repository.create(
            f"conv_{uuid4().hex}", subject,
            title=normalized_title or "新会话",
            title_is_custom=bool(title),
        )
        self.session.commit()
        return conversation

    def list(
        self, context: AccessContext, *, limit: int, offset: int
    ) -> tuple[list[ChatConversation], int]:
        """列出当前可信主体自己的会话，不接受客户端指定所有者。"""

        return self.repository.list_owned(
            subject_from_context(context), limit=limit, offset=offset
        )

    def messages(
        self, conversation_id: str, context: AccessContext, *,
        limit: int, before_sequence: int | None = None,
    ):
        """读取当前主体会话中的脱敏消息。"""

        return self.repository.list_messages(
            conversation_id, subject_from_context(context),
            limit=limit, before_sequence=before_sequence,
        )

    def rename(
        self, conversation_id: str, context: AccessContext, title: str
    ) -> ChatConversation:
        """设置用户自定义标题；后续自动标题不得覆盖。"""

        safe_title = redact_persistent_text(title, max_length=80).strip()
        if not safe_title:
            safe_title = "新会话"
        conversation = self.repository.rename(
            conversation_id, subject_from_context(context), safe_title
        )
        self.session.commit()
        return conversation

    def ensure_for_chat(
        self, conversation_id: str, context: AccessContext
    ) -> ChatConversation:
        """兼容旧 web-* 客户端：不存在则在可信主体下惰性创建。"""

        subject = subject_from_context(context)
        try:
            return self.repository.get_owned(conversation_id, subject)
        except ConversationNotFoundError:
            # 同一个全局 ID 若已被别的主体占用，统一表现为 404，不能接管。
            if self.repository.get_any(conversation_id) is not None:
                raise
            conversation = self.repository.create(conversation_id, subject)
            self.session.commit()
            return conversation

    def prepare_for_chat(
        self, conversation_id: str | None, context: AccessContext,
        store: ConversationStore, *, recent_turn_limit: int,
    ) -> ChatConversation | None:
        if conversation_id is None:
            return None
        subject = subject_from_context(context)
        conversation = self.ensure_for_chat(conversation_id, context)
        recent = self.repository.recent_messages(
            conversation_id, subject, limit=max(2, recent_turn_limit * 2)
        )
        restore_if_missing(
            store, conversation_id=conversation_id, subject=subject,
            conversation=conversation, messages=recent,
        )
        return conversation

    def persist_turn(
        self, conversation_id: str | None, context: AccessContext,
        store: ConversationStore, *, user_message: str, assistant_answer: str,
    ) -> None:
        if conversation_id is None:
            return
        subject = subject_from_context(context)
        conversation = self.repository.get_owned(conversation_id, subject)
        memory = store.read(conversation_id, subject=subject)
        snapshot = memory_to_payload(memory, include_turns=False)
        # 数据库是第二道脱敏边界；即使调用方未来误传原文，也不会直接落库。
        safe_user = redact_persistent_text(user_message, max_length=2000)
        safe_answer = redact_persistent_text(assistant_answer, max_length=8000)
        self.repository.append_turn(
            conversation, user_message=safe_user, assistant_answer=safe_answer,
            context_snapshot=snapshot, auto_title=generate_conversation_title(safe_user),
        )
        self.session.commit()

    def delete(
        self, conversation_id: str, context: AccessContext, store: ConversationStore
    ) -> None:
        subject = subject_from_context(context)
        self.repository.delete(conversation_id, subject)
        write_audit_log(
            self.session, actor_user_id=context.user_id, action="conversation.delete",
            resource_type="chat_conversation", resource_id=conversation_id,
            outcome="success", metadata={"owner_role": context.role},
        )
        self.session.commit()
        # PostgreSQL 删除是权威结果；Redis 清理失败由调用方记录告警，不能复活目录。
        try:
            store.clear(conversation_id, subject=subject)
        except Exception:
            # 删除已经提交，短期键最多存活至 TTL；不能因此向客户端伪装成
            # 数据库删除失败，更不能回滚后重新暴露会话目录。
            logger.warning(
                "conversation_cache_delete_failed reason=storage_unavailable"
            )


__all__ = [
    "ConversationHistoryService",
    "ConversationNotFoundError",
    "subject_from_context",
]
