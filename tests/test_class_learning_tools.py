"""阶段 14-C-1B：班级级学情统计、权限和数据完整性测试。

这些测试直接复用 seed_demo_data 写入的舞蹈演示数据，验证班级统计工具的
确定性结果。测试不调用 LLM、RAGFlow 或 A2A，确保统计口径不会被模型输出影响。
"""

from datetime import date

from backend.app.services.access_control import AccessContext
from backend.app.services.seed import seed_demo_data
from backend.app.tools.class_learning_tools import query_class_learning_summary
from tests.test_database import make_session


def seeded_session():
    """创建并初始化一份隔离数据库，避免测试依赖本地 PostgreSQL。"""

    session = make_session()
    seed_demo_data(session)
    return session


def test_teacher_and_admin_class_scope_is_enforced() -> None:
    """教师只能查自己授课的班级，管理员只能查授权校区的班级。"""

    with seeded_session() as session:
        main_teacher = AccessContext("T1001", "teacher", frozenset({"C01"}))
        branch_teacher = AccessContext("T1002", "teacher", frozenset({"C02"}))
        idle_teacher = AccessContext("T1003", "teacher", frozenset({"C01"}))
        main_admin = AccessContext("A1001", "admin", frozenset({"C01"}))
        branch_admin = AccessContext("A2001", "admin", frozenset({"C02"}))
        period_start = date(2026, 8, 1)
        period_end = date(2026, 8, 31)

        assert query_class_learning_summary(
            session, main_teacher, "CLASS_DANCE_01", period_start, period_end
        ) is not None
        assert query_class_learning_summary(
            session, main_teacher, "CLASS_DANCE_02", period_start, period_end
        ) is None
        assert query_class_learning_summary(
            session, branch_teacher, "CLASS_DANCE_02", period_start, period_end
        ) is not None
        assert query_class_learning_summary(
            session, idle_teacher, "CLASS_DANCE_01", period_start, period_end
        ) is None
        assert query_class_learning_summary(
            session, main_admin, "CLASS_DANCE_01", period_start, period_end
        ) is not None
        assert query_class_learning_summary(
            session, main_admin, "CLASS_DANCE_02", period_start, period_end
        ) is None
        assert query_class_learning_summary(
            session, branch_admin, "CLASS_DANCE_02", period_start, period_end
        ) is not None


def test_parent_cannot_read_class_level_summary() -> None:
    """家长可查询本人孩子，但不能读取包含其他学员的班级聚合数据。"""

    with seeded_session() as session:
        parent = AccessContext("P1001", "parent")
        summary = query_class_learning_summary(
            session,
            parent,
            "CLASS_DANCE_01",
            date(2026, 8, 1),
            date(2026, 8, 31),
        )

        assert summary is None


def test_dance_class_summary_uses_seeded_business_data() -> None:
    """验证舞蹈一班的完课率、出勤率、缺勤 TOP5 和低课时名单。"""

    with seeded_session() as session:
        teacher = AccessContext("T1001", "teacher", frozenset({"C01"}))
        summary = query_class_learning_summary(
            session,
            teacher,
            "CLASS_DANCE_01",
            date(2026, 8, 1),
            date(2026, 8, 31),
        )

        assert summary is not None
        assert summary.class_name == "舞蹈一班"
        assert summary.course_name == "舞蹈"
        assert summary.campus_name == "主校区"
        assert summary.scheduled_lessons == 6
        assert summary.enrolled_learners == 12
        assert summary.expected_attendance_records == 72
        assert summary.marked_attendance_records == 71
        assert summary.attended_records == 41
        assert summary.absent_records == 26
        assert summary.excused_records == 4
        assert summary.unmarked_records == 1
        assert summary.completion_rate == 41 / 72
        assert summary.attendance_rate == 41 / 71

        assert [metric.learner_id for metric in summary.absence_top5] == [
            "L1003",
            "L1004",
            "L1005",
            "L1007",
            "L1001",
        ]
        assert [metric.absent_lessons for metric in summary.absence_top5] == [4, 4, 3, 3, 2]
        assert [metric.learner_id for metric in summary.low_balance_learners] == [
            "L1004",
            "L1003",
            "L1007",
        ]
        assert [metric.remaining_hours for metric in summary.low_balance_learners] == [2, 3, 4]
        assert summary.missing_hour_accounts == 1


def test_unmarked_attendance_is_not_counted_as_absence() -> None:
    """L1012 的未登记课次应保留为未登记，而不能静默计入缺勤。"""

    with seeded_session() as session:
        teacher = AccessContext("T1001", "teacher", frozenset({"C01"}))
        summary = query_class_learning_summary(
            session,
            teacher,
            "CLASS_DANCE_01",
            date(2026, 8, 1),
            date(2026, 8, 31),
        )

        assert summary is not None
        learner = next(metric for metric in summary.learner_metrics if metric.learner_id == "L1012")
        assert learner.marked_lessons == 5
        assert learner.unmarked_lessons == 1
        assert learner.absent_lessons == 2
        assert summary.absent_records == 26
        assert summary.unmarked_records == 1


def test_class_summary_respects_date_range() -> None:
    """统计周期只应包含周期内的舞蹈课次，不应把后续课次混入结果。"""

    with seeded_session() as session:
        teacher = AccessContext("T1001", "teacher", frozenset({"C01"}))
        summary = query_class_learning_summary(
            session,
            teacher,
            "CLASS_DANCE_01",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )

        assert summary is not None
        assert summary.scheduled_lessons == 2
        assert summary.enrolled_learners == 12
        assert summary.expected_attendance_records == 24
        assert summary.marked_attendance_records == 24
        assert summary.attended_records == 14
        assert summary.absent_records == 9
        assert summary.excused_records == 1
        assert summary.unmarked_records == 0


def test_invalid_period_and_threshold_are_rejected() -> None:
    """非法日期范围和课时阈值应在查询前被拒绝。"""

    with seeded_session() as session:
        teacher = AccessContext("T1001", "teacher", frozenset({"C01"}))

        try:
            query_class_learning_summary(
                session,
                teacher,
                "CLASS_DANCE_01",
                date(2026, 8, 31),
                date(2026, 8, 1),
            )
        except ValueError as exc:
            assert "开始日期" in str(exc)
        else:
            raise AssertionError("反向日期范围应抛出 ValueError")

        try:
            query_class_learning_summary(
                session,
                teacher,
                "CLASS_DANCE_01",
                date(2026, 8, 1),
                date(2026, 8, 31),
                low_balance_threshold=-1,
            )
        except ValueError as exc:
            assert "阈值" in str(exc)
        else:
            raise AssertionError("负数课时阈值应抛出 ValueError")
