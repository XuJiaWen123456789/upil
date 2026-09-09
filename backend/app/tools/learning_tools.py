"""学情分析智能体的受控工具。

本模块把“身份授权、结构化查询、指标计算、脱敏输出”固定成工具边界。
自然语言模型负责识别用户意图和解释结果，但不能自行计算课时、出勤率或
学习进度，也不能直接访问 ORM Session。
"""

import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.learning_contracts import (
    AttendanceSummary,
    LearnerProfile,
    LessonBalance,
    ProgressRecord,
)
from backend.app.models import Attendance, HourAccount, Learner, Lesson
from backend.app.services.access_control import AccessContext, can_access_learner


STRUCTURED_DATA_DIR = Path(__file__).resolve().parents[3] / "knowledge_base" / "structured"
PROGRESS_FILE = STRUCTURED_DATA_DIR / "progress_records.json"


def _has_learner_access(session: Session, context: AccessContext, learner_id: str) -> bool:
    """统一执行学员访问校验，调用方不会得到越权对象的差异化结果。"""

    return can_access_learner(session, context, learner_id)


def query_learner_profile(
    session: Session, context: AccessContext, learner_id: str
) -> LearnerProfile | None:
    """查询学员基础资料。"""

    if not _has_learner_access(session, context, learner_id):
        return None
    learner = session.get(Learner, learner_id)
    if learner is None:
        return None
    return LearnerProfile(
        learner_id=learner.id,
        learner_name=learner.display_name,
        active=learner.is_active,
    )


def query_attendance_summary(
    session: Session,
    context: AccessContext,
    learner_id: str,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> AttendanceSummary | None:
    """查询并计算出勤率、缺勤和请假次数。"""

    if not _has_learner_access(session, context, learner_id):
        return None

    # 通过课次日期筛选，避免将未来课次或其他时间范围混入统计口径。
    conditions = [Attendance.learner_id == learner_id]
    if period_start is not None:
        conditions.append(Lesson.lesson_date >= period_start)
    if period_end is not None:
        conditions.append(Lesson.lesson_date <= period_end)

    rows = session.execute(
        select(Attendance.status)
        .join(Lesson, Lesson.id == Attendance.lesson_id)
        .where(*conditions)
    ).scalars().all()
    total = len(rows)
    present = sum(status == "present" for status in rows)
    absent = sum(status == "absent" for status in rows)
    leave = sum(status in {"leave", "excused"} for status in rows)

    return AttendanceSummary(
        learner_id=learner_id,
        total_lessons=total,
        present_lessons=present,
        absent_lessons=absent,
        leave_lessons=leave,
        attendance_rate=present / total if total else 0.0,
        period_start=period_start,
        period_end=period_end,
    )


def query_lesson_balance(
    session: Session, context: AccessContext, learner_id: str
) -> LessonBalance | None:
    """查询学员的总课时、已消课时和剩余课时。"""

    if not _has_learner_access(session, context, learner_id):
        return None
    account = session.get(HourAccount, learner_id)
    if account is None:
        return None
    return LessonBalance(
        learner_id=account.learner_id,
        total_hours=account.total_hours,
        consumed_hours=account.consumed_hours,
        remaining_hours=account.remaining_hours,
    )


def query_learning_progress(
    session: Session, context: AccessContext, learner_id: str
) -> list[ProgressRecord]:
    """读取结构化阶段进度；无权限或无记录时统一返回空列表。"""

    if not _has_learner_access(session, context, learner_id):
        return []
    if not PROGRESS_FILE.exists():
        return []

    # 进度资料是演示用结构化快照；生产环境应替换为教务系统只读接口。
    raw_records = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return [
        ProgressRecord.model_validate(record)
        for record in raw_records
        if record.get("learner_id") == learner_id
    ]


def query_learning_snapshot(
    session: Session, context: AccessContext, learner_id: str
) -> dict | None:
    """组合调用四个白名单工具，返回可交给智能体的学情快照。"""

    profile = query_learner_profile(session, context, learner_id)
    balance = query_lesson_balance(session, context, learner_id)
    attendance = query_attendance_summary(session, context, learner_id)
    if profile is None or balance is None or attendance is None:
        return None
    return {
        "profile": profile,
        "balance": balance,
        "attendance": attendance,
        "progress": query_learning_progress(session, context, learner_id),
    }
