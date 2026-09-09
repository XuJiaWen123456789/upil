"""对话理解所需的结构化契约和确定性实体处理。

本模块只负责可以稳定测试的基础能力：实体类型定义、课程名称标准化、
显式纠正后的实体覆盖、基础指代消解和检索查询改写。结构化 LLM 调用与
LangGraph 状态接入将在下一小步完成，避免一次改动影响现有 FAQ/SSE 链路。
"""

from datetime import date
from enum import Enum
import re

from pydantic import BaseModel, ConfigDict, Field


class IntentType(str, Enum):
    """Supervisor 允许输出的业务意图白名单。

    使用枚举而不是任意字符串，可防止模型返回工作流中不存在的路由名称。
    """

    COURSE_RECOMMENDATION = "course_recommendation"
    COURSE_DETAIL = "course_detail"
    COURSE_BENEFIT = "course_benefit"
    TEACHER_DETAIL = "teacher_detail"
    CAMPUS_DETAIL = "campus_detail"
    TRIAL_BOOKING = "trial_booking"
    ENROLLMENT = "enrollment"
    CLASS_TRANSFER = "class_transfer"
    SCHEDULE_OR_SEAT = "schedule_or_seat"
    LEARNING_SUMMARY = "learning_summary"
    CLASS_LEARNING_SUMMARY = "class_learning_summary"
    LEARNING_REPORT = "learning_report"
    FEE_REFUND = "fee_refund"
    SAFETY_HEALTH = "safety_health"
    SERVICE_RULES = "service_rules"
    COMPLAINT = "complaint"
    HUMAN_HANDOFF = "human_handoff"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    """公开咨询阶段需要识别的通用实体类型。"""

    COURSE = "course"
    COURSE_CATEGORY = "course_category"
    CLASS = "class"
    TEACHER = "teacher"
    CAMPUS = "campus"
    SERVICE = "service"
    POLICY = "policy"
    UNKNOWN = "unknown"


class EntityReference(BaseModel):
    """对话中一个业务对象的轻量引用。

    这里不保存课程年龄、教师履历等知识正文，只保存状态管理与检索改写
    必需的信息，避免实体模型随着知识文档数量增长而无限膨胀。
    """

    entity_type: EntityType = EntityType.UNKNOWN
    entity_name: str | None = None
    raw_mention: str | None = None
    is_explicit: bool = False
    is_correction: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # 模型输出存在未知字段时直接拒绝，不能静默吞掉潜在的任意工具参数。
    model_config = ConfigDict(extra="forbid")


class IntentResult(BaseModel):
    """未来结构化 LLM 意图识别节点必须返回的统一契约。"""

    intent: IntentType = IntentType.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    mentioned_entity: EntityReference | None = None
    requested_attributes: list[str] = Field(default_factory=list)
    needs_live_data: bool = False
    clarification_needed: bool = False

    # JSON Schema 与运行时校验保持一致，防止模型扩展未授权的业务字段。
    model_config = ConfigDict(extra="forbid")


class TurnResolution(BaseModel):
    """完成一轮确定性实体处理后的结果。"""

    mentioned_entity: EntityReference | None = None
    active_entity: EntityReference | None = None
    rewritten_query: str
    requested_attributes: list[str] = Field(default_factory=list)
    used_context: bool = False


class ClassLearningQuery(BaseModel):
    """班级学情统计请求的结构化参数。

    class_id 只能来自班级白名单映射，不能直接使用用户输入作为数据库
    查询条件；日期和低课时阈值在进入统计工具前还会再次校验。
    """

    class_id: str | None = None
    class_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    low_balance_threshold: int = Field(default=5, ge=0, le=10000)

    # 禁止模型或上游请求偷偷添加 SQL、用户筛选等未授权字段。
    model_config = ConfigDict(extra="forbid")


# 标准课程名与家长常见表达的映射。知识库增加正式课程时，应同时更新此表，
# 后续可迁移到数据库或课程目录 API，而不是长期硬编码在 Python 中。
COURSE_ALIASES: dict[str, tuple[str, ...]] = {
    "舞蹈启蒙班": ("舞蹈启蒙班", "舞蹈启蒙"),
    "中国舞基础班": ("中国舞基础班", "中国舞基础"),
    "中国舞进阶班": ("中国舞进阶班", "中国舞进阶"),
    "少儿美术创意班": ("少儿美术创意班", "美术创意班", "美术创意"),
    "素描基础班": ("素描基础班", "素描基础"),
    "少儿编程基础班": ("少儿编程基础班", "编程基础班", "少儿编程基础"),
    "编程项目实践班": (
        "编程项目实践班",
        "少儿编程项目实践班",
        "编程项目班",
        "编程项目实践",
    ),
    "音乐启蒙班": ("音乐启蒙班", "音乐启蒙"),
    "童声合唱班": ("童声合唱班", "童声合唱"),
}

COURSE_CATEGORIES: tuple[str, ...] = ("舞蹈", "美术", "音乐", "编程")

# 班级名称必须通过内部白名单映射到稳定 ID，避免自然语言直接进入查询层。
# 目前沿用项目已有的舞蹈班级，不新增课程或虚构 Python 班级。
CLASS_ALIASES: dict[str, tuple[str, ...]] = {
    "CLASS_DANCE_01": ("舞蹈一班", "舞蹈1班", "中国舞一班", "中国舞1班"),
    "CLASS_DANCE_02": ("舞蹈二班", "舞蹈2班", "中国舞二班", "中国舞2班"),
}

# 用户明确修正上一轮对象时常用的语言标记。
CORRECTION_MARKERS: tuple[str, ...] = (
    "不是",
    "改成",
    "改问",
    "我说的是",
    "说错了",
    "应该是",
    "是指",
)

# 这里只处理课程类基础指代。教师、校区等指代需要在相应知识文档接入后
# 使用最近实体列表和类型约束扩展，不能把所有“他/它/那里”盲目绑定。
COURSE_REFERENCES: tuple[str, ...] = (
    "这个课程",
    "该课程",
    "这门课程",
    "这门课",
    "这个班",
    "该班",
)

ATTRIBUTE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "age_range": ("多大", "几岁", "年龄", "适龄"),
    "duration": ("多长时间", "多久", "时长", "多少分钟", "一节课"),
    "prerequisite": ("什么基础", "需要基础", "零基础", "前置", "入学条件"),
    "teaching_style": ("授课风格", "教学风格"),
    "experience": ("履历", "经历", "资历"),
    "address": ("在哪里", "怎么走", "地址", "位置"),
    "schedule": ("排课", "什么时候上课", "上课时间", "时段"),
    "available_seats": ("名额", "空位", "还能报名"),
}


def _course_alias_entries() -> list[tuple[str, str]]:
    """返回按别名长度降序排列的“别名—标准名”列表。

    长名称优先可以避免“编程项目实践班”先被较短的“编程”误识别。
    """

    entries = [
        (alias, canonical)
        for canonical, aliases in COURSE_ALIASES.items()
        for alias in aliases
    ]
    return sorted(entries, key=lambda item: len(item[0]), reverse=True)


COURSE_ALIAS_ENTRIES = _course_alias_entries()


def _class_alias_entries() -> list[tuple[str, str]]:
    """返回按别名长度降序排列的“别名—班级 ID”列表。"""

    entries = [
        (alias, class_id)
        for class_id, aliases in CLASS_ALIASES.items()
        for alias in aliases
    ]
    return sorted(entries, key=lambda item: len(item[0]), reverse=True)


CLASS_ALIAS_ENTRIES = _class_alias_entries()


def normalize_course_name(text: str) -> str | None:
    """从文本中识别课程别名并返回知识库使用的标准课程名。"""

    matched = _find_course_mention(text)
    return matched[1] if matched else None


def _find_course_mention(text: str) -> tuple[str, str, int, int] | None:
    """返回课程别名、标准名及其在原文中的起止位置。"""

    for alias, canonical in COURSE_ALIAS_ENTRIES:
        start = text.find(alias)
        if start >= 0:
            return alias, canonical, start, start + len(alias)
    return None


def _find_class_mention(text: str) -> tuple[str, str, int, int] | None:
    """返回班级别名、稳定班级 ID 及其在原文中的起止位置。"""

    for alias, class_id in CLASS_ALIAS_ENTRIES:
        start = text.find(alias)
        if start >= 0:
            return alias, class_id, start, start + len(alias)
    return None


def normalize_class_name(text: str) -> str | None:
    """将家长常用班级称呼转换为内部白名单班级 ID。"""

    matched = _find_class_mention(text)
    return matched[1] if matched else None


def extract_class_reference(message: str) -> EntityReference | None:
    """只从班级白名单中提取班级实体，不对未知班级进行猜测。"""

    matched = _find_class_mention(message)
    if matched is None:
        return None
    alias, class_id, _, _ = matched
    return EntityReference(
        entity_type=EntityType.CLASS,
        entity_name=class_id,
        raw_mention=alias,
        is_explicit=True,
        is_correction=any(marker in message for marker in CORRECTION_MARKERS),
        confidence=1.0 if alias in {"舞蹈一班", "舞蹈二班"} else 0.95,
    )


def extract_entity_reference(message: str) -> EntityReference | None:
    """按“班级—具体课程—课程大类”的顺序识别实体。

    本函数是确定性基线，不声称能够识别任意教师或校区名称。未来 LLM
    抽取结果仍需经过课程/教师/校区白名单校验后才能写入会话状态。
    """

    # “舞蹈一班”同时包含课程类别词“舞蹈”，班级必须优先识别，
    # 否则会把班级统计误路由成普通课程咨询。
    class_entity = extract_class_reference(message)
    if class_entity is not None:
        return class_entity

    matched = _find_course_mention(message)
    is_correction = any(marker in message for marker in CORRECTION_MARKERS)
    if matched:
        alias, canonical, _, _ = matched
        return EntityReference(
            entity_type=EntityType.COURSE,
            entity_name=canonical,
            raw_mention=alias,
            is_explicit=True,
            is_correction=is_correction,
            # 完全使用标准名时置信度最高，别名匹配略低。
            confidence=1.0 if alias == canonical else 0.95,
        )

    for category in sorted(COURSE_CATEGORIES, key=len, reverse=True):
        if category in message:
            return EntityReference(
                entity_type=EntityType.COURSE_CATEGORY,
                entity_name=category,
                raw_mention=category,
                is_explicit=True,
                is_correction=is_correction,
                confidence=0.9,
            )
    return None


def extract_requested_attributes(message: str) -> list[str]:
    """按稳定顺序提取用户本轮明确询问的属性。"""

    return [
        attribute
        for attribute, keywords in ATTRIBUTE_KEYWORDS.items()
        if any(keyword in message for keyword in keywords)
    ]


def has_course_reference(message: str) -> bool:
    """判断文本是否包含可以安全绑定到课程实体的明确指代表达。"""

    return any(reference in message for reference in COURSE_REFERENCES)


def _rewrite_explicit_correction(
    message: str, mentioned_entity: EntityReference
) -> str:
    """移除纠正语句中的旧实体，只保留新课程及其后续问题。

    例如“不是舞蹈，是编程项目实践班，适合几岁”会被改写为
    “编程项目实践班，适合几岁”，避免否定实体干扰向量和全文检索。
    """

    raw_mention = mentioned_entity.raw_mention or mentioned_entity.entity_name
    entity_name = mentioned_entity.entity_name
    if not raw_mention or not entity_name:
        return message.strip()

    start = message.find(raw_mention)
    if start < 0:
        return message.strip()
    tail = message[start + len(raw_mention) :]
    return f"{entity_name}{tail}".strip()


def rewrite_query(
    message: str,
    active_entity: EntityReference | None,
    mentioned_entity: EntityReference | None = None,
) -> tuple[str, bool]:
    """将依赖上下文的追问改写成可独立检索的问题。

    返回值中的布尔量表示是否使用了历史实体。显式提到新课程时不会把旧
    课程写入查询；纠正语句会去掉旧对象，降低错误召回概率。
    """

    query = message.strip()
    if mentioned_entity and mentioned_entity.entity_name:
        if mentioned_entity.is_correction:
            query = _rewrite_explicit_correction(query, mentioned_entity)
        return query, False

    if not active_entity or not active_entity.entity_name:
        return query, False
    if active_entity.entity_type not in {
        EntityType.COURSE,
        EntityType.COURSE_CATEGORY,
        EntityType.CLASS,
    }:
        return query, False

    entity_name = active_entity.entity_name
    if has_course_reference(query):
        for reference in COURSE_REFERENCES:
            query = query.replace(reference, entity_name)
        return query, True

    # 省略“这个课程”的短追问只有在明确询问课程属性时才继承历史实体，
    # 避免把“谢谢”“还有别的吗”等普通表达错误改写成课程查询。
    if extract_requested_attributes(query):
        return f"{entity_name}：{query}", True
    return query, False


def resolve_turn(
    message: str, active_entity: EntityReference | None = None
) -> TurnResolution:
    """解析一轮消息，并按“本轮明确实体优先”更新当前实体。"""

    mentioned_entity = extract_entity_reference(message)
    resolved_active = mentioned_entity or active_entity
    rewritten_query, used_context = rewrite_query(
        message,
        active_entity=resolved_active,
        mentioned_entity=mentioned_entity,
    )
    return TurnResolution(
        mentioned_entity=mentioned_entity,
        active_entity=resolved_active,
        rewritten_query=rewritten_query,
        requested_attributes=extract_requested_attributes(message),
        used_context=used_context,
    )
