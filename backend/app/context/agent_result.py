"""Agent 输出的结构化契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.app.schemas import SourceReference


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Agent 只能通过该结果表达回答和受控状态更新。"""

    agent_name: str
    answer: str = ""
    provider: str = "workflow"
    sources: tuple[SourceReference, ...] = ()
    state_updates: Mapping[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    warnings: tuple[str, ...] = ()

    def as_state(self) -> dict[str, Any]:
        """转换为 LangGraph 节点可以返回的普通字典。"""

        return {
            "answer": self.answer,
            "provider": self.provider,
            "sources": list(self.sources),
            **dict(self.state_updates),
        }
