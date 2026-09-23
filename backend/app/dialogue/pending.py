"""未完成对话流程的建立、保留和清除规则。"""

from __future__ import annotations

from backend.app.conversation_understanding import IntentResult, IntentType
from backend.app.dialogue.contracts import PendingFlow, SlotValue, UnknownKind


_PENDING_INTENTS = {IntentType.LEARNING_REPORT, IntentType.CLASS_LEARNING_SUMMARY}
_CANCEL_PATTERNS = (
    "取消", "不用了", "先不做", "不生成了", "不查了", "停止查询",
    "算了，不", "算了不",
)


def has_explicit_pending_cancel(message: str) -> bool:
    """只识别明确取消，不把普通“不是这个课程”误当成取消任务。"""

    return any(pattern in message for pattern in _CANCEL_PATTERNS)


def resolve_pending_intent(
    message: str,
    *,
    current: IntentType | None,
    proposed: IntentType | None,
    result: IntentResult,
    unknown_kind: UnknownKind | None,
) -> IntentType | None:
    """按固定优先级决定下一轮是否保留 pending。

    礼貌消息不会清空待补周期；完成当前流程、明确取消或切换到其他确定
    业务时才清除。pending 只恢复兼容参数，不能劫持任意后续问题。
    """

    if has_explicit_pending_cancel(message):
        return None
    if proposed in _PENDING_INTENTS:
        return proposed
    if current is None:
        return None
    if unknown_kind == UnknownKind.SMALL_TALK:
        return current
    if result.intent == current and not result.clarification_needed:
        return None
    if result.intent == IntentType.UNKNOWN and unknown_kind in {
        UnknownKind.UNKNOWN,
        UnknownKind.NEEDS_CLARIFICATION,
    }:
        return current
    # 其他明确业务、域外问题或人工处理请求都视为话题切换。
    return None


def build_pending_flow(
    pending_intent: IntentType | None,
    *,
    slots: dict[str, SlotValue],
) -> tuple[PendingFlow | None, tuple[str, ...]]:
    """把兼容字段转换为结构化 pending，并计算仍缺少的槽位。"""

    if pending_intent == IntentType.LEARNING_REPORT:
        required = ("period_start", "period_end")
    elif pending_intent == IntentType.CLASS_LEARNING_SUMMARY:
        required = ("class_id", "period_start", "period_end")
    else:
        return None, ()
    # 只有已确认槽位才算真正收集完成。模型可以把候选值放进决策对象供
    # 后续澄清展示，但不能因为“有值”就绕过报告和班级统计的执行门禁。
    collected = {
        name: slots[name]
        for name in required
        if name in slots and slots[name].confirmed
    }
    missing = tuple(name for name in required if name not in collected)
    return (
        PendingFlow(
            flow_type=pending_intent,
            required_slots=required,
            collected_slots=collected,
        ),
        missing,
    )
