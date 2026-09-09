"""班级级学情分析的确定性业务工具。

该模块把权限校验、数据库查询和指标计算固定在后端服务中。LLM/LangGraph
只负责识别用户意图和编排流程；A2A/DSH 后续只负责对已聚合的结果排版，不能
直接访问数据库，也不能重新计算完课率、出勤率或缺勤 TOP5。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.class_learning_contracts import ClassLearnerMetric, ClassLearningSummary
from backend.app.models import (
    Attendance,
    Campus,
    ClassGroup,
    Course,
    Enrollment,
    HourAccount,
    Learner,
    Lesson,
)
from backend.app.services.access_control import AccessContext, can_access_class


# 只认这组有限状态，原因是上游脏数据不能被静默解释成“缺勤”。未知值会
# 进入未登记统计，促使运营人员修复数据，而不是让报表产生虚假的风险结论。
_KNOWN_ATTENDANCE_STATUSES = {"present", "absent", "leave", "excused"}


def _empty_metric(
    learner_id: str,
    learner_name: str,
    scheduled_lessons: int,
    remaining_hours: int | None,
) -> dict[str, object]:
    """创建一名学员的零值统计容器，后续再填充考勤结果。

    先建立完整报名名单再合并考勤，是为了把“没有考勤记录”和“没有报名”
    区分开；前者应显示为未登记，不能从统计分母中悄悄删除。
    """

    return {
        "learner_id": learner_id,
        "learner_name": learner_name,
        "scheduled_lessons": scheduled_lessons,
        "marked_lessons": 0,
        "attended_lessons": 0,
        "absent_lessons": 0,
        "excused_lessons": 0,
        "unmarked_lessons": scheduled_lessons,
        "completion_rate": 0.0,
        "attendance_rate": 0.0,
        "remaining_hours": remaining_hours,
    }


def query_class_learning_summary(
    session: Session,
    context: AccessContext,
    class_id: str,
    period_start: date,
    period_end: date,
    *,
    low_balance_threshold: int = 5,
) -> ClassLearningSummary | None:
    """查询并计算授权班级的学情统计。

    统计口径如下：
    - 完课率 = 出勤课次 /（有效报名人数 × 周期内计划课次）；
    - 出勤率 = 出勤课次 / 已登记考勤结果数；
    - leave/ excused 计入请假，不计入出勤率分子；
    - 缺失或未知考勤状态计入未登记，不能被静默当作缺勤；
    - 缺勤 TOP5 按缺勤次数降序、学员编号升序；
    - 低课时名单使用 remaining_hours <= low_balance_threshold。

    未授权、班级不存在或班级已停用时统一返回 None，避免泄露班级存在性。

    该函数故意不接收“计算公式”或模型生成的 SQL。指标计算属于核心业务
    规则，应该可以被单元测试、审计和复算；LLM/DSH 只能在后续把结果写成
    报表，不应重新解释这些分子分母。
    """

    if period_start > period_end:
        raise ValueError("统计开始日期不能晚于结束日期")
    if not 0 <= low_balance_threshold <= 10000:
        raise ValueError("低课时阈值必须在 0 至 10000 之间")
    # 权限校验必须发生在查询班级详情之前，避免通过错误码或响应时间推断
    # 其他校区是否存在某个班级。
    if not can_access_class(session, context, class_id):
        return None

    class_group = session.get(ClassGroup, class_id)
    if class_group is None:
        return None
    course = session.get(Course, class_group.course_id)
    campus = session.get(Campus, class_group.campus_id)
    if course is None or campus is None:
        # 基础关联数据不完整时不生成部分可信的运营统计。
        return None

    enrollment_rows = session.execute(
        select(Enrollment.learner_id, Learner.display_name)
        .join(Learner, Learner.id == Enrollment.learner_id)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.is_active.is_(True),
            Learner.is_active.is_(True),
        )
        .order_by(Enrollment.learner_id.asc())
    ).all()
    learner_ids = [row.learner_id for row in enrollment_rows]

    lessons = session.scalars(
        select(Lesson)
        .where(
            Lesson.class_id == class_id,
            Lesson.lesson_date >= period_start,
            Lesson.lesson_date <= period_end,
        )
        .order_by(Lesson.lesson_date.asc(), Lesson.id.asc())
    ).all()
    lesson_ids = [lesson.id for lesson in lessons]
    scheduled_lessons = len(lessons)

    # 课时账户与考勤是两个独立数据源；缺少课时账户时保留 None，不能把
    # “未知”误写成 0，否则会把数据缺失错误地呈现为低课时预警。
    balances = {
        row.learner_id: row.remaining_hours
        for row in session.scalars(
            select(HourAccount).where(HourAccount.learner_id.in_(learner_ids))
        ).all()
    }
    metrics: dict[str, dict[str, object]] = {
        row.learner_id: _empty_metric(
            row.learner_id,
            row.display_name,
            scheduled_lessons,
            balances.get(row.learner_id),
        )
        for row in enrollment_rows
    }

    attendance_rows = session.execute(
        select(Attendance.learner_id, Attendance.lesson_id, Attendance.status)
        .where(
            Attendance.learner_id.in_(learner_ids),
            Attendance.lesson_id.in_(lesson_ids),
        )
    ).all()
    lesson_set = set(lesson_ids)
    for row in attendance_rows:
        # 只接受当前班级、当前周期、有效报名学员的考勤记录。
        if row.learner_id not in metrics or row.lesson_id not in lesson_set:
            continue
        metric = metrics[row.learner_id]
        status = row.status.lower()
        if status not in _KNOWN_ATTENDANCE_STATUSES:
            # 未知状态保守归入未登记，不把异常数据误算成缺勤。
            continue
        metric["marked_lessons"] = int(metric["marked_lessons"]) + 1
        metric["unmarked_lessons"] = int(metric["unmarked_lessons"]) - 1
        if status == "present":
            metric["attended_lessons"] = int(metric["attended_lessons"]) + 1
        elif status == "absent":
            metric["absent_lessons"] = int(metric["absent_lessons"]) + 1
        else:
            metric["excused_lessons"] = int(metric["excused_lessons"]) + 1

    # Pydantic 契约在这里作为第二道门，确保数据库聚合结果满足字段范围和
    # 计数关系，再允许它进入接口响应或脱敏后交给远程报告节点。
    learner_metrics: list[ClassLearnerMetric] = []
    for learner_id in learner_ids:
        raw = metrics[learner_id]
        scheduled = int(raw["scheduled_lessons"])
        marked = int(raw["marked_lessons"])
        raw["completion_rate"] = int(raw["attended_lessons"]) / (scheduled or 1)
        raw["attendance_rate"] = int(raw["attended_lessons"]) / (marked or 1)
        learner_metrics.append(ClassLearnerMetric.model_validate(raw))

    expected_records = scheduled_lessons * len(learner_metrics)
    marked_records = sum(metric.marked_lessons for metric in learner_metrics)
    attended_records = sum(metric.attended_lessons for metric in learner_metrics)
    absent_records = sum(metric.absent_lessons for metric in learner_metrics)
    excused_records = sum(metric.excused_lessons for metric in learner_metrics)
    unmarked_records = sum(metric.unmarked_lessons for metric in learner_metrics)

    # 固定排序规则可以让同一批数据每次生成相同结果，便于运营复核和测试。
    absence_top5 = sorted(
        (metric for metric in learner_metrics if metric.absent_lessons > 0),
        key=lambda metric: (-metric.absent_lessons, metric.learner_id),
    )[:5]
    low_balance_learners = sorted(
        (
            metric
            for metric in learner_metrics
            if metric.remaining_hours is not None
            and metric.remaining_hours <= low_balance_threshold
        ),
        key=lambda metric: (metric.remaining_hours, metric.learner_id),
    )

    # 最终汇总只使用本函数得到的确定性指标；后续自然语言层只能负责解释，
    # 不能覆盖这些数值。
    return ClassLearningSummary(
        class_id=class_group.id,
        class_name=class_group.name,
        course_name=course.name,
        campus_name=campus.name,
        period_start=period_start,
        period_end=period_end,
        scheduled_lessons=scheduled_lessons,
        enrolled_learners=len(learner_metrics),
        expected_attendance_records=expected_records,
        marked_attendance_records=marked_records,
        attended_records=attended_records,
        absent_records=absent_records,
        excused_records=excused_records,
        unmarked_records=unmarked_records,
        completion_rate=attended_records / (expected_records or 1),
        attendance_rate=attended_records / (marked_records or 1),
        low_balance_threshold=low_balance_threshold,
        missing_hour_accounts=sum(metric.remaining_hours is None for metric in learner_metrics),
        learner_metrics=learner_metrics,
        absence_top5=absence_top5,
        low_balance_learners=low_balance_learners,
    )
