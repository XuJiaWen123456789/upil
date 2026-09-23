"""对话仲裁使用的不可变数据契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from backend.app.agents.supervisor import RecognitionSource
from backend.app.conversation_understanding import (
    EntityReference,
    IntentResult,
    IntentType,
)


class SlotSource(str, Enum):
    """槽位值的可信来源。"""

    USER_EXPLICIT = "user_explicit"
    DETERMINISTIC = "deterministic"
    MODEL_INFERRED = "model_inferred"
    SESSION = "session"
    DATABASE = "database"


class DialogueAct(str, Enum):
    """本轮消息在对话状态机中的作用，而不是业务意图。"""

    QUESTION = "question"
    COMMAND = "command"
    PROVIDE_SLOT = "provide_slot"
    CORRECTION = "correction"
    GREETING = "greeting"
    COURTESY = "courtesy"
    CANCEL = "cancel"
    # DEFER 表示暂缓试听、报名或销售顾问跟进，不等同于取消报告等工具
    # pending；分开建模可以让固定回复和后台线索状态保持准确。
    DEFER = "defer"


class UnknownKind(str, Enum):
    """UNKNOWN 的细分类，防止所有未知消息都进入 FAQ/RAG。"""

    SMALL_TALK = "small_talk"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED_IN_DOMAIN = "unsupported_in_domain"
    OUT_OF_SCOPE = "out_of_scope"
    IN_DOMAIN_GENERAL = "in_domain_general"
    UNKNOWN = "unknown"


class SideEffectLevel(str, Enum):
    """本轮主路由允许产生的副作用等级。"""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True, slots=True)
class SlotValue:
    """带来源和确认状态的槽位值。

    模型推断值默认不能驱动数据库查询或报告生成；业务工具只消费
    ``confirmed=True`` 的确定性值，权限范围仍由服务端认证上下文决定。
    """

    value: Any
    source: SlotSource
    confidence: float
    confirmed: bool
    updated_turn: int | None = None


@dataclass(frozen=True, slots=True)
class PendingFlow:
    """一项尚未收集完整参数的受控业务流程。"""

    flow_type: IntentType
    required_slots: tuple[str, ...]
    collected_slots: Mapping[str, SlotValue] = field(default_factory=dict)
    created_turn: int | None = None
    last_updated_turn: int | None = None

    def __post_init__(self) -> None:
        # 防止节点通过共享字典绕过 reducer 修改待办流程。
        object.__setattr__(self, "collected_slots", MappingProxyType(dict(self.collected_slots)))


@dataclass(frozen=True, slots=True)
class TurnDecision:
    """Supervisor 与确定性状态机完成仲裁后的唯一决策。"""

    primary_intent: IntentType
    secondary_intents: tuple[IntentType, ...]
    dialogue_act: DialogueAct
    active_entity: EntityReference | None
    slot_updates: Mapping[str, SlotValue]
    pending_flow: PendingFlow | None
    missing_slots: tuple[str, ...]
    requires_live_data: bool
    side_effect_level: SideEffectLevel
    route: str
    confidence: float
    recognition_source: RecognitionSource
    normalized_result: IntentResult
    unknown_kind: UnknownKind | None = None
    clarification_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot_updates", MappingProxyType(dict(self.slot_updates)))
