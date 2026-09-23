"""短期会话状态与结构化路由规划。

本模块只操作会话存储协议中的轻量状态，不保存知识正文或动态学情数据。
当前本地和部署模板由工厂选择 Redis，以支持多进程共享、重启恢复和集中
过期治理；自动化测试仍可显式注入进程内实现。

这里的会话状态是“对话理解状态”，不是业务事实缓存。课程名称可以帮助
下一轮追问完成指代消解，但剩余课时、班级名额、退费金额等事实仍必须每次
从授权的业务系统读取，不能因为曾经出现在会话里就被视为可信结果。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date, timedelta
import re
from typing import Callable

from backend.app.conversation_understanding import (
    EntityReference,
    EntityType,
    IntentResult,
    IntentType,
    CLASS_ALIASES,
    extract_requested_attributes,
    resolve_turn,
)
from backend.app.agents.supervisor import (
    RecognitionSource,
    StructuredIntentModel,
    recognize_intent_detailed,
)
from backend.app.memory.conversation import (
    ConversationMemory,
    ConversationStore,
    ConversationSubject,
    InMemoryConversationStore,
)
from backend.app.memory.structured.admission import is_explicit_memory_request
from backend.app.dialogue import TurnDecision, arbitrate_turn
from backend.app.dialogue.slots import collect_slot_values
from backend.app.services.course_consultation import (
    resolve_course_attribute_follow_up,
    resolve_course_consultation_follow_up,
    resolve_trial_consultation_follow_up,
)


@dataclass(frozen=True, slots=True)
class ConversationPlan:
    """一次请求进入 LangGraph 前的受控理解结果。

    该对象把“理解”和“执行”隔离开：路由层只提供受控计划，后续节点仍要
    自己完成权限校验和参数校验，不能把计划中的实体名称直接当作数据库主键。
    """

    conversation_id: str | None
    intent_result: IntentResult
    active_entity: EntityReference | None
    rewritten_query: str
    recognition_source: RecognitionSource
    # route 最终由 route_for_intent 的白名单映射产生，不接受模型任意字符串。
    route: str
    # 只保存受控失败原因枚举，不保存模型原文、Prompt 或供应商异常正文。
    # 该字段用于区分“未配置模型”和“模型调用后安全回退”，不会参与路由。
    recognition_fallback_reason: str | None = None
    # 班级统计参数在这里完成一次结构化落地；后续 LangGraph 节点不再从
    # 用户原文猜日期或班级，避免模型/文本直接影响数据库查询范围。
    class_id: str | None = None
    class_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    low_balance_threshold: int = 5
    # 已由确定性课程目录完成回答时直接返回，避免将“12岁”等孤立数字
    # 送入全库检索并召回无关课程。
    direct_answer: str | None = None
    child_age: int | None = None
    programming_foundation: str | None = None
    class_time_preference: str | None = None
    pending_intent: IntentType | None = None
    # 新决策契约作为 LangGraph 和旁路线索的共同依据；保留旧字段是为了让
    # 既有 API、测试和节点可以渐进迁移，而不是一次性重写整个会话链路。
    decision: TurnDecision | None = None


class StatisticsPeriodError(ValueError):
    """统计周期存在但无法解析为合法日期时抛出的受控异常。"""


CLASS_DISPLAY_NAMES = {
    class_id: aliases[0]
    for class_id, aliases in CLASS_ALIASES.items()
}


def _month_range(year: int, month: int) -> tuple[date, date]:
    """返回指定月份的首日和末日，并统一拦截非法月份。"""

    if not 1 <= month <= 12:
        raise StatisticsPeriodError("月份必须在 1 至 12 之间")
    try:
        first = date(year, month, 1)
    except ValueError as exc:
        raise StatisticsPeriodError("统计月份不是合法日期") from exc
    return first, date(year, month, calendar.monthrange(year, month)[1])


def _parse_full_dates(text: str) -> list[date]:
    """提取完整日期，支持中文日期、短横线和斜线格式。"""

    pattern = re.compile(
        r"(?<!\d)(\d{4})\s*(?:年|[-/])\s*(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})\s*日?"
    )
    result: list[date] = []
    for match in pattern.finditer(text):
        try:
            result.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError as exc:
            raise StatisticsPeriodError("统计日期不是合法日期") from exc
    return result


def parse_statistics_period(
    message: str,
    *,
    reference_date: date | None = None,
) -> tuple[date, date] | None:
    """把用户给出的统计周期转换成闭区间日期。

    支持当前业务中的自然语言范围：月份、明确起止日期、
    本月/上个月、最近 7 天和最近 30 天。函数只负责解析，不访问数据库。
    这样做可以在真正查询前拦截反向日期、非法日期和不支持的表达。

    reference_date 只用于测试和回放；生产调用默认使用服务端日期，不能
    使用模型生成的“当前日期”，否则同一请求可能因模型输出而产生不同结果。
    """

    text = message.strip()
    if not text:
        return None
    today = reference_date or date.today()

    if "本月" in text or "这个月" in text:
        return today.replace(day=1), today
    if "上个月" in text or "上月" in text:
        previous = today.replace(day=1) - timedelta(days=1)
        return _month_range(previous.year, previous.month)
    if "最近7天" in text or "近7天" in text:
        return today - timedelta(days=6), today
    if "最近30天" in text or "近30天" in text:
        return today - timedelta(days=29), today

    full_dates = _parse_full_dates(text)
    if len(full_dates) >= 2:
        start, end = full_dates[0], full_dates[1]
        if start > end:
            raise StatisticsPeriodError("统计开始日期不能晚于结束日期")
        return start, end
    if len(full_dates) == 1:
        return full_dates[0], full_dates[0]

    # 只有月份、没有日时按整月统计。完整日期优先，所以不会把
    # “2026-08-01”误识别成 2026 年 8 月。
    month_match = re.search(r"(?<!\d)(\d{4})\s*(?:年\s*(\d{1,2})\s*月|[-/](\d{1,2}))(?![-/]\d)", text)
    if month_match:
        month = int(month_match.group(2) or month_match.group(3))
        return _month_range(int(month_match.group(1)), month)

    # 只要看起来像用户在写日期，就不要静默当成“未提供周期”。
    # 这会让非法月份/日期进入澄清，而不是错误调用业务工具。
    if re.search(r"\d{4}\s*(?:年|[-/])", text):
        raise StatisticsPeriodError("无法识别统计周期，请使用 YYYY-MM-DD 或 YYYY年M月")
    return None


def parse_low_balance_threshold(message: str, *, default: int = 5) -> int:
    """解析可选的低课时阈值；未说明时使用后端固定默认值。"""

    match = re.search(r"(?:低课时(?:阈值|提醒)?|剩余课时(?:不超过|少于等于))\s*(?:为|是|设为)?\s*(\d+)", message)
    if not match:
        return default
    threshold = int(match.group(1))
    if not 0 <= threshold <= 10000:
        raise ValueError("低课时阈值必须在 0 至 10000 之间")
    return threshold


def route_for_intent(result: IntentResult) -> str:
    """把业务意图白名单映射为当前真正可执行的工作流路由。

    当前只有学情查询具备实时数据库工具。其他需要实时数据的请求不能
    降级成静态 FAQ，而是进入人工兜底，防止模型编造名额或退款金额。
    """

    # 澄清优先级最高。即使模型识别出了某个意图，只要关键实体或周期不完整，
    # 就不能继续调用工具，否则会产生“查错人、查错班、查错周期”的业务事故。
    if result.clarification_needed:
        return "clarification"
    if result.intent == IntentType.LEARNING_REPORT:
        return "learning_report"
    if result.intent == IntentType.REPORT_HISTORY:
        return "report_history"
    if result.intent == IntentType.CLASS_LEARNING_SUMMARY:
        # 班级统计和个人学情是两条不同的数据权限链路，必须使用独立路由。
        return "class_learning_summary"
    if result.intent == IntentType.LEARNING_SUMMARY:
        return "learning_summary"
    if result.intent in {IntentType.COMPLAINT, IntentType.HUMAN_HANDOFF}:
        return "human_handoff"
    if result.needs_live_data:
        # 没有对应的实时工具时只能人工兜底，不能让静态 FAQ “看起来像是”
        # 查到了实时数据。这个分支是防止模型幻觉的重要最后一道路由门禁。
        return "human_handoff"
    if result.intent in {
        IntentType.SERVICE_RULES,
        IntentType.FEE_REFUND,
        IntentType.SAFETY_HEALTH,
        IntentType.CLASS_TRANSFER,
    }:
        return "service_rules"
    return "faq"


def _finalize_plan(
    message: str,
    plan: ConversationPlan,
    *,
    current_pending: IntentType | None,
) -> ConversationPlan:
    """把兼容规划结果收敛为一次不可变、可审计的对话决策。

    旧规划器继续负责实体解析、自然语言周期和确定性课程回答；本函数统一
    完成主/旁路意图、UNKNOWN 类型、待补流程和最终白名单路由的仲裁。
    """

    slots = collect_slot_values(
        message,
        active_entity=plan.active_entity,
        child_age=plan.child_age,
        programming_foundation=plan.programming_foundation,
        class_time_preference=plan.class_time_preference,
        class_id=plan.class_id,
        period_start=plan.period_start,
        period_end=plan.period_end,
    )
    proposed_pending = (
        plan.intent_result.intent
        if plan.intent_result.clarification_needed
        and plan.intent_result.intent
        in {IntentType.LEARNING_REPORT, IntentType.CLASS_LEARNING_SUMMARY}
        else None
    )
    # 显式长期记忆命令是当前轮的一次旁支操作，不应清空此前未完成的报告
    # 参数收集；其他课程或服务问题则交给仲裁器按话题切换规则处理。
    if plan.route == "memory":
        proposed_pending = current_pending
    decision = arbitrate_turn(
        message,
        result=plan.intent_result,
        recognition_source=plan.recognition_source,
        active_entity=plan.active_entity,
        slot_values=slots,
        current_pending=current_pending,
        proposed_pending=proposed_pending,
        proposed_route=plan.route,
    )
    return replace(
        plan,
        intent_result=decision.normalized_result,
        route=decision.route,
        pending_intent=(
            decision.pending_flow.flow_type if decision.pending_flow is not None else None
        ),
        decision=decision,
    )


def plan_conversation(
    message: str,
    *,
    conversation_id: str | None,
    store: ConversationStore,
    subject: ConversationSubject | None = None,
    model: StructuredIntentModel | None = None,
) -> ConversationPlan:
    """结合历史实体生成意图、独立检索问题和安全路由。

    rewritten_query 面向检索，route 面向工作流，active_entity 面向下一轮
    对话；三者职责不同，不能用一个“大而全”的字符串替代结构化状态。
    """

    def build(memory: ConversationMemory) -> ConversationPlan:
        def finalized(plan: ConversationPlan) -> ConversationPlan:
            return _finalize_plan(
                message,
                plan,
                current_pending=memory.pending_intent,
            )

        active_entity = memory.active_entity
        turn = resolve_turn(message, active_entity)
        # 明确的长期记忆命令必须先于 FAQ/课程追问判断。否则“请记住孩子喜欢
        # 编程”会因为包含课程实体而进入咨询链路，RAGFlow 可能返回旧的“无法
        # 记住用户信息”话术。是否真正保存由聊天记忆服务继续执行准入和事务。
        if is_explicit_memory_request(message):
            result = IntentResult(
                intent=IntentType.UNKNOWN,
                confidence=1.0,
                mentioned_entity=turn.mentioned_entity,
            )
            return finalized(ConversationPlan(
                conversation_id=conversation_id,
                intent_result=result,
                active_entity=turn.active_entity,
                rewritten_query=turn.rewritten_query,
                recognition_source=RecognitionSource.DETERMINISTIC_GUARD,
                route="memory",
                # “请记住”只是一次长期记忆写入命令，不能顺带清空当前会话
                # 已确认的年龄和编程基础，否则下一轮会错误地重复追问。
                child_age=memory.child_age,
                programming_foundation=memory.programming_foundation,
                class_time_preference=memory.class_time_preference,
                pending_intent=memory.pending_intent,
            ))
        # 明确试听/报名是当前对话的业务动作。先给出自然的承接话术，
        # 线索卡仍由聊天编排中的报课意向旁路负责，不在这里处理联系方式。
        substantive_attributes = set(turn.requested_attributes) - {"trial_policy"}
        trial_consultation = (
            resolve_trial_consultation_follow_up(
                message,
                active_entity=turn.active_entity,
                previous_age=memory.child_age,
                previous_class_time_preference=memory.class_time_preference,
            )
            if not substantive_attributes
            else None
        )
        if trial_consultation is not None:
            contextual_entity = turn.active_entity
            result = IntentResult(
                intent={
                    "trial": IntentType.TRIAL_BOOKING,
                    "enrollment": IntentType.ENROLLMENT,
                    "trial_and_enrollment": IntentType.TRIAL_BOOKING,
                }[trial_consultation.action],
                confidence=1.0,
                mentioned_entity=(
                    contextual_entity.model_copy(update={"is_explicit": False})
                    if contextual_entity is not None
                    else None
                ),
            )
            return finalized(ConversationPlan(
                conversation_id=conversation_id,
                intent_result=result,
                active_entity=contextual_entity,
                rewritten_query=trial_consultation.rewritten_query,
                recognition_source=RecognitionSource.DETERMINISTIC_GUARD,
                route="faq",
                direct_answer=trial_consultation.answer,
                child_age=trial_consultation.child_age,
                programming_foundation=memory.programming_foundation,
                class_time_preference=trial_consultation.class_time_preference,
                pending_intent=memory.pending_intent,
            ))
        # 槽位补全只处理省略课程名的短回答。只要本轮明确出现课程实体，就应
        # 先按普通咨询/纠错处理，不能把“不是基础班，是项目实践班”中的课程名
        # 误判成“有项目经验”。
        same_programming_context = (
            active_entity is not None
            and active_entity.entity_name in {"编程", "少儿编程基础班", "编程项目实践班"}
            and turn.mentioned_entity is not None
            and turn.mentioned_entity.entity_type == EntityType.COURSE_CATEGORY
            and turn.mentioned_entity.entity_name == "编程"
            and not turn.mentioned_entity.is_correction
        )
        consultation = (
            resolve_course_consultation_follow_up(
                message,
                active_entity=active_entity,
                previous_age=memory.child_age,
                previous_programming_foundation=memory.programming_foundation,
            )
            if turn.mentioned_entity is None or same_programming_context
            else None
        )
        if consultation is not None:
            contextual_entity = turn.mentioned_entity or active_entity
            if consultation.recommended_course_name is not None:
                # 课程大类在确定性目录中已经唯一收敛后，应把具体班型写回
                # 会话状态。它不是用户逐字点名，因此 is_explicit 保持 False；
                # 但来源是受控年龄/基础规则，可用高置信度支持后续指代消解。
                contextual_entity = EntityReference(
                    entity_type=EntityType.COURSE,
                    entity_name=consultation.recommended_course_name,
                    raw_mention=None,
                    is_explicit=False,
                    is_correction=False,
                    confidence=1.0,
                )
            result = IntentResult(
                intent=IntentType.COURSE_RECOMMENDATION,
                confidence=1.0,
                mentioned_entity=(
                    contextual_entity.model_copy(update={"is_explicit": False})
                    if contextual_entity is not None
                    else None
                ),
                requested_attributes=["age_range", "prerequisite"],
            )
            return finalized(ConversationPlan(
                conversation_id=conversation_id,
                intent_result=result,
                active_entity=contextual_entity,
                rewritten_query=consultation.rewritten_query,
                recognition_source=RecognitionSource.DETERMINISTIC_GUARD,
                route="faq",
                direct_answer=consultation.answer,
                child_age=consultation.child_age,
                programming_foundation=consultation.programming_foundation,
                class_time_preference=consultation.class_time_preference,
                # 时间偏好属于已通过确定性解析的短期槽位；后续回复可复用它，
                # 但动态排课和名额仍必须实时查询，不能从会话状态推断。
                pending_intent=memory.pending_intent,
            ))
        # “那个班需要什么基础”等问题属于稳定课程目录属性，直接回答可以
        # 消除无必要的 FAQ/RAG 延迟，同时保留实时信息不得猜测的边界。课程槽位
        # 补全必须先于这里判断，否则用户单独回复“零基础”时会被误当成是在
        # 询问课程的基础要求，而不是在提供孩子的学习经历。
        attribute_consultation = resolve_course_attribute_follow_up(
            message,
            active_entity=turn.active_entity,
            previous_age=memory.child_age,
            previous_programming_foundation=memory.programming_foundation,
        )
        if attribute_consultation is not None:
            contextual_entity = turn.active_entity
            result = IntentResult(
                intent=IntentType.COURSE_DETAIL,
                confidence=1.0,
                mentioned_entity=(
                    contextual_entity.model_copy(update={"is_explicit": False})
                    if contextual_entity is not None
                    else None
                ),
                requested_attributes=extract_requested_attributes(message),
            )
            return finalized(ConversationPlan(
                conversation_id=conversation_id,
                intent_result=result,
                active_entity=contextual_entity,
                rewritten_query=attribute_consultation.rewritten_query,
                recognition_source=RecognitionSource.DETERMINISTIC_GUARD,
                route="faq",
                direct_answer=attribute_consultation.answer,
                child_age=attribute_consultation.child_age,
                programming_foundation=attribute_consultation.programming_foundation,
                class_time_preference=memory.class_time_preference,
                pending_intent=memory.pending_intent,
            ))
        outcome = recognize_intent_detailed(
            message, active_entity=active_entity, model=model
        )
        result = outcome.result
        next_entity = result.mentioned_entity or active_entity
        pending_intent = memory.pending_intent

        # 上一轮已经确定是报告或班级统计，只是缺周期时，本轮自然语言周期应
        # 作为参数补全，而不是被重新分类成普通 FAQ。这里仅恢复受控意图，
        # 后续仍会执行身份、资源归属和日期范围校验。
        if pending_intent == IntentType.LEARNING_REPORT:
            try:
                period_supplied = parse_statistics_period(message) is not None
            except StatisticsPeriodError:
                period_supplied = False
            if period_supplied:
                result = IntentResult(
                    intent=IntentType.LEARNING_REPORT,
                    confidence=1.0,
                    mentioned_entity=next_entity,
                    needs_live_data=True,
                )
                outcome = outcome.__class__(result, RecognitionSource.DETERMINISTIC_GUARD)
                turn = turn.model_copy(
                    update={"rewritten_query": f"生成学情报告，周期为{message.strip()}"}
                )
                pending_intent = None
        elif pending_intent == IntentType.CLASS_LEARNING_SUMMARY:
            try:
                period_supplied = parse_statistics_period(message) is not None
            except StatisticsPeriodError:
                period_supplied = False
            if period_supplied and next_entity is not None and next_entity.entity_type == EntityType.CLASS:
                result = IntentResult(
                    intent=IntentType.CLASS_LEARNING_SUMMARY,
                    confidence=1.0,
                    mentioned_entity=next_entity.model_copy(update={"is_explicit": False}),
                    needs_live_data=True,
                )
                outcome = outcome.__class__(result, RecognitionSource.DETERMINISTIC_GUARD)
                turn = turn.model_copy(
                    update={"rewritten_query": f"{CLASS_DISPLAY_NAMES.get(next_entity.entity_name or '', next_entity.entity_name)}班级学情，周期为{message.strip()}"}
                )
                pending_intent = None
        class_id: str | None = None
        class_name: str | None = None
        period_start: date | None = None
        period_end: date | None = None
        low_balance_threshold = 5

        # 只有已经被 Supervisor 识别为班级统计时才解析统计参数；普通 FAQ
        # 不应因为正文里出现一个年份或数字而被误判为数据库查询。
        if result.intent in {
            IntentType.CLASS_LEARNING_SUMMARY,
            IntentType.LEARNING_REPORT,
        }:
            if next_entity is not None and next_entity.entity_type == EntityType.CLASS:
                class_id = next_entity.entity_name
                class_name = CLASS_DISPLAY_NAMES.get(class_id or "")
            try:
                period = parse_statistics_period(message)
                if period is not None:
                    period_start, period_end = period
                low_balance_threshold = parse_low_balance_threshold(message)
            except (StatisticsPeriodError, ValueError):
                # 非法周期/阈值只能进入澄清，不能让图节点带着不完整参数
                # 调用数据库。异常正文不向用户回显，统一使用安全提示。
                result = result.model_copy(update={"clarification_needed": True})

        if result.clarification_needed and result.intent in {
            IntentType.LEARNING_REPORT,
            IntentType.CLASS_LEARNING_SUMMARY,
        }:
            pending_intent = result.intent
        elif not result.clarification_needed:
            pending_intent = None

        return finalized(ConversationPlan(
            conversation_id=conversation_id,
            intent_result=result,
            active_entity=next_entity,
            rewritten_query=turn.rewritten_query,
            recognition_source=outcome.source,
            route=route_for_intent(result),
            recognition_fallback_reason=outcome.fallback_reason,
            class_id=class_id,
            class_name=class_name,
            period_start=period_start,
            period_end=period_end,
            low_balance_threshold=low_balance_threshold,
            child_age=memory.child_age,
            programming_foundation=memory.programming_foundation,
            class_time_preference=memory.class_time_preference,
            pending_intent=pending_intent,
        ))

    def process_and_apply(memory: ConversationMemory) -> ConversationPlan:
        """在存储层原子锁内应用本轮已验证的规划结果。"""

        plan = build(memory)
        _apply_plan_to_memory(memory, plan)
        return plan

    return store.process(conversation_id, process_and_apply, subject=subject)


def _apply_plan_to_memory(memory: ConversationMemory, plan: ConversationPlan) -> None:
    """只把规划结果中的受控槽位写回短期会话状态。

    存储模块不理解课程实体和业务意图，这些规则属于对话理解层。这里保留
    原有的污染防护：澄清中的未知实体不覆盖历史实体，切换到非编程课程时
    清理编程基础，避免下一轮推荐误用旧槽位。
    """

    previous_entity = memory.active_entity
    entity = plan.intent_result.mentioned_entity
    preserve_existing_entity = (
        plan.intent_result.intent == IntentType.COURSE_RECOMMENDATION
        and any(marker in plan.rewritten_query for marker in ("还是", "或者", "对比", "比较"))
        and sum(
            1
            for marker in ("舞蹈", "中国舞", "美术", "音乐", "编程")
            if marker in plan.rewritten_query
        ) >= 2
    )
    if (
        entity is not None
        and entity.entity_type != EntityType.UNKNOWN
        and not preserve_existing_entity
        and (
            not plan.intent_result.clarification_needed
            or (
                plan.intent_result.intent == IntentType.CLASS_LEARNING_SUMMARY
                and entity.entity_type == EntityType.CLASS
            )
        )
    ):
        memory.active_entity = entity

    memory.child_age = plan.child_age
    if (
        previous_entity is not None
        and memory.active_entity is not None
        and previous_entity.entity_name != memory.active_entity.entity_name
        and memory.active_entity.entity_name not in {"编程", "少儿编程基础班", "编程项目实践班"}
    ):
        memory.programming_foundation = None
    else:
        memory.programming_foundation = plan.programming_foundation
    # 时间偏好与年龄、编程基础一样属于当前会话的受控槽位。只有本轮确实
    # 解析出新的时间偏好时才覆盖旧值；普通追问返回 None 时必须保留之前的
    # “周末上午”等上下文，否则下一轮又会丢失家长已经提供的上课时段。
    if plan.class_time_preference is not None:
        memory.class_time_preference = plan.class_time_preference
    memory.pending_intent = plan.pending_intent
