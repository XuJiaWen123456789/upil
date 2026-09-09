"""家长学情报告的周期解析和脱敏快照服务。

本模块负责把家长消息中的时间表达转换为确定的日期范围，并组合已经授权的
结构化查询结果。它不调用 LLM、A2A 或 DSH，避免远程节点自行猜测统计边界、
访问业务数据库或接触姓名和原始学员编号。
"""

from __future__ import annotations

import hashlib
import re
from calendar import monthrange
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from backend.app.learning_contracts import (
    LearningReportPeriod,
    LearningReportSnapshot,
    PublishedProgress,
)
from backend.app.services.access_control import AccessContext
from backend.app.tools.learning_tools import (
    query_attendance_summary,
    query_learning_progress,
    query_lesson_balance,
    query_learner_profile,
)


class ReportPeriodResolutionError(ValueError):
    """用户没有提供可安全解释的报告统计周期。"""


def _learner_reference(learner_id: str) -> str:
    """将原始学员编号转换为远程任务可使用的不可逆引用。"""

    # 远程 A2A 节点只需要关联同一任务的匿名标识，不需要知道业务库主键。
    digest = hashlib.sha256(learner_id.encode("utf-8")).hexdigest()[:24]
    return f"learner_ref_{digest}"


def build_learning_report_snapshot(
    session: Session,
    context: AccessContext,
    learner_id: str,
    message: str,
    *,
    today: date | None = None,
) -> LearningReportSnapshot | None:
    """构建指定周期的脱敏学情报告快照。

    周期解析、权限检查、出勤率计算和字段脱敏都在主服务完成；该函数不调用
    LLM、A2A 或 DSH。返回的快照可以安全地交给后续协议层继续校验。

    None 同时覆盖学员不存在、绑定关系不存在和基础数据缺失，避免调用方
    通过错误差异推断其他学员是否存在。
    """

    period = resolve_report_period(message, today=today)

    # 先读取最小的基础资料执行统一授权；姓名只用于确认数据存在，绝不写入快照。
    profile = query_learner_profile(session, context, learner_id)
    balance = query_lesson_balance(session, context, learner_id)
    attendance = query_attendance_summary(
        session,
        context,
        learner_id,
        period_start=period.period_start,
        period_end=period.period_end,
    )
    if profile is None or balance is None or attendance is None:
        return None

    progress_records = query_learning_progress(session, context, learner_id)

    # 只把已发布字段转换为家长可见进度；teacher_note 和 learner_id 不出现在远程输入。
    published_progress = [
        PublishedProgress(
            course_name=record.course_name,
            current_stage=record.current_stage,
            completion_rate=record.completion_rate,
            strengths=list(record.strengths),
            next_focus=list(record.next_focus),
            updated_at=record.updated_at,
        )
        for record in progress_records
    ]

    # 课程摘要只保留课程名称和当前阶段，供报告标题或分组使用。
    course_summaries: list[str] = []
    for record in published_progress:
        summary = f"{record.course_name}：{record.current_stage}"
        if summary not in course_summaries:
            course_summaries.append(summary)

    # 出勤率已由 query_attendance_summary 根据数据库记录确定性计算；这里再次使用
    # 该契约值，不允许自然语言模型或远程执行节点重新推算统计数字。
    return LearningReportSnapshot(
        learner_ref=_learner_reference(learner_id),
        period=period,
        course_summaries=course_summaries,
        scheduled_sessions=attendance.total_lessons,
        attended_sessions=attendance.present_lessons,
        excused_absences=attendance.leave_lessons,
        unexcused_absences=attendance.absent_lessons,
        attendance_rate=attendance.attendance_rate,
        completed_lessons=balance.consumed_hours,
        remaining_lessons=balance.remaining_hours,
        published_progress=published_progress,
    )


# 只识别包含年、月、日的完整日期，避免把订单号或学员编号误识别为日期。
_FULL_DATE_PATTERN = re.compile(
    r"(?<!\d)"
    r"(?P<year>\d{4})\s*(?:年|[-/])\s*"
    r"(?P<month>\d{1,2})\s*(?:月|[-/])\s*"
    r"(?P<day>\d{1,2})\s*日?"
    r"(?!\d)"
)

# 月份表达用于“2026年8月”这类完整月度报告；完整日期会优先被识别。
_MONTH_PATTERN = re.compile(
    r"(?<!\d)(?P<year>\d{4})\s*(?:年|[-/])\s*"
    r"(?P<month>\d{1,2})\s*月?(?!\d)"
)

_RANGE_CONNECTOR_PATTERN = re.compile(r"从|至|到|截止|期间|区间|~|～|—|–")
_PREVIOUS_MONTH_PATTERN = re.compile(r"上个月|上月|上一个月")
_CURRENT_MONTH_PATTERN = re.compile(r"本月|这个月|当月")
_RECENT_30_DAYS_PATTERN = re.compile(r"(?:最近|近)\s*(?:30|三十)\s*天")


def _month_start(year: int, month: int) -> date:
    """返回指定月份的第一天。"""

    return date(year, month, 1)


def _month_end(year: int, month: int) -> date:
    """返回指定月份的最后一天。"""

    return date(year, month, monthrange(year, month)[1])


def _period_label(start: date, end: date) -> str:
    """生成适合家长报告标题和任务审计的稳定周期标签。"""

    if start.year == end.year and start.month == end.month:
        return f"{start.year}年{start.month}月"
    return f"{start.isoformat()}至{end.isoformat()}"


def _build_period(
    *,
    start: date,
    end: date,
    period_type: str,
    today: date,
) -> LearningReportPeriod:
    """统一校验日期范围，并创建领域层周期模型。"""

    if start > end:
        raise ReportPeriodResolutionError("报告开始日期不能晚于结束日期")
    # 报告不能查询未来数据；这也能避免当前月份被错误扩展到未来日期。
    if end > today:
        raise ReportPeriodResolutionError("报告结束日期不能晚于当前日期")
    # 限制单次报告范围，防止误输入造成超大统计任务。
    if (end - start).days > 366:
        raise ReportPeriodResolutionError("单次报告周期不能超过 367 天")

    return LearningReportPeriod(
        period_start=start,
        period_end=end,
        period_label=_period_label(start, end),
        period_type=period_type,
    )


def _parse_full_dates(message: str) -> list[date]:
    """解析消息中的完整日期，并把非法日期转换成业务错误。"""

    dates: list[date] = []
    for match in _FULL_DATE_PATTERN.finditer(message):
        try:
            dates.append(
                date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError as exc:
            raise ReportPeriodResolutionError("报告日期格式不合法") from exc
    return dates


def _parse_custom_period(message: str, *, today: date) -> LearningReportPeriod | None:
    """解析明确日期范围或完整月份；无法识别时返回 None。"""

    full_dates = _parse_full_dates(message)
    if full_dates:
        # 两个完整日期只有在文本表达了范围关系时才接受，避免误把两个无关日期拼接。
        if len(full_dates) != 2 or not _RANGE_CONNECTOR_PATTERN.search(message):
            raise ReportPeriodResolutionError(
                "请提供明确的起止日期，例如：2026-08-01 至 2026-08-31"
            )
        return _build_period(
            start=full_dates[0],
            end=full_dates[1],
            period_type="custom",
            today=today,
        )

    month_match = _MONTH_PATTERN.search(message)
    if month_match:
        year = int(month_match.group("year"))
        month = int(month_match.group("month"))
        try:
            start = _month_start(year, month)
            end = _month_end(year, month)
        except ValueError as exc:
            raise ReportPeriodResolutionError("报告月份格式不合法") from exc
        return _build_period(start=start, end=end, period_type="custom", today=today)
    return None


def resolve_report_period(message: str, *, today: date | None = None) -> LearningReportPeriod:
    """把家长消息解析为确定的报告周期。

    支持的表达包括：
    - “上个月”或“上月”：上一个自然月；
    - “本月”或“这个月”：本月 1 日至 today；
    - “最近 30 天”：today 往前数 30 个自然日（含 today）；
    - “2026-08-01 至 2026-08-31”或“2026年8月”：明确自定义周期。

    未提供周期、提供模糊周期或同时出现多个周期时直接抛出异常，调用方应向家长
    澄清，而不是让模型自行选择一个日期范围。
    """

    normalized = message.strip()
    if not normalized:
        raise ReportPeriodResolutionError("请说明需要生成哪个时间段的学情报告")
    current_date = today or date.today()

    # 显式日期优先，避免“2026年8月报告，上个月……”这类混合输入静默选错周期。
    custom_period = _parse_custom_period(normalized, today=current_date)
    if custom_period is not None:
        return custom_period

    matched_periods = sum(
        [
            bool(_PREVIOUS_MONTH_PATTERN.search(normalized)),
            bool(_CURRENT_MONTH_PATTERN.search(normalized)),
            bool(_RECENT_30_DAYS_PATTERN.search(normalized)),
        ]
    )
    if matched_periods > 1:
        raise ReportPeriodResolutionError("一次报告只能指定一个统计周期")

    if _PREVIOUS_MONTH_PATTERN.search(normalized):
        first_of_current_month = _month_start(current_date.year, current_date.month)
        previous_day = first_of_current_month - timedelta(days=1)
        return _build_period(
            start=_month_start(previous_day.year, previous_day.month),
            end=previous_day,
            period_type="previous_month",
            today=current_date,
        )

    if _CURRENT_MONTH_PATTERN.search(normalized):
        return _build_period(
            start=_month_start(current_date.year, current_date.month),
            end=current_date,
            period_type="current_month",
            today=current_date,
        )

    if _RECENT_30_DAYS_PATTERN.search(normalized):
        return _build_period(
            start=current_date - timedelta(days=29),
            end=current_date,
            period_type="recent_30_days",
            today=current_date,
        )

    raise ReportPeriodResolutionError(
        "当前未识别到明确报告周期，请说明上个月、本月、最近30天或具体起止日期"
    )
