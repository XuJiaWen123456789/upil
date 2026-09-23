"""对话槽位的来源标记与确认规则。"""

from __future__ import annotations

from datetime import date

from backend.app.conversation_understanding import EntityReference, EntityType
from backend.app.dialogue.contracts import SlotSource, SlotValue
from backend.app.services.course_consultation import (
    extract_child_age,
    extract_programming_foundation,
)
from backend.app.services.preference_values import extract_class_time_preference


def _confirmed(value, source: SlotSource) -> SlotValue:
    """构建可被业务层消费的确定性槽位。"""

    return SlotValue(value=value, source=source, confidence=1.0, confirmed=True)


def collect_slot_values(
    message: str,
    *,
    active_entity: EntityReference | None,
    child_age: int | None,
    programming_foundation: str | None,
    class_time_preference: str | None,
    class_id: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, SlotValue]:
    """把当前规划中的槽位转换成带可信来源的结构化值。

    用户本轮原话和确定性解析器得到的值标记为已确认；从上一轮会话继承的
    稳定咨询槽位标记为 session。这里不接收模型自由生成的工具参数。
    """

    slots: dict[str, SlotValue] = {}
    explicit_age = extract_child_age(message)
    explicit_foundation = extract_programming_foundation(message)
    explicit_time = extract_class_time_preference(message)

    if child_age is not None:
        source = SlotSource.USER_EXPLICIT if explicit_age == child_age else SlotSource.SESSION
        slots["child_age"] = _confirmed(child_age, source)
    if programming_foundation is not None:
        source = (
            SlotSource.USER_EXPLICIT
            if explicit_foundation == programming_foundation
            else SlotSource.SESSION
        )
        slots["programming_foundation"] = _confirmed(programming_foundation, source)
    if class_time_preference is not None:
        source = (
            SlotSource.USER_EXPLICIT
            if explicit_time == class_time_preference
            else SlotSource.SESSION
        )
        slots["class_time_preference"] = _confirmed(class_time_preference, source)
    if class_id is not None:
        source = (
            SlotSource.USER_EXPLICIT
            if active_entity is not None
            and active_entity.entity_type == EntityType.CLASS
            and active_entity.is_explicit
            else SlotSource.SESSION
        )
        slots["class_id"] = _confirmed(class_id, source)
    if period_start is not None and period_end is not None:
        # 日期由白名单自然语言解析器得到，不是模型根据摘要猜测。
        slots["period_start"] = _confirmed(period_start, SlotSource.DETERMINISTIC)
        slots["period_end"] = _confirmed(period_end, SlotSource.DETERMINISTIC)
    return slots
