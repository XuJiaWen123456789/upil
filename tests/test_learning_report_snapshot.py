"""阶段 14-A-3：家长学情报告快照的权限、统计和脱敏测试。"""

from datetime import date

import pytest

from backend.app.services.access_control import AccessContext
from backend.app.services.learning_reports import (
    ReportPeriodResolutionError,
    build_learning_report_snapshot,
)
from tests.test_database import make_session, seed_session


DEMO_TODAY = date(2026, 9, 8)


def test_report_snapshot_uses_requested_period_and_backend_metrics() -> None:
    """上个月报告应使用指定日期范围，并由后端给出出勤率。"""

    with make_session() as session:
        seed_session(session)
        snapshot = build_learning_report_snapshot(
            session,
            AccessContext("P1001", "parent"),
            "L1001",
            "帮我生成上个月的学情报告",
            today=DEMO_TODAY,
        )

    assert snapshot is not None
    assert snapshot.period.period_start == date(2026, 8, 1)
    assert snapshot.period.period_end == date(2026, 8, 31)
    assert snapshot.scheduled_sessions == 2
    assert snapshot.attended_sessions == 1
    assert snapshot.excused_absences == 0
    assert snapshot.unexcused_absences == 1
    assert snapshot.attendance_rate == 0.5
    assert snapshot.completed_lessons == 8
    assert snapshot.remaining_lessons == 12
    assert snapshot.course_summaries == ["中国舞基础：基础节奏与身体协调"]


def test_report_snapshot_only_exposes_published_progress() -> None:
    """报告快照只能包含已发布阶段字段，不能泄露内部教师备注和原始编号。"""

    with make_session() as session:
        seed_session(session)
        snapshot = build_learning_report_snapshot(
            session,
            AccessContext("P1001", "parent"),
            "L1001",
            "查看 2026年8月的学情报告",
            today=DEMO_TODAY,
        )

    assert snapshot is not None
    payload = snapshot.model_dump(mode="json")
    serialized = str(payload)
    assert snapshot.learner_ref != "L1001"
    assert "L1001" not in serialized
    assert "演示学员" not in serialized
    assert "teacher_note" not in serialized
    assert "建议每周完成两次十分钟基础拉伸" not in serialized
    assert payload["published_progress"][0]["course_name"] == "中国舞基础"
    assert payload["published_progress"][0]["completion_rate"] == 0.4


def test_report_snapshot_denies_unbound_learner_without_data_difference() -> None:
    """未绑定学员不能生成报告，且不返回任何学情事实。"""

    with make_session() as session:
        seed_session(session)
        snapshot = build_learning_report_snapshot(
            session,
            AccessContext("P1001", "parent"),
            "L2001",
            "生成上个月的学情报告",
            today=DEMO_TODAY,
        )

    assert snapshot is None


def test_report_snapshot_requires_an_explicit_period() -> None:
    """没有明确周期时不能静默选择最近一段时间。"""

    with make_session() as session:
        seed_session(session)
        with pytest.raises(ReportPeriodResolutionError):
            build_learning_report_snapshot(
                session,
                AccessContext("P1001", "parent"),
                "L1001",
                "帮我生成孩子的学情报告",
                today=DEMO_TODAY,
            )
