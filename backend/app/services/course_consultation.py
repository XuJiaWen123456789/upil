"""课程咨询中的轻量槽位识别与确定性推荐。

本模块只处理短期会话中的非敏感咨询信息，例如孩子年龄、编程基础、
课程兴趣和稳定上课时段。
它不会保存姓名、联系方式或学情数据，也不会替代 RAGFlow 回答价格、名额、
教师安排等动态事实。把这类槽位从通用 FAQ 检索中提前解析，可以避免用户
仅回复“12岁”时按数字全库检索，进而错误召回其他课程。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from backend.app.conversation_understanding import (
    EntityReference,
    EntityType,
    extract_requested_attributes,
    has_course_reference,
    rewrite_query,
)
from backend.app.services.enrollment_intent import (
    has_explicit_enrollment_action,
    has_explicit_trial_action,
    is_trial_process_question,
)
from backend.app.services.course_equipment import course_equipment_answer
from backend.app.services.preference_values import extract_class_time_preference


@dataclass(frozen=True, slots=True)
class CourseProfile:
    """确定性课程目录中用于初步筛选的最小字段。"""

    name: str
    category: str
    min_age: int
    max_age: int
    prerequisite: str


@dataclass(frozen=True, slots=True)
class ConsultationFollowUp:
    """一轮槽位补全的结果；None 表示该轮不属于槽位回答。"""

    child_age: int | None
    programming_foundation: str | None
    class_time_preference: str | None
    rewritten_query: str
    answer: str
    # 试听和报名虽然都进入销售顾问流程，但用户期待的下一步不同；用受控
    # 动作值把主回答、Supervisor 意图和线索旁路保持在同一语义上。
    action: Literal["trial", "enrollment", "trial_and_enrollment"] = "trial"
    # 当课程大类结合用户明确提供的年龄/基础后只剩一个合适班型时，记录
    # 该确定性推荐结果。规划器会把它提升为后续轮次的活动课程实体，使
    # “这个班怎么试听”“先不用安排”等表达指向具体班型，而不是退回大类。
    recommended_course_name: str | None = None


# 年龄和准入条件属于稳定课程目录，允许用于确定性初筛。实时名额、价格和
# 教师安排不进入本表，仍必须通过对应知识域或业务系统查询。
COURSE_PROFILES: tuple[CourseProfile, ...] = (
    CourseProfile("舞蹈启蒙班", "舞蹈", 4, 6, "无需舞蹈基础"),
    CourseProfile("中国舞基础班", "舞蹈", 6, 12, "可从基础阶段开始"),
    CourseProfile("中国舞进阶班", "舞蹈", 8, 16, "建议已有中国舞基础或通过教师评估"),
    CourseProfile("少儿美术创意班", "美术", 5, 10, "无需美术基础"),
    CourseProfile("素描基础班", "美术", 10, 14, "建议能够持续完成课堂练习"),
    CourseProfile("音乐启蒙班", "音乐", 4, 8, "无需音乐基础"),
    CourseProfile("童声合唱班", "音乐", 7, 12, "建议通过基础音准与节奏评估"),
    CourseProfile("少儿编程基础班", "编程", 8, 12, "适合零基础，从图形化编程开始"),
    CourseProfile("编程项目实践班", "编程", 10, 14, "建议已完成图形化编程基础或通过教师评估"),
)

_PROFILE_BY_NAME = {profile.name: profile for profile in COURSE_PROFILES}
_AGE_PATTERN = re.compile(r"(?<!\d)([3-9]|1[0-8])\s*(?:岁|周岁)(?!\d)")
_PROGRAMMING_TERMS = ("编程", "scratch", "图形化", "代码", "项目")
# “没有编程基础”不能只靠“没基础”这个连续短语覆盖；把常见的
# 否定表达单独列出，才能正确处理家长一次性提供“12岁，没有编程基础”。
# 这里刻意不把“没有做过完整项目”当成零基础，因为后半句可能继续说明
# 孩子已经学过 Scratch，不能被前半句覆盖。
_NO_FOUNDATION_PATTERNS = (
    "没有编程基础", "无编程基础", "完全没编程基础", "完全没有编程基础",
    "没学过编程", "没有学过编程", "从未学过编程", "从来没学过编程",
    "没学过图形化编程", "没有学过图形化编程", "从未学过图形化编程",
    "从来没学过图形化编程", "没接触过图形化编程", "没有接触过图形化编程",
    # message 会先执行 casefold，因此英文产品名也必须使用小写常量；否则
    # “没有学过 Scratch”会先命中后面的正向“学过”而被误判为已有基础。
    "没学过scratch", "没有学过scratch", "没学过 scratch", "没有学过 scratch",
    "没接触过编程", "没有接触过编程", "完全没基础", "完全没有基础",
    "没基础", "零基础", "从来没学过", "从未学过",
)
_GRAPHICAL_FOUNDATION_PATTERNS = ("scratch", "图形化编程", "编程猫", "积木编程")
_PROJECT_FOUNDATION_PATTERNS = ("做过项目", "项目经验", "项目实践")
_CHILD_SUBJECT_MARKERS = ("孩子", "小朋友", "宝宝", "他", "她")
_POSITIVE_INTEREST_MARKERS = ("喜欢", "感兴趣", "有兴趣", "想学", "偏爱")
_NEGATIVE_INTEREST_MARKERS = ("不喜欢", "不感兴趣", "不想学", "没兴趣")
_NON_CONSULTATION_TERMS = (
    "请假", "补课", "调课", "退费", "退款", "名额", "排课",
    "出勤", "课时", "学情", "报告", "投诉", "转人工",
)


def extract_child_age(message: str) -> int | None:
    """提取明确带“岁”的年龄；裸数字不会被猜成年龄。"""

    match = _AGE_PATTERN.search(message)
    return int(match.group(1)) if match else None


def extract_programming_foundation(message: str) -> str | None:
    """把常见编程学习经历归一为受控枚举。"""

    normalized = message.casefold()
    if any(pattern in normalized for pattern in _NO_FOUNDATION_PATTERNS):
        return "none"
    if any(pattern in normalized for pattern in _PROJECT_FOUNDATION_PATTERNS):
        return "project"
    if any(pattern in normalized for pattern in _GRAPHICAL_FOUNDATION_PATTERNS) and any(
        marker in normalized for marker in ("学过", "学了", "会", "接触过", "上过")
    ):
        return "graphical"
    return None


def _entity_course_scope(entity: EntityReference | None) -> tuple[str | None, str | None]:
    """返回“具体课程、课程类别”，只接受已经校验过的活动实体。"""

    if entity is None or not entity.entity_name:
        return None, None
    if entity.entity_type == EntityType.COURSE:
        profile = _PROFILE_BY_NAME.get(entity.entity_name)
        return entity.entity_name, profile.category if profile else None
    if entity.entity_type == EntityType.COURSE_CATEGORY:
        return None, entity.entity_name
    return None, None


def _is_course_interest_statement(message: str) -> bool:
    """识别孩子对当前课程的明确正向兴趣，不把家长咨询误当成孩子偏好。"""

    return (
        any(marker in message for marker in _CHILD_SUBJECT_MARKERS)
        and any(marker in message for marker in _POSITIVE_INTEREST_MARKERS)
        and not any(marker in message for marker in _NEGATIVE_INTEREST_MARKERS)
    )


def _is_compact_consultation_reply(
    message: str,
    *,
    age: int | None,
    foundation: str | None,
    time_preference: str | None,
    course_interest: bool,
) -> bool:
    """限制确定性短路范围，避免把请假、退费等业务问题误判为课程推荐。"""

    normalized = message.strip()
    if (
        not normalized
        or len(normalized) > 48
        or (age is None and foundation is None and time_preference is None and not course_interest)
    ):
        return False
    return not any(term in normalized for term in _NON_CONSULTATION_TERMS)


def _age_phrase(age: int) -> str:
    return f"{age}岁"


def _programming_answer(age: int | None, foundation: str | None, course_name: str | None) -> str:
    """生成编程方向的确定性初筛回答，不承诺实时可报名状态。"""

    if course_name == "少儿编程基础班":
        profile = _PROFILE_BY_NAME[course_name]
        if age is not None and not profile.min_age <= age <= profile.max_age:
            return f"{_age_phrase(age)}不在少儿编程基础班的建议年龄范围（8至12岁）内。可以继续告诉我孩子的学习经历，我再帮您筛选其他班型。"
        if age is None:
            return "少儿编程基础班适合零基础，从图形化编程开始。孩子目前多大了？我再帮您核对适龄范围。"
        return f"{_age_phrase(age)}符合少儿编程基础班的初步条件。这个班适合零基础，从图形化编程开始；最终班型仍以教师评估为准。"

    if course_name == "编程项目实践班":
        profile = _PROFILE_BY_NAME[course_name]
        if age is not None and not profile.min_age <= age <= profile.max_age:
            return f"{_age_phrase(age)}不在编程项目实践班的建议年龄范围（10至14岁）内，建议先了解少儿编程基础班或由教师评估。"
        if age is None:
            foundation_text = (
                "已经有图形化编程或项目基础"
                if foundation in {"graphical", "project"}
                else "目前是零基础"
            )
            return f"已了解孩子{foundation_text}。孩子目前多大了？我再帮您核对编程项目实践班的适龄范围。"
        if foundation == "none":
            return f"{_age_phrase(age) if age is not None else '孩子'}年龄上可以考虑编程项目实践班，但目前是零基础，建议先从少儿编程基础班开始，再根据学习情况进入项目实践班。"
        if foundation in {"graphical", "project"}:
            return f"{_age_phrase(age) if age is not None else '孩子'}年龄合适，并且已有图形化编程或项目基础，可以优先申请编程项目实践班的教师评估。"
        return f"{_age_phrase(age) if age is not None else '孩子'}符合编程项目实践班10至14岁的建议年龄。这个班建议已完成图形化编程基础学习或通过教师评估。孩子以前学过Scratch等图形化编程吗？"

    # 编程大类需要同时比较两个班型，不能仅凭年龄直接替家长做最终决定。
    if age is None:
        foundation_text = (
            "已经有图形化编程或项目基础"
            if foundation in {"graphical", "project"}
            else "目前是零基础"
        )
        return f"已了解孩子{foundation_text}。孩子目前多大了？我再根据年龄和基础一起推荐班型。"
    if age is not None and not 8 <= age <= 14:
        return f"目前少儿编程课程的建议年龄主要为8至14岁，{_age_phrase(age)}暂不在现有班型范围内，建议由老师进一步评估。"
    if foundation == "none":
        return f"{_age_phrase(age) if age is not None else '孩子'}目前是零基础，建议先从少儿编程基础班开始，使用图形化编程建立顺序、循环和条件等基础。"
    if foundation in {"graphical", "project"}:
        return f"{_age_phrase(age) if age is not None else '孩子'}已有图形化编程或项目基础，可以重点了解编程项目实践班，并通过教师评估确认衔接程度。"
    return (
        f"{_age_phrase(age) if age is not None else '孩子'}处在少儿编程基础班（8至12岁）和编程项目实践班（10至14岁）的适龄范围内。"
        "如果还没有系统学过图形化编程，建议先从基础班开始；如果已完成图形化编程基础或通过教师评估，可以考虑项目实践班。"
        "孩子以前学过Scratch等图形化编程吗？"
    )


def _general_course_answer(age: int, category: str, course_name: str | None) -> str:
    """按稳定年龄目录筛选非编程课程，并保留教师评估边界。"""

    if course_name is not None:
        profile = _PROFILE_BY_NAME.get(course_name)
        if profile is None:
            return f"已记录孩子{age}岁。为了准确推荐，请继续说明想了解的具体班型。"
        if profile.min_age <= age <= profile.max_age:
            return f"{age}岁在{course_name}的建议年龄范围（{profile.min_age}至{profile.max_age}岁）内，{profile.prerequisite}；最终以教师评估和实际班级安排为准。"
        return f"{age}岁不在{course_name}的建议年龄范围（{profile.min_age}至{profile.max_age}岁）内。可以继续了解同方向的其他班型。"

    candidates = [
        profile.name
        for profile in COURSE_PROFILES
        if profile.category == category and profile.min_age <= age <= profile.max_age
    ]
    if not candidates:
        return f"{age}岁暂不在现有{category}班型的建议年龄范围内，建议由老师进一步评估。"
    return f"按年龄初步筛选，{age}岁可以了解{'、'.join(candidates)}。最终还需要结合孩子的基础和兴趣确认班型。"


def _infer_unique_recommended_course(
    *,
    age: int | None,
    foundation: str | None,
    category: str,
    course_name: str | None,
) -> str | None:
    """在确定性目录足以唯一筛选时返回具体班型。

    这里只根据用户明确提供并已归一化的年龄、编程基础做窄范围推断，绝不
    使用模型猜测，也不涉及实时名额或教师评估结果。多个课程同时适龄时返回
    None，继续保留课程大类，避免系统替家长武断选择。
    """

    if course_name is not None:
        return course_name
    if age is None:
        return None

    candidates = [
        profile
        for profile in COURSE_PROFILES
        if profile.category == category and profile.min_age <= age <= profile.max_age
    ]
    if category != "编程":
        return candidates[0].name if len(candidates) == 1 else None

    # 编程在 10 至 12 岁存在两个重叠班型，必须结合用户明确提供的基础。
    # 零基础只在基础班本身适龄时收敛；已有图形化/项目基础只在项目班适龄
    # 时收敛。否则仍保留“编程”大类并交由教师评估，不制造越龄推荐。
    candidate_names = {profile.name for profile in candidates}
    if foundation == "none" and "少儿编程基础班" in candidate_names:
        return "少儿编程基础班"
    if (
        foundation in {"graphical", "project"}
        and "编程项目实践班" in candidate_names
    ):
        return "编程项目实践班"
    return candidates[0].name if len(candidates) == 1 else None


def _course_interest_answer(
    *,
    age: int | None,
    foundation: str | None,
    category: str,
    course_name: str | None,
) -> str:
    """确认孩子课程兴趣，并复用已知年龄与基础继续给出建议。"""

    if category == "编程":
        recommendation = _programming_answer(age, foundation, course_name)
    elif age is not None:
        recommendation = _general_course_answer(age, category, course_name)
    else:
        recommendation = f"可以继续了解{course_name or category}方向。孩子目前多大了？我再帮您核对适龄班型。"
    return f"了解到孩子喜欢{course_name or category}。{recommendation}"


def _time_preference_answer(
    *,
    time_preference: str,
    age: int | None,
    foundation: str | None,
    category: str,
    course_name: str | None,
) -> str:
    """确认当前时段偏好，但不把静态咨询回答成实时排课结果。"""

    if course_name == "编程项目实践班":
        context_text = (
            f"结合前面确认的编程项目实践班和孩子{age}岁的情况，这个班适合10至14岁，"
            "建议已完成图形化编程基础学习或通过教师评估。"
            if age is not None
            else "结合前面确认的编程项目实践班，这个班适合10至14岁，建议已完成图形化编程基础学习或通过教师评估。"
        )
    elif course_name == "少儿编程基础班":
        context_text = (
            f"结合前面确认的少儿编程基础班和孩子{age}岁的情况，这个班适合8至12岁，适合零基础，从图形化编程开始。"
            if age is not None
            else "结合前面确认的少儿编程基础班，这个班适合8至12岁，适合零基础，从图形化编程开始。"
        )
    elif category == "编程" and age is not None:
        if foundation == "none":
            suggestion = "孩子目前是零基础，可以优先关注少儿编程基础班"
        elif foundation in {"graphical", "project"}:
            suggestion = "孩子已有编程基础，可以重点了解编程项目实践班并申请教师评估"
        else:
            suggestion = (
                "可以同时了解少儿编程基础班和编程项目实践班，再根据是否学过"
                "Scratch等图形化编程确定衔接班型"
            )
        context_text = f"结合前面咨询的编程方向和孩子{age}岁的情况，{suggestion}。"
    elif age is not None:
        context_text = _general_course_answer(age, category, course_name)
    else:
        context_text = f"前面您咨询的是{course_name or category}方向；再告诉我孩子年龄，我可以继续帮您筛选班型。"

    return (
        f"好的，了解到您{time_preference}方便上课。{context_text}"
        f"具体{time_preference}是否有合适班次和实时名额，需要由课程顾问结合校区当前安排确认。"
    )


def resolve_course_attribute_follow_up(
    message: str,
    *,
    active_entity: EntityReference | None,
    previous_age: int | None = None,
    previous_programming_foundation: str | None = None,
) -> ConsultationFollowUp | None:
    """直接回答已确认课程的静态属性，避免每次都绕行通用 FAQ。

    课程年龄范围和基础要求来自受控课程目录，不包含价格、实时排课、名额
    或教师安排。后四类信息仍必须走原有实时/知识库边界，不能因为短期记忆
    中出现过课程名称就伪造动态结果。
    """

    course_name, _ = _entity_course_scope(active_entity)
    if course_name is None or len(message.strip()) > 48:
        return None
    attributes = set(extract_requested_attributes(message))
    supported_attributes = {"age_range", "prerequisite", "equipment"}
    if not attributes.intersection(supported_attributes):
        return None
    # 复合问题需要保留完整问题交给 FAQ/LLM 统一组织答案。这里只处理一个
    # 静态属性，避免“适合多大？需要什么基础？”被截成只回答其中一半。
    if len(attributes.intersection(supported_attributes)) != 1:
        return None
    if not has_course_reference(message) and not attributes:
        return None

    profile = _PROFILE_BY_NAME.get(course_name)
    if profile is None:
        return None
    if "equipment" in attributes:
        answer = course_equipment_answer(course_name)
        if answer is None:
            return None
    elif "prerequisite" in attributes:
        # 课程目录中的 prerequisite 已经带有“建议/无需”等语气，直接拼接
        # 课程名可以避免出现“建议建议”这类重复文案。
        answer = f"{course_name}{profile.prerequisite}。"
    elif "age_range" in attributes:
        answer = f"{course_name}适合{profile.min_age}至{profile.max_age}岁。"
    else:
        return None
    rewritten_query, _ = rewrite_query(message, active_entity)
    return ConsultationFollowUp(
        child_age=previous_age,
        programming_foundation=previous_programming_foundation,
        class_time_preference=None,
        # 复用统一的指代改写，保证“这个课程/那个班”不会残留在检索问题中，
        # 也避免为静态属性短路引入第二套文本替换规则。
        rewritten_query=rewritten_query,
        answer=answer,
    )


def resolve_trial_consultation_follow_up(
    message: str,
    *,
    active_entity: EntityReference | None,
    previous_age: int | None = None,
    previous_class_time_preference: str | None = None,
) -> ConsultationFollowUp | None:
    """为明确试听/报名动作生成自然的主回答，并与线索卡解耦。

    主回答只承接家长的业务诉求、说明后续确认边界；联系方式提取、明确
    授权和销售顾问队列仍由报课意向旁路及线索服务负责，避免模型自行索取
    或保存联系方式，也不把“有意向”说成“已经预约成功”。
    """

    normalized = message.strip()
    has_trial = any(keyword in normalized for keyword in ("试听", "体验课", "体验"))
    has_enrollment = any(keyword in normalized for keyword in ("报名", "报课", "缴费"))
    if not has_trial and not has_enrollment:
        return None
    # 询问“怎么试听/试听流程/怎么预约”仍属于 FAQ，不应直接进入销售
    # 承接。只有明确表达“我要参加、请帮我安排、这周去试听”等动作时，
    # 才生成承接回答；这样主回答与旁路线索的升级条件保持一致。
    trial_process_question = is_trial_process_question(normalized)
    explicit_trial_action = has_explicit_trial_action(normalized)
    explicit_enrollment_action = has_explicit_enrollment_action(normalized)
    if has_trial and not has_enrollment and (trial_process_question or not explicit_trial_action):
        return None
    if has_enrollment and not explicit_enrollment_action and not explicit_trial_action:
        return None
    course_name, category = _entity_course_scope(active_entity)
    if category is None:
        return None
    target = course_name or f"{category}课程"
    if explicit_trial_action and explicit_enrollment_action:
        action: Literal["trial", "enrollment", "trial_and_enrollment"] = "trial_and_enrollment"
    elif explicit_enrollment_action:
        action = "enrollment"
    else:
        action = "trial"

    current_time_preference = extract_class_time_preference(normalized)
    time_preference = current_time_preference or previous_class_time_preference
    context_clauses: list[str] = []
    if previous_age is not None:
        context_clauses.append(f"孩子{previous_age}岁")
    if time_preference is not None:
        context_clauses.append(f"可安排时间为{time_preference}")
    if any(word in normalized for word in ("这周", "本周")):
        context_clauses.append("希望本周安排")
    elif "尽快" in normalized:
        context_clauses.append("希望尽快安排")
    request_scope = "、".join(context_clauses)
    context_text = "" if not request_scope else f"已记录：{request_scope}。"

    # 主回答用自然语言复述本轮已经掌握的关键信息，不再重复课程介绍或让
    # 家长重新提供年龄、时段。它也不能使用“预约成功”等容易让家长误以为
    # 已经锁定名额的表述；联系方式授权仍由旁路线索卡单独负责。
    if action == "trial":
        answer = (
            f"可以，我先为您整理参加{target}试听的需求。{context_text}"
            "具体试听时间、校区和名额需要由销售顾问老师结合当前排课确认，"
            "确认后再与您沟通具体安排。"
        )
        query_action = "试听"
    elif action == "enrollment":
        answer = (
            f"可以，我先为您整理报名{target}的需求。{context_text}"
            "报名条件、班级安排和可选时间需要由销售顾问老师结合当前排课和教师评估确认，"
            "确认后再与您沟通具体办理安排。"
        )
        query_action = "报名"
    else:
        answer = (
            f"可以，我先为您整理{target}的试听和报名需求。{context_text}"
            "通常需要先确认孩子情况并完成试听或教师评估，具体时间、校区和后续安排"
            "由销售顾问老师结合当前排课确认。"
        )
        query_action = "试听和报名"
    return ConsultationFollowUp(
        child_age=previous_age,
        programming_foundation=None,
        class_time_preference=time_preference,
        rewritten_query=f"{target}；{query_action}意向；请由销售顾问老师确认后续安排",
        answer=answer,
        action=action,
    )


def resolve_course_consultation_follow_up(
    message: str,
    *,
    active_entity: EntityReference | None,
    previous_age: int | None = None,
    previous_programming_foundation: str | None = None,
) -> ConsultationFollowUp | None:
    """识别“12岁”“没学过”等上下文回答并给出受控推荐。

    只有存在明确课程上下文且当前消息是短槽位回答时才命中。普通寒暄、
    服务规则、学情、实时名额等请求继续进入原有 Supervisor 和工作流。
    """

    course_name, category = _entity_course_scope(active_entity)
    if category is None:
        return None
    age = extract_child_age(message)
    foundation = extract_programming_foundation(message) if category == "编程" else None
    time_preference = extract_class_time_preference(message)
    course_interest = _is_course_interest_statement(message)
    if not _is_compact_consultation_reply(
        message,
        age=age,
        foundation=foundation,
        time_preference=time_preference,
        course_interest=course_interest,
    ):
        return None

    resolved_age = age if age is not None else previous_age
    resolved_foundation = (
        foundation if foundation is not None else previous_programming_foundation
    )
    if time_preference is not None:
        answer = _time_preference_answer(
            time_preference=time_preference,
            age=resolved_age,
            foundation=resolved_foundation,
            category=category,
            course_name=course_name,
        )
        rewritten = f"{course_name or category}；"
        if resolved_age is not None:
            rewritten += f"孩子年龄：{resolved_age}岁；"
        rewritten += f"上课时间偏好：{time_preference}；请结合已知信息推荐班型"
    elif course_interest:
        answer = _course_interest_answer(
            age=resolved_age,
            foundation=resolved_foundation,
            category=category,
            course_name=course_name,
        )
        rewritten = f"{course_name or category}；孩子明确感兴趣"
        if resolved_age is not None:
            rewritten += f"；孩子年龄：{resolved_age}岁"
        rewritten += "；请推荐合适班型"
    elif category == "编程":
        answer = _programming_answer(resolved_age, resolved_foundation, course_name)
        facts = [f"孩子年龄：{resolved_age}岁" if resolved_age is not None else "孩子年龄：未提供"]
        if resolved_foundation == "none":
            facts.append("编程基础：零基础")
        elif resolved_foundation == "graphical":
            facts.append("编程基础：学过图形化编程")
        elif resolved_foundation == "project":
            facts.append("编程基础：有项目经验")
        rewritten = f"{course_name or category}；{'；'.join(facts)}；请推荐合适班型"
    else:
        # 非编程方向目前只收集年龄，不把“没学过”泛化为不可靠的跨课程基础。
        if resolved_age is None:
            return None
        answer = _general_course_answer(resolved_age, category, course_name)
        rewritten = f"{course_name or category}；孩子年龄：{resolved_age}岁；请推荐合适班型"

    return ConsultationFollowUp(
        child_age=resolved_age,
        programming_foundation=resolved_foundation,
        class_time_preference=time_preference,
        rewritten_query=rewritten,
        answer=answer,
        recommended_course_name=_infer_unique_recommended_course(
            age=resolved_age,
            foundation=resolved_foundation,
            category=category,
            course_name=course_name,
        ),
    )
