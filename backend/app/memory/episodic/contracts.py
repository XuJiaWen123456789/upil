"""情景记忆的最小协议。

情景记忆在当前版本不是 RAGFlow 的替代品，也不强制要求部署嵌入模型。协议先
把事件、召回片段和存储边界固定下来，默认由 Noop 实现返回空结果，后续有明确
评测集和嵌入服务后再接入具体实现。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.memory.structured.contracts import MemoryScope


@dataclass(frozen=True, slots=True)
class EpisodicMemoryEvent:
    """一条候选历史事件；事件内容必须在调用前完成脱敏。"""

    scope: MemoryScope
    content: str
    occurred_at: datetime
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class EpisodicMemorySnippet:
    """供 Agent 读取的历史片段，不暴露数据库元数据。"""

    content: str
    score: float | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


class EpisodicMemoryStore(Protocol):
    """情景记忆读写协议；实现必须自行落实租户和用户隔离。"""

    def recall(
        self,
        scope: MemoryScope,
        query: str,
        *,
        limit: int = 5,
    ) -> tuple[EpisodicMemorySnippet, ...]:
        """按受控查询召回历史片段。"""

    def remember(self, event: EpisodicMemoryEvent) -> None:
        """保存一条已经过准入检查的事件。"""
