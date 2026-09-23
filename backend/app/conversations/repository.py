"""持久会话仓储，只负责受主体约束的数据访问。"""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.conversations.models import ChatConversation, ChatMessage
from backend.app.memory.conversation import ConversationSubject


class ConversationNotFoundError(LookupError):
    """会话不存在或不属于当前主体；HTTP 层统一映射为 404。"""


class ConversationRepository:
    """任何查询都同时约束租户、用户和角色，禁止只按 ID 读取。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _owner_conditions(subject: ConversationSubject):
        return (
            ChatConversation.tenant_id == subject.tenant_id,
            ChatConversation.owner_user_id == subject.user_id,
            ChatConversation.owner_role == subject.role,
        )

    def get_owned(
        self, conversation_id: str, subject: ConversationSubject, *, lock: bool = False
    ) -> ChatConversation:
        statement = select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            *self._owner_conditions(subject),
        )
        if lock:
            statement = statement.with_for_update()
        conversation = self.session.scalar(statement)
        if conversation is None:
            raise ConversationNotFoundError("会话不存在")
        return conversation

    def get_any(self, conversation_id: str) -> ChatConversation | None:
        """只用于惰性创建前检查全局 ID 冲突，不向调用方返回他人数据。"""

        return self.session.get(ChatConversation, conversation_id)

    def create(
        self, conversation_id: str, subject: ConversationSubject, *, title: str = "新会话",
        title_is_custom: bool = False,
    ) -> ChatConversation:
        conversation = ChatConversation(
            id=conversation_id,
            tenant_id=subject.tenant_id,
            owner_user_id=subject.user_id,
            owner_role=subject.role,
            title=title,
            title_is_custom=title_is_custom,
        )
        self.session.add(conversation)
        self.session.flush()
        return conversation

    def list_owned(
        self, subject: ConversationSubject, *, limit: int, offset: int
    ) -> tuple[list[ChatConversation], int]:
        conditions = self._owner_conditions(subject)
        total = self.session.scalar(
            select(func.count()).select_from(ChatConversation).where(*conditions)
        ) or 0
        items = list(self.session.scalars(
            select(ChatConversation)
            .where(*conditions)
            .order_by(
                ChatConversation.last_message_at.desc().nullslast(),
                ChatConversation.updated_at.desc(),
                ChatConversation.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ))
        return items, total

    def list_messages(
        self, conversation_id: str, subject: ConversationSubject, *,
        limit: int, before_sequence: int | None = None,
    ) -> tuple[list[ChatMessage], bool]:
        self.get_owned(conversation_id, subject)
        conditions = [ChatMessage.conversation_id == conversation_id]
        if before_sequence is not None:
            conditions.append(ChatMessage.sequence_no < before_sequence)
        newest_first = list(self.session.scalars(
            select(ChatMessage)
            .where(*conditions)
            .order_by(ChatMessage.sequence_no.desc())
            .limit(limit + 1)
        ))
        has_more = len(newest_first) > limit
        return list(reversed(newest_first[:limit])), has_more

    def recent_messages(
        self, conversation_id: str, subject: ConversationSubject, *, limit: int
    ) -> list[ChatMessage]:
        messages, _ = self.list_messages(
            conversation_id, subject, limit=limit, before_sequence=None
        )
        return messages

    def append_turn(
        self, conversation: ChatConversation, *, user_message: str,
        assistant_answer: str, context_snapshot: dict, auto_title: str,
    ) -> None:
        # 锁住目录行后再计算序号，避免同一会话的两个并发请求复用序号。
        locked = self.get_owned(
            conversation.id,
            ConversationSubject(
                conversation.tenant_id, conversation.owner_user_id, conversation.owner_role
            ),
            lock=True,
        )
        latest_sequence = self.session.scalar(
            select(func.max(ChatMessage.sequence_no)).where(
                ChatMessage.conversation_id == locked.id
            )
        ) or 0
        now = datetime.utcnow()
        self.session.add_all((
            ChatMessage(
                conversation_id=locked.id, sequence_no=latest_sequence + 1,
                role="user", content=user_message, created_at=now,
            ),
            ChatMessage(
                conversation_id=locked.id, sequence_no=latest_sequence + 2,
                role="assistant", content=assistant_answer, created_at=now,
            ),
        ))
        if not locked.title_is_custom and locked.title == "新会话":
            locked.title = auto_title
        locked.context_snapshot = context_snapshot
        locked.last_message_at = now
        locked.updated_at = now
        self.session.flush()

    def rename(
        self, conversation_id: str, subject: ConversationSubject, title: str
    ) -> ChatConversation:
        conversation = self.get_owned(conversation_id, subject, lock=True)
        conversation.title = title
        conversation.title_is_custom = True
        conversation.updated_at = datetime.utcnow()
        self.session.flush()
        return conversation

    def delete(self, conversation_id: str, subject: ConversationSubject) -> None:
        conversation = self.get_owned(conversation_id, subject, lock=True)
        # PostgreSQL 外键配置了 ON DELETE CASCADE；这里仍显式删除消息，既保证
        # SQLite 测试环境未开启外键 pragma 时行为一致，也避免未来迁移漏配级联
        # 后遗留不再属于任何会话的孤儿消息。
        self.session.execute(
            delete(ChatMessage).where(ChatMessage.conversation_id == conversation.id)
        )
        self.session.delete(conversation)
        self.session.flush()
