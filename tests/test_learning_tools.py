"""阶段 5B：结构化学情工具和接口契约测试。"""

from datetime import date

from backend.app.learning_contracts import ProgressRecord
from backend.app.services.access_control import AccessContext
from backend.app.services.learning import get_learning_snapshot
from backend.app.tools.learning_tools import (
    query_attendance_summary,
    query_learning_progress,
    query_lesson_balance,
    query_learner_profile,
)
from tests.test_database import make_session, seed_session


def test_learning_tools_return_structured_contracts() -> None:
    """四个白名单工具应返回契约对象，而不是散乱字典或 ORM 实例。"""

    with make_session() as session:
        seed_session(session)
        context = AccessContext("P1001", "parent")
        assert query_learner_profile(session, context, "L1001").learner_name == "演示学员"
        assert query_lesson_balance(session, context, "L1001").remaining_hours == 12
        attendance = query_attendance_summary(session, context, "L1001")
        assert attendance.total_lessons == 2
        assert attendance.present_lessons == 1
        assert attendance.absent_lessons == 1
        assert query_learning_progress(session, context, "L1001")[0].course_name == "中国舞基础"


def test_attendance_tool_supports_date_range() -> None:
    """出勤工具应按课次日期筛选，保证统计口径可解释。"""

    with make_session() as session:
        seed_session(session)
        context = AccessContext("P1001", "parent")
        result = query_attendance_summary(
            session,
            context,
            "L1001",
            period_start=date(2026, 8, 8),
            period_end=date(2026, 8, 8),
        )
        assert result.total_lessons == 1
        assert result.present_lessons == 0
        assert result.absent_lessons == 1
        assert result.attendance_rate == 0


def test_learning_tools_hide_unbound_learner() -> None:
    """越权访问的所有工具都必须返回统一的空结果。"""

    with make_session() as session:
        seed_session(session)
        context = AccessContext("P1001", "parent")
        assert query_learner_profile(session, context, "L2001") is None
        assert query_lesson_balance(session, context, "L2001") is None
        assert query_attendance_summary(session, context, "L2001") is None
        assert query_learning_progress(session, context, "L2001") == []


def test_learning_snapshot_is_ready_for_a2a_task_payload() -> None:
    """组合快照应由可序列化契约组成，便于未来封装 A2A Task。"""

    with make_session() as session:
        seed_session(session)
        snapshot = get_learning_snapshot(session, AccessContext("P1001", "parent"), "L1001")
        assert snapshot is not None
        assert snapshot["profile"].learner_id == "L1001"
        assert snapshot["attendance"].attendance_rate == 0.5
        assert isinstance(snapshot["progress"][0], ProgressRecord)
        payload = {key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value for key, value in snapshot.items()}
        assert payload["balance"]["remaining_hours"] == 12
        assert payload["attendance"]["attendance_rate"] == 0.5
