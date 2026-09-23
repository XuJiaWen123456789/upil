"""模型结果的实体规范化和业务白名单校验。

Pydantic 只验证结构；本模块继续验证课程、班级、属性和实时数据边界，
确保模型不能把任意文本变成活动实体或后续查询参数。
"""

from backend.app.conversation_understanding import (
    COURSE_ALIASES,
    COURSE_CATEGORIES,
    EntityReference,
    EntityType,
    IntentResult,
    IntentType,
    TurnResolution,
    has_course_reference,
    normalize_class_name,
    normalize_course_name,
)

from .constants import ALLOWED_REQUESTED_ATTRIBUTES, LOW_CONFIDENCE_THRESHOLD
from .rules import context_entity, requires_live_data


def course_candidate_names(message: str) -> set[str]:
    """提取消息中参与比较或选择的课程候选。"""

    from .constants import COURSE_CATEGORY_MENTIONS

    candidates: set[str] = set()
    for canonical, aliases in COURSE_ALIASES.items():
        if any(alias in message for alias in aliases):
            candidates.add(canonical)
    for category, aliases in COURSE_CATEGORY_MENTIONS.items():
        if any(alias in message for alias in aliases):
            candidates.add(category)
    return candidates


def normalize_model_entity(
    model_entity: EntityReference | None,
    turn: TurnResolution,
) -> tuple[EntityReference | None, bool]:
    """校验模型实体，返回规范实体和是否需要澄清。"""

    if turn.mentioned_entity is not None:
        return turn.mentioned_entity, False
    contextual = context_entity(turn)
    if contextual is not None:
        return contextual, False
    if model_entity is None:
        return None, False

    raw_name = model_entity.raw_mention or model_entity.entity_name or ""
    if model_entity.entity_type == EntityType.COURSE:
        canonical = normalize_course_name(model_entity.entity_name or raw_name)
        if canonical is not None:
            return model_entity.model_copy(
                update={
                    "entity_name": canonical,
                    "confidence": min(model_entity.confidence, 0.95),
                }
            ), False
        for category in COURSE_CATEGORIES:
            if category in raw_name:
                return EntityReference(
                    entity_type=EntityType.COURSE_CATEGORY,
                    entity_name=category,
                    raw_mention=raw_name or None,
                    is_explicit=model_entity.is_explicit,
                    is_correction=model_entity.is_correction,
                    confidence=min(model_entity.confidence, 0.5),
                ), True
        return EntityReference(
            entity_type=EntityType.UNKNOWN,
            raw_mention=raw_name or None,
            is_explicit=model_entity.is_explicit,
            is_correction=model_entity.is_correction,
            confidence=0.0,
        ), True

    if model_entity.entity_type == EntityType.COURSE_CATEGORY:
        if model_entity.entity_name in COURSE_CATEGORIES:
            return model_entity, False
        return EntityReference(
            entity_type=EntityType.UNKNOWN,
            raw_mention=raw_name or None,
            is_explicit=model_entity.is_explicit,
            is_correction=model_entity.is_correction,
            confidence=0.0,
        ), True

    if model_entity.entity_type == EntityType.CLASS:
        canonical = normalize_class_name(model_entity.entity_name or raw_name)
        if canonical is not None:
            return model_entity.model_copy(
                update={
                    "entity_name": canonical,
                    "confidence": min(model_entity.confidence, 0.95),
                }
            ), False
        return EntityReference(
            entity_type=EntityType.UNKNOWN,
            raw_mention=raw_name or None,
            is_explicit=model_entity.is_explicit,
            is_correction=model_entity.is_correction,
            confidence=0.0,
        ), True

    if model_entity.entity_type in {EntityType.TEACHER, EntityType.CAMPUS}:
        # 教师与校区尚未形成正式白名单，只允许作为待核验提及保留。
        return EntityReference(
            entity_type=EntityType.UNKNOWN,
            raw_mention=raw_name or None,
            is_explicit=model_entity.is_explicit,
            is_correction=model_entity.is_correction,
            confidence=min(model_entity.confidence, 0.4),
        ), True

    return model_entity, False


def validate_business_result(
    result: IntentResult,
    *,
    message: str,
    turn: TurnResolution,
) -> IntentResult:
    """在结构校验后执行实体、属性和实时数据业务校验。"""

    candidates = course_candidate_names(message)
    unresolved_reference = (
        has_course_reference(message)
        and turn.mentioned_entity is None
        and not turn.used_context
        and turn.active_entity is None
    )
    is_multi_candidate_recommendation = (
        result.intent == IntentType.COURSE_RECOMMENDATION and len(candidates) >= 2
    )
    if unresolved_reference:
        entity, entity_needs_clarification = None, True
    elif is_multi_candidate_recommendation:
        # 当前状态只允许一个活动实体，比较问题不能任选一个写入。
        entity, entity_needs_clarification = None, False
    else:
        entity, entity_needs_clarification = normalize_model_entity(
            result.mentioned_entity, turn
        )

    attributes = list(
        dict.fromkeys(
            attribute
            for attribute in (*turn.requested_attributes, *result.requested_attributes)
            if attribute in ALLOWED_REQUESTED_ATTRIBUTES
        )
    )
    needs_clarification = (
        (result.clarification_needed and not is_multi_candidate_recommendation)
        or result.confidence < LOW_CONFIDENCE_THRESHOLD
        or entity_needs_clarification
    )
    return result.model_copy(
        update={
            "mentioned_entity": entity,
            "requested_attributes": attributes,
            "needs_live_data": result.needs_live_data
            or requires_live_data(message, result.intent),
            "clarification_needed": needs_clarification,
        }
    )
