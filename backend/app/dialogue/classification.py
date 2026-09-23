"""主意图与旁路意图分离规则。"""

from __future__ import annotations

from backend.app.conversation_understanding import IntentResult, IntentType
from backend.app.services.enrollment_intent import (
    has_explicit_enrollment_action,
    has_explicit_trial_action,
)


def detect_secondary_intents(
    message: str,
    *,
    primary_intent: IntentType,
) -> tuple[IntentType, ...]:
    """提取不会覆盖主回答的试听和报名旁路意图。"""

    candidates: list[IntentType] = []
    if has_explicit_trial_action(message):
        candidates.append(IntentType.TRIAL_BOOKING)
    if has_explicit_enrollment_action(message):
        candidates.append(IntentType.ENROLLMENT)
    return tuple(intent for intent in candidates if intent != primary_intent)


def normalize_primary_intent(message: str, result: IntentResult) -> IntentResult:
    """复合诉求中让信息问题决定主回答，动作意图进入旁路。

    例如“这个班多少钱，我还想预约试听”应先回答价格问题；试听意图由
    线索 Agent 并行处理，不能覆盖课程详情主路由。
    """

    has_action = has_explicit_trial_action(message) or has_explicit_enrollment_action(message)
    substantive_attributes = set(result.requested_attributes) - {"trial_policy"}
    if (
        has_action
        and substantive_attributes
        and result.intent in {IntentType.TRIAL_BOOKING, IntentType.ENROLLMENT}
    ):
        return result.model_copy(update={"intent": IntentType.COURSE_DETAIL})
    return result
