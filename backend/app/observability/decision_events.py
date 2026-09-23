"""对话决策链的脱敏结构化事件。

本模块刻意不接收用户消息、会话编号、用户编号、学员编号或联系方式。日志
只保留受控枚举、槽位名称和耗时，既能定位路由与状态机问题，又不会把业务
数据复制到日志系统。模型思维链、Prompt 和原始输出同样不属于可观测字段。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import re
from typing import Mapping

from backend.app.dialogue import TurnDecision


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
_SLOT_NAMES = frozenset({
    "child_age",
    "programming_foundation",
    "class_time_preference",
    "class_id",
    "period_start",
    "period_end",
})
_MODEL_FALLBACK_REASONS = frozenset({
    "model_not_configured",
    "invalid_or_timed_out_model_output",
    "model_provider_error",
})
_LEAD_FALLBACK_REASONS = frozenset({
    "model_not_configured",
    "invalid_or_provider_fallback",
    "timeout",
    "budget_exhausted",
    "provider_error",
    "contact_follow_up_deterministic",
    "storage_or_protection",
})
_DECISION_SOURCES = frozenset({
    "deterministic_guard",
    "model",
    "deterministic_fallback",
})
_ROUTES = frozenset({
    "faq",
    "service_rules",
    "learning_summary",
    "class_learning_summary",
    "learning_report",
    "report_history",
    "human_handoff",
    "clarification",
    "small_talk",
    "out_of_scope",
    "memory",
    "lead_contact_follow_up",
})


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    """一轮请求的安全诊断字段，不包含可还原业务主体的数据。"""

    request_id: str
    decision_source: str
    primary_intent: str | None
    secondary_intents: tuple[str, ...]
    route: str
    dialogue_act: str | None
    unknown_kind: str | None
    pending_flow: str | None
    missing_slot_names: tuple[str, ...]
    slot_sources: Mapping[str, str]
    model_fallback_reason: str | None
    lead_sidecar_fallback_reason: str | None
    contact_redaction_applied: bool
    planning_duration_ms: int
    total_duration_ms: int

    def to_json(self) -> str:
        """以稳定字段顺序输出 JSON，便于日志平台聚合。"""

        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def _safe_request_id(request_id: str | None) -> str:
    """只接受中间件允许的追踪编号，拒绝把任意请求头写入日志。"""

    if request_id and _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    return "request_id_unavailable"


def _allowed_reason(value: str | None, allowed: frozenset[str]) -> str | None:
    """失败原因只能来自代码定义的低基数枚举。"""

    return value if value in allowed else None


def build_decision_event(
    *,
    request_id: str | None,
    route: str,
    decision: TurnDecision | None,
    decision_source: str,
    model_fallback_reason: str | None = None,
    lead_sidecar_fallback_reason: str | None = None,
    contact_redaction_applied: bool = False,
    planning_duration_ms: int = 0,
    total_duration_ms: int = 0,
) -> DecisionEvent:
    """从决策契约构造白名单事件；槽位只输出名称和来源。"""

    slot_sources = {}
    missing_slots: tuple[str, ...] = ()
    if decision is not None:
        slot_sources = {
            name: value.source.value
            for name, value in decision.slot_updates.items()
            if name in _SLOT_NAMES
        }
        missing_slots = tuple(
            name for name in decision.missing_slots if name in _SLOT_NAMES
        )

    return DecisionEvent(
        request_id=_safe_request_id(request_id),
        decision_source=(
            decision_source if decision_source in _DECISION_SOURCES else "unknown"
        ),
        primary_intent=(decision.primary_intent.value if decision else None),
        secondary_intents=(
            tuple(intent.value for intent in decision.secondary_intents)
            if decision
            else ()
        ),
        route=route if route in _ROUTES else "unknown",
        dialogue_act=(decision.dialogue_act.value if decision else None),
        unknown_kind=(
            decision.unknown_kind.value
            if decision and decision.unknown_kind is not None
            else None
        ),
        pending_flow=(
            decision.pending_flow.flow_type.value
            if decision and decision.pending_flow is not None
            else None
        ),
        missing_slot_names=missing_slots,
        slot_sources=slot_sources,
        model_fallback_reason=_allowed_reason(
            model_fallback_reason, _MODEL_FALLBACK_REASONS
        ),
        lead_sidecar_fallback_reason=_allowed_reason(
            lead_sidecar_fallback_reason, _LEAD_FALLBACK_REASONS
        ),
        contact_redaction_applied=bool(contact_redaction_applied),
        planning_duration_ms=max(0, int(planning_duration_ms)),
        total_duration_ms=max(0, int(total_duration_ms)),
    )


def log_decision_event(logger: logging.Logger, event: DecisionEvent) -> None:
    """写入单行结构化事件，不附加自由文本或异常正文。"""

    logger.info("dialogue_decision %s", event.to_json())
