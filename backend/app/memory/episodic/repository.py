"""情景记忆的默认空实现。"""

from __future__ import annotations

from backend.app.memory.episodic.contracts import (
    EpisodicMemoryEvent,
    EpisodicMemorySnippet,
)
from backend.app.memory.structured.contracts import MemoryScope


class NoopEpisodicMemoryStore:
    """未配置嵌入模型或后端时使用的安全空实现。

    空实现比临时写一个关键词检索更可控：没有经过评测的召回不能悄悄影响
    课程回答，也不会把普通聊天内容无差别长期保存。
    """

    def __init__(self, *, reason: str = "disabled") -> None:
        self.reason = reason

    def recall(
        self,
        scope: MemoryScope,
        query: str,
        *,
        limit: int = 5,
    ) -> tuple[EpisodicMemorySnippet, ...]:
        """关闭状态始终返回空，不传播查询和作用域内容。"""

        return ()

    def remember(self, event: EpisodicMemoryEvent) -> None:
        """关闭状态丢弃事件，避免形成未经治理的隐式长期存储。"""

        return None
