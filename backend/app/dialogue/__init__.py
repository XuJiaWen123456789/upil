"""多 Agent 对话决策层。

该包只负责把实体、槽位、Supervisor 结果和未完成流程仲裁为一份受控决策，
不访问数据库、不调用 RAG，也不执行报告生成等业务副作用。
"""

from backend.app.dialogue.arbitration import arbitrate_turn, resolve_dialogue_route
from backend.app.dialogue.contracts import (
    DialogueAct,
    PendingFlow,
    SideEffectLevel,
    SlotSource,
    SlotValue,
    TurnDecision,
    UnknownKind,
)

__all__ = [
    "DialogueAct",
    "PendingFlow",
    "SideEffectLevel",
    "SlotSource",
    "SlotValue",
    "TurnDecision",
    "UnknownKind",
    "arbitrate_turn",
    "resolve_dialogue_route",
]
