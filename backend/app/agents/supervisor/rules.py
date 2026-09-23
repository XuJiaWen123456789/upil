"""Supervisor 的确定性安全守卫和无模型回退规则。

高风险、隐私、交易及强实时数据意图必须先于概率模型判断；模型不可用时，
同一规则集提供可解释的保守分类，保证主客服链路仍可运行。
"""

import re

from backend.app.conversation_understanding import (
    EntityReference,
    EntityType,
    IntentResult,
    IntentType,
    TurnResolution,
    resolve_turn,
)

from .constants import (
    CLASS_LEARNING_CUES,
    CLASS_LEARNING_METRIC_KEYWORDS,
    CLASS_LEARNING_PERIOD_PATTERNS,
    COMPLAINT_KEYWORDS,
    HUMAN_HANDOFF_KEYWORDS,
    LEARNING_DATA_KEYWORDS,
    LEARNING_REPORT_KEYWORDS,
    LEARNING_REPORT_PERIOD_KEYWORDS,
    REPORT_HISTORY_KEYWORDS,
    REFUND_LIVE_DATA_KEYWORDS,
    SCHEDULE_DATA_KEYWORDS,
    STATIC_SERVICE_RULES_KEYWORDS,
)


def context_entity(turn: TurnResolution) -> EntityReference | None:
    """返回本轮可安全使用的实体，并标记是否来自历史上下文。"""

    if turn.mentioned_entity is not None:
        return turn.mentioned_entity
    if turn.used_context and turn.active_entity is not None:
        return turn.active_entity.model_copy(update={"is_explicit": False})
    return None


def has_statistics_period(message: str) -> bool:
    """判断班级统计请求是否包含当前支持的自然语言或显式日期周期。"""

    if any(pattern in message for pattern in CLASS_LEARNING_PERIOD_PATTERNS):
        return True
    if re.search(r"\d{4}\s*年\s*\d{1,2}\s*月", message):
        return True
    if re.search(r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?", message):
        return True
    return bool(
        re.search(
            r"\d{4}[-/]\d{1,2}[-/]\d{1,2}.*?"
            r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
            message,
        )
    )


def is_class_learning_request(message: str, turn: TurnResolution) -> bool:
    """识别班级聚合统计信号，同时避免误伤个人出勤查询。"""

    entity = context_entity(turn)
    if not any(keyword in message for keyword in CLASS_LEARNING_METRIC_KEYWORDS):
        return False
    if entity is not None and entity.entity_type == EntityType.CLASS:
        return True
    return any(keyword in message for keyword in CLASS_LEARNING_CUES)


def is_live_schedule_request(message: str) -> bool:
    """识别当前班次、名额和可安排性的实时查询。

    家长常用“有具体班吗”“现在有名额吗”这类省略表达，并不会完整说出
    “实时排课”。这里只识别当前可用性，不把“什么时候上课”“一周几次”
    等稳定课程规则误判成实时数据，后者仍交给课程知识库回答。
    """

    normalized = re.sub(r"[\s，。！？?！、]+", "", message)
    if any(keyword in normalized for keyword in SCHEDULE_DATA_KEYWORDS):
        return True

    availability_target = r"(?:具体班|班次|名额|空位|余位)"
    availability_question = r"(?:有没有|是否有|有无|还有|还剩|有吗|剩吗)"
    current_or_time = (
        r"(?:现在|当前|目前|今天|明天|本周|这周|近期|最近|"
        r"周末|工作日|平时|上午|下午|晚上|这个时间|这个时段)"
    )
    patterns = (
        # “有具体班吗”“有没有空位”等表达不要求出现“现在”。
        rf"{availability_question}.*?{availability_target}",
        rf"(?:有|剩).*?{availability_target}(?:吗|么|嘛)?$",
        rf"{availability_target}.*?(?:有吗|还有吗|剩吗|多少|几个)",
        # 带明确当前性或时段时，“有班吗”也表示查询可报名班次。
        rf"{current_or_time}.*?(?:有班|开班|排班|{availability_target})",
        # “目前还能报名吗”查询的是当前可报名状态，而非静态报名流程。
        r"(?:现在|当前|目前|本周|这周)?(?:还)?能(?:不能)?报名(?:吗|么|嘛)?$",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def high_risk_result(
    message: str, turn: TurnResolution
) -> IntentResult | None:
    """优先处理高风险、强实时和确定性强的业务意图。"""

    attributes = turn.requested_attributes
    entity = context_entity(turn)
    if any(keyword in message for keyword in HUMAN_HANDOFF_KEYWORDS):
        return IntentResult(
            intent=IntentType.HUMAN_HANDOFF,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
        )
    if any(keyword in message for keyword in COMPLAINT_KEYWORDS):
        return IntentResult(
            intent=IntentType.COMPLAINT,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
        )
    if is_class_learning_request(message, turn):
        return IntentResult(
            intent=IntentType.CLASS_LEARNING_SUMMARY,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
            needs_live_data=True,
            clarification_needed=(
                entity is None
                or entity.entity_type != EntityType.CLASS
                or not has_statistics_period(message)
            ),
        )
    report_generation_requested = (
        any(keyword in message for keyword in LEARNING_REPORT_KEYWORDS)
        and any(
            keyword in message
            for keyword in ("学情报告", "学习报告", "月度报告")
        )
        and any(keyword in message for keyword in ("生成", "导出", "做一份"))
    )
    if report_generation_requested:
        has_period = any(
            keyword in message for keyword in LEARNING_REPORT_PERIOD_KEYWORDS
        ) or bool(
            re.search(
                r"\d{4}[-/]\d{1,2}[-/]\d{1,2}.*"
                r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
                message,
            )
        )
        return IntentResult(
            intent=IntentType.LEARNING_REPORT,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
            needs_live_data=True,
            clarification_needed=not has_period,
        )
    # “查看已有报告”不能与“生成新报告”共用意图。前者只提供受控的历史
    # 报告入口，绝不能因为一句“查看报告”创建 ReportTask 或重复生成 PDF。
    if any(keyword in message for keyword in REPORT_HISTORY_KEYWORDS):
        return IntentResult(
            intent=IntentType.REPORT_HISTORY,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
        )
    if any(keyword in message for keyword in LEARNING_DATA_KEYWORDS):
        return IntentResult(
            intent=IntentType.LEARNING_SUMMARY,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
            needs_live_data=True,
        )
    if any(keyword in message for keyword in REFUND_LIVE_DATA_KEYWORDS):
        return IntentResult(
            intent=IntentType.FEE_REFUND,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
            needs_live_data=True,
        )
    if is_live_schedule_request(message):
        intent = (
            IntentType.CLASS_TRANSFER
            if any(keyword in message for keyword in ("插班", "调班", "转班"))
            else IntentType.SCHEDULE_OR_SEAT
        )
        return IntentResult(
            intent=intent,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
            needs_live_data=True,
        )
    if any(keyword in message for keyword in STATIC_SERVICE_RULES_KEYWORDS):
        return IntentResult(
            intent=IntentType.SERVICE_RULES,
            confidence=1.0,
            mentioned_entity=entity,
            requested_attributes=attributes,
        )
    return None


def requires_live_data(message: str, intent: IntentType) -> bool:
    """对模型结果执行实时数据边界的确定性二次覆盖。"""

    dynamic_keywords = (
        *LEARNING_DATA_KEYWORDS,
        *REFUND_LIVE_DATA_KEYWORDS,
    )
    if any(keyword in message for keyword in dynamic_keywords):
        return True
    if is_live_schedule_request(message):
        return True
    return intent in {IntentType.LEARNING_SUMMARY, IntentType.LEARNING_REPORT}


def deterministic_fallback(
    message: str,
    *,
    active_entity: EntityReference | None = None,
    turn: TurnResolution | None = None,
) -> IntentResult:
    """没有可用模型时执行可解释、可审计的保守分类。"""

    resolution = turn or resolve_turn(message, active_entity)
    guarded = high_risk_result(message, resolution)
    if guarded is not None:
        return guarded

    entity = context_entity(resolution)
    attributes = resolution.requested_attributes
    if any(keyword in message for keyword in ("受伤", "磕碰", "过敏", "突发疾病", "安全")):
        intent = IntentType.SAFETY_HEALTH
    elif any(
        keyword in message
        for keyword in (
            "请假", "补课", "调课", "调到其他时间", "换个时间",
            "延期", "顺延", "过期",
        )
    ):
        intent = IntentType.SERVICE_RULES
    elif any(keyword in message for keyword in ("退费", "退款", "退课")):
        intent = IntentType.FEE_REFUND
    elif any(keyword in message for keyword in ("插班", "调班", "转班")):
        intent = IntentType.CLASS_TRANSFER
    elif any(keyword in message for keyword in ("试听", "预约体验")):
        intent = IntentType.TRIAL_BOOKING
    elif any(keyword in message for keyword in ("报名", "报课", "缴费")):
        intent = IntentType.ENROLLMENT
    elif any(keyword in message for keyword in ("授课风格", "老师履历", "教师履历", "老师介绍")):
        intent = IntentType.TEACHER_DETAIL
    elif any(keyword in message for keyword in ("校区", "地址", "怎么走", "停车", "环境")):
        intent = IntentType.CAMPUS_DETAIL
    elif any(keyword in message for keyword in ("好处", "帮助", "作用", "培养什么")):
        intent = IntentType.COURSE_BENEFIT
    elif any(keyword in message for keyword in ("推荐", "学什么", "怎么选", "选哪", "还是")):
        intent = IntentType.COURSE_RECOMMENDATION
    elif entity is not None or attributes:
        intent = IntentType.COURSE_DETAIL
    else:
        intent = IntentType.UNKNOWN

    return IntentResult(
        intent=intent,
        confidence=0.82 if intent != IntentType.UNKNOWN else 0.25,
        mentioned_entity=entity,
        requested_attributes=attributes,
        needs_live_data=requires_live_data(message, intent),
        clarification_needed=False,
    )
