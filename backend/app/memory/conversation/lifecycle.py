"""会话消息记录、压缩和快照读取。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.memory.conversation.compression import compress_memory
from backend.app.memory.conversation.contracts import (
    ConversationMemory,
    ConversationStore,
    ConversationSubject,
    ConversationTurn,
)


@dataclass(frozen=True, slots=True)
class ConversationSnapshot:
    """供上下文装配器读取的不可变短期状态快照。"""

    rolling_summary: str
    recent_turns: tuple[dict[str, str], ...]
    version: int


def record_turn(
    store: ConversationStore,
    *,
    conversation_id: str | None,
    subject: ConversationSubject | None,
    user_message: str,
    assistant_answer: str,
    recent_turn_limit: int,
    summary_token_budget: int,
    context_token_budget: int,
) -> None:
    """记录已脱敏的一问一答，并立即执行容量治理。"""

    if conversation_id is None:
        return

    def update(memory: ConversationMemory) -> None:
        memory.recent_turns.extend((
            ConversationTurn("user", user_message[:2000]),
            ConversationTurn("assistant", assistant_answer[:4000]),
        ))
        compress_memory(
            memory,
            recent_turn_limit=recent_turn_limit * 2,
            summary_token_budget=summary_token_budget,
            context_token_budget=context_token_budget,
        )

    store.process(conversation_id, update, subject=subject)


def read_snapshot(
    store: ConversationStore,
    *,
    conversation_id: str | None,
    subject: ConversationSubject | None,
) -> ConversationSnapshot:
    """读取快照；无会话 ID 时返回空上下文。"""

    if conversation_id is None:
        return ConversationSnapshot("", (), 0)

    def to_snapshot(memory: ConversationMemory) -> ConversationSnapshot:
        return ConversationSnapshot(
            rolling_summary=memory.rolling_summary,
            recent_turns=tuple(
                {"role": turn.role, "content": turn.content}
                for turn in memory.recent_turns
            ),
            version=memory.version,
        )

    read_method = getattr(store, "read", None)
    if read_method is not None:
        return to_snapshot(read_method(conversation_id, subject=subject))
    # 兼容尚未实现 read 的测试替身；正式存储使用上面的只读路径。
    return store.process(conversation_id, to_snapshot, subject=subject)
