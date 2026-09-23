"""从 PostgreSQL 快照恢复已过期的 Redis 工作记忆。"""

from backend.app.conversations.models import ChatConversation, ChatMessage
from backend.app.memory.conversation import (
    ConversationMemory,
    ConversationStore,
    ConversationSubject,
    ConversationTurn,
)
from backend.app.memory.conversation.serialization import memory_from_payload


def build_recovery_memory(
    conversation: ChatConversation, messages: list[ChatMessage]
) -> ConversationMemory:
    """组合白名单快照和少量最近消息，绝不加载整段历史。"""

    memory = memory_from_payload(conversation.context_snapshot or {})
    memory.recent_turns = [
        ConversationTurn(
            role=message.role,
            content=message.content[:4000],
            created_at=message.created_at.timestamp(),
        )
        for message in messages
        if message.role in {"user", "assistant"} and message.content
    ]
    return memory


def restore_if_missing(
    store: ConversationStore, *, conversation_id: str, subject: ConversationSubject,
    conversation: ChatConversation, messages: list[ChatMessage],
) -> bool:
    """仅在短期存储确实为空时恢复，禁止覆盖正在使用的新状态。"""

    if not (conversation.context_snapshot or messages):
        return False
    return store.restore(
        conversation_id,
        build_recovery_memory(conversation, messages),
        subject=subject,
        only_if_empty=True,
    )
