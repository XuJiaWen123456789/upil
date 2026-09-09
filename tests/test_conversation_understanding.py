"""结构化实体契约、实体覆盖和查询改写的单元测试。"""

import pytest
from pydantic import ValidationError

from backend.app.conversation_understanding import (
    EntityReference,
    EntityType,
    IntentResult,
    IntentType,
    extract_entity_reference,
    normalize_course_name,
    resolve_turn,
)


def test_course_alias_is_normalized_to_canonical_name() -> None:
    """用户简称应映射成知识库中的正式课程名称。"""

    assert normalize_course_name("想了解编程项目班") == "编程项目实践班"


def test_specific_course_has_priority_over_course_category() -> None:
    """具体课程和课程大类同时出现时必须保留更精确的具体课程。"""

    entity = extract_entity_reference("编程项目实践班属于什么编程课程？")
    assert entity is not None
    assert entity.entity_type == EntityType.COURSE
    assert entity.entity_name == "编程项目实践班"


def test_explicit_correction_overrides_previous_course() -> None:
    """“不是A，是B”必须用本轮的新课程覆盖历史课程。"""

    previous = EntityReference(
        entity_type=EntityType.COURSE,
        entity_name="中国舞进阶班",
        is_explicit=True,
        confidence=1.0,
    )
    result = resolve_turn("不是舞蹈，是编程项目实践班", previous)

    assert result.active_entity is not None
    assert result.active_entity.entity_name == "编程项目实践班"
    assert result.active_entity.is_correction is True
    assert "中国舞进阶班" not in result.rewritten_query
    assert result.rewritten_query == "编程项目实践班"


def test_course_pronoun_uses_latest_active_entity() -> None:
    """“这个课程”应绑定到最近一次已经确认的课程实体。"""

    active = EntityReference(
        entity_type=EntityType.COURSE,
        entity_name="编程项目实践班",
        is_explicit=True,
        confidence=1.0,
    )
    result = resolve_turn("这个课程适合多大孩子？需要什么基础？", active)

    assert result.active_entity == active
    assert result.used_context is True
    assert result.rewritten_query == "编程项目实践班适合多大孩子？需要什么基础？"
    assert result.requested_attributes == ["age_range", "prerequisite"]


def test_implicit_attribute_follow_up_is_prefixed_with_active_course() -> None:
    """省略指代词的属性追问也应补全当前课程，形成独立可检索问题。"""

    active = EntityReference(
        entity_type=EntityType.COURSE,
        entity_name="童声合唱班",
        confidence=1.0,
    )
    result = resolve_turn("适合几岁？一节课多久？", active)

    assert result.used_context is True
    assert result.rewritten_query == "童声合唱班：适合几岁？一节课多久？"
    assert result.requested_attributes == ["age_range", "duration"]


def test_unrelated_short_message_is_not_forced_to_use_course_context() -> None:
    """普通寒暄不能因为历史课程存在就被错误改写。"""

    active = EntityReference(
        entity_type=EntityType.COURSE,
        entity_name="音乐启蒙班",
        confidence=1.0,
    )
    result = resolve_turn("谢谢", active)

    assert result.used_context is False
    assert result.rewritten_query == "谢谢"


def test_three_turn_course_switch_resolves_to_programming_project_course() -> None:
    """复现本项目已经发现的三轮课程切换失败案例。"""

    first = resolve_turn("孩子8岁，想学中国舞进阶班")
    second = resolve_turn("不是舞蹈，是编程项目实践班", first.active_entity)
    third = resolve_turn(
        "这个课程适合多大孩子？需要什么基础？一节课多长时间？",
        second.active_entity,
    )

    assert third.active_entity is not None
    assert third.active_entity.entity_name == "编程项目实践班"
    assert third.rewritten_query == (
        "编程项目实践班适合多大孩子？需要什么基础？一节课多长时间？"
    )
    assert third.requested_attributes == ["age_range", "duration", "prerequisite"]


def test_intent_contract_rejects_confidence_outside_valid_range() -> None:
    """结构化模型输出中的置信度必须在0到1之间。"""

    with pytest.raises(ValidationError):
        IntentResult(intent=IntentType.COURSE_DETAIL, confidence=1.2)


def test_generic_entity_schema_can_represent_teacher_without_extra_profile_fields() -> None:
    """通用实体契约可表示教师，无需提前结构化全部教师履历。"""

    entity = EntityReference(
        entity_type=EntityType.TEACHER,
        entity_name="林老师",
        raw_mention="林老师",
        is_explicit=True,
        confidence=0.98,
    )
    assert entity.entity_name == "林老师"
    assert not hasattr(entity, "teaching_resume")
