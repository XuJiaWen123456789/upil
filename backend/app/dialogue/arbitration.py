"""确定性状态机与 Supervisor 结果的统一仲裁。"""

from __future__ import annotations

from backend.app.agents.supervisor import RecognitionSource
from backend.app.conversation_understanding import (
    EntityReference,
    EntityType,
    IntentResult,
    IntentType,
)
from backend.app.dialogue.classification import (
    detect_secondary_intents,
    normalize_primary_intent,
)
from backend.app.dialogue.contracts import (
    DialogueAct,
    SideEffectLevel,
    SlotValue,
    TurnDecision,
    UnknownKind,
)
from backend.app.dialogue.pending import (
    build_pending_flow,
    has_explicit_pending_cancel,
    resolve_pending_intent,
)
from backend.app.dialogue.unknown import (
    classify_unknown_kind,
    is_courtesy,
    is_greeting,
)
from backend.app.services.enrollment_intent import has_explicit_enrollment_decline


_BUSINESS_REQUIRED_SLOTS: dict[IntentType, tuple[str, ...]] = {
    IntentType.LEARNING_REPORT: ("period_start", "period_end"),
    IntentType.CLASS_LEARNING_SUMMARY: ("class_id", "period_start", "period_end"),
}

_ENROLLMENT_DEFER_CONTEXT_MARKERS = (
    "安排", "预约", "试听", "报名", "报课", "联系", "考虑",
)


def _is_course_enrollment_deferral(
    message: str, active_entity: EntityReference | None
) -> bool:
    """识别课程语境中的试听或报名暂缓动作。

    “不同意保存”也可能出现在其他业务中，因此主路由除了要求命中招生
    否定词，还要求已有课程语境且出现安排、试听、报名等销售流程标记。
    联系方式补全场景仍由更严格的线索状态门禁单独处理。
    """

    return bool(
        active_entity is not None
        and active_entity.entity_type in {EntityType.COURSE, EntityType.COURSE_CATEGORY}
        and any(marker in message for marker in _ENROLLMENT_DEFER_CONTEXT_MARKERS)
        and has_explicit_enrollment_decline(message)
    )


def _enforce_confirmed_business_slots(
    result: IntentResult,
    *,
    slots: dict[str, SlotValue],
) -> IntentResult:
    """阻止未确认槽位驱动报告或班级统计工具。

    模型可以辅助判断意图，但模型推断的日期、班级等参数不能直接扩大数据库
    查询范围。只有用户明确提供、白名单解析或会话中已确认的槽位才算完整。
    """

    required = _BUSINESS_REQUIRED_SLOTS.get(result.intent)
    if not required:
        return result
    missing = tuple(
        name
        for name in required
        if name not in slots or not slots[name].confirmed
    )
    if not missing or result.clarification_needed:
        return result
    return result.model_copy(update={"clarification_needed": True})


def resolve_dialogue_route(
    result: IntentResult,
    *,
    unknown_kind: UnknownKind | None = None,
) -> str:
    """把已仲裁意图映射到应用允许的固定路由。"""

    if result.clarification_needed or unknown_kind == UnknownKind.NEEDS_CLARIFICATION:
        return "clarification"
    if unknown_kind == UnknownKind.SMALL_TALK:
        return "small_talk"
    if unknown_kind == UnknownKind.OUT_OF_SCOPE:
        return "out_of_scope"
    if result.intent == IntentType.LEARNING_REPORT:
        return "learning_report"
    if result.intent == IntentType.REPORT_HISTORY:
        return "report_history"
    if result.intent == IntentType.CLASS_LEARNING_SUMMARY:
        return "class_learning_summary"
    if result.intent == IntentType.LEARNING_SUMMARY:
        return "learning_summary"
    if result.intent in {IntentType.COMPLAINT, IntentType.HUMAN_HANDOFF}:
        return "human_handoff"
    if result.needs_live_data:
        return "human_handoff"
    if result.intent in {
        IntentType.SERVICE_RULES,
        IntentType.FEE_REFUND,
        IntentType.SAFETY_HEALTH,
        IntentType.CLASS_TRANSFER,
    }:
        return "service_rules"
    if result.intent == IntentType.UNKNOWN:
        # 只有明确属于机构业务的一般咨询仍允许进入 FAQ；真正无法判断的
        # 消息进入澄清，避免 RAGFlow 为无关问题生成看似可信的答案。
        return "faq" if unknown_kind == UnknownKind.IN_DOMAIN_GENERAL else "clarification"
    return "faq"


def _dialogue_act(
    message: str,
    *,
    active_entity: EntityReference | None,
    slots: dict[str, SlotValue],
) -> DialogueAct:
    if has_explicit_pending_cancel(message):
        return DialogueAct.CANCEL
    if _is_course_enrollment_deferral(message, active_entity):
        return DialogueAct.DEFER
    if is_greeting(message):
        return DialogueAct.GREETING
    if is_courtesy(message):
        return DialogueAct.COURTESY
    if active_entity is not None and active_entity.is_correction:
        return DialogueAct.CORRECTION
    if any(slot.source.value == "user_explicit" for slot in slots.values()):
        return DialogueAct.PROVIDE_SLOT
    if any(marker in message for marker in ("吗", "呢", "？", "?", "多少", "怎么", "如何")):
        return DialogueAct.QUESTION
    return DialogueAct.COMMAND


def _side_effect_level(result: IntentResult, route: str) -> SideEffectLevel:
    if route == "learning_report":
        return SideEffectLevel.WRITE
    if route in {"learning_summary", "class_learning_summary", "report_history"}:
        return SideEffectLevel.READ
    if route == "human_handoff":
        return SideEffectLevel.HUMAN_REVIEW
    return SideEffectLevel.NONE


def arbitrate_turn(
    message: str,
    *,
    result: IntentResult,
    recognition_source: RecognitionSource,
    active_entity: EntityReference | None,
    slot_values: dict[str, SlotValue],
    current_pending: IntentType | None,
    proposed_pending: IntentType | None,
    proposed_route: str,
) -> TurnDecision:
    """输出一次不可变决策，作为 LangGraph 与旁路 Agent 的共同依据。

    优先级固定为：显式取消/安全边界 > pending 兼容补槽 > 主意图 >
    试听报名旁路 > UNKNOWN 分类。该函数只仲裁，不执行任何外部调用。
    """

    normalized = normalize_primary_intent(message, result)
    normalized = _enforce_confirmed_business_slots(normalized, slots=slot_values)
    unknown_kind = classify_unknown_kind(
        message, result=normalized, active_entity=active_entity
    )
    effective_proposed = proposed_pending
    if (
        effective_proposed is None
        and normalized.clarification_needed
        and normalized.intent in _BUSINESS_REQUIRED_SLOTS
    ):
        effective_proposed = normalized.intent
    pending_intent = resolve_pending_intent(
        message,
        current=current_pending,
        proposed=effective_proposed,
        result=normalized,
        unknown_kind=unknown_kind,
    )
    pending_flow, missing_slots = build_pending_flow(pending_intent, slots=slot_values)
    route = (
        proposed_route
        if proposed_route == "memory"
        else resolve_dialogue_route(normalized, unknown_kind=unknown_kind)
    )
    if has_explicit_pending_cancel(message) and current_pending is not None:
        # 取消待办是一个确定性的会话动作，不应再进入 UNKNOWN 澄清，更不能
        # 访问 FAQ/RAG。固定节点会根据 dialogue_act 返回已取消的自然话术。
        route = "small_talk"
    elif _is_course_enrollment_deferral(message, active_entity):
        # 暂缓试听/报名是确定性的会话控制动作，不能因为仍保留课程实体
        # 就回退成 COURSE_DETAIL 并访问 FAQ/RAGFlow。招生旁路会独立负责
        # 撤回当前会话已有线索；主路由只负责给出自然、无副作用的确认。
        route = "small_talk"
    secondary = detect_secondary_intents(
        message, primary_intent=normalized.intent
    )
    clarification_reason = None
    if unknown_kind == UnknownKind.NEEDS_CLARIFICATION:
        clarification_reason = "unresolved_reference_or_missing_business_slot"
    elif unknown_kind == UnknownKind.UNKNOWN:
        clarification_reason = "low_confidence_unknown"

    return TurnDecision(
        primary_intent=normalized.intent,
        secondary_intents=secondary,
        dialogue_act=_dialogue_act(message, active_entity=active_entity, slots=slot_values),
        active_entity=active_entity,
        slot_updates=slot_values,
        pending_flow=pending_flow,
        missing_slots=missing_slots,
        requires_live_data=normalized.needs_live_data,
        side_effect_level=_side_effect_level(normalized, route),
        route=route,
        confidence=normalized.confidence,
        recognition_source=recognition_source,
        normalized_result=normalized,
        unknown_kind=unknown_kind,
        clarification_reason=clarification_reason,
    )
