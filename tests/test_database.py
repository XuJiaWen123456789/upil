"""数据库模型、权限、学情查询和任务审计测试。"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.models import (
    Attendance,
    Campus,
    ClassGroup,
    Course,
    Enrollment,
    HourAccount,
    Learner,
    Lesson,
    ParentLearner,
    ReportArtifact,
    User,
)
from backend.app.services.access_control import AccessContext, can_access_learner
from backend.app.services.audit import write_audit_log
from backend.app.services.learning import get_learning_summary
from backend.app.services.report_tasks import add_report_artifact, create_report_task
from backend.app.services.seed import seed_demo_data


def make_session() -> Session:
    """创建隔离的内存 SQLite 会话，避免测试依赖外部数据库。"""

    # TestClient 可能在不同线程执行请求；StaticPool 保证所有线程共享同一
    # 条 SQLite 内存连接，否则 API 请求会看到一个没有建表的空数据库。
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_session(session: Session) -> None:
    """写入覆盖权限和学情统计场景的最小测试数据集。"""

    session.add_all([
        Campus(id="C01", name="主校区"),
        Campus(id="C02", name="分校区"),
        User(id="P1001", display_name="演示家长", role="parent"),
        User(id="T1001", display_name="演示教师", role="teacher", campus_id="C01"),
        User(id="A1001", display_name="演示管理员", role="admin", campus_id="C01"),
        Learner(id="L1001", display_name="演示学员"),
        Learner(id="L2001", display_name="其他学员"),
        Course(id="COURSE_DANCE", name="舞蹈", category="舞蹈"),
        ClassGroup(id="CLASS_DANCE_01", name="舞蹈一班", campus_id="C01", course_id="COURSE_DANCE", teacher_id="T1001"),
        ClassGroup(id="CLASS_DANCE_02", name="舞蹈二班", campus_id="C02", course_id="COURSE_DANCE", teacher_id="T1001"),
        ParentLearner(parent_id="P1001", learner_id="L1001"),
        Enrollment(class_id="CLASS_DANCE_01", learner_id="L1001"),
        Enrollment(class_id="CLASS_DANCE_02", learner_id="L2001"),
        HourAccount(learner_id="L1001", total_hours=20, consumed_hours=8, remaining_hours=12),
        HourAccount(learner_id="L2001", total_hours=20, consumed_hours=4, remaining_hours=16),
        Lesson(id="LESSON_01", class_id="CLASS_DANCE_01", lesson_date=date(2026, 8, 1), planned_hours=1),
        Lesson(id="LESSON_02", class_id="CLASS_DANCE_01", lesson_date=date(2026, 8, 8), planned_hours=1),
        Attendance(lesson_id="LESSON_01", learner_id="L1001", status="present"),
        Attendance(lesson_id="LESSON_02", learner_id="L1001", status="absent"),
    ])
    session.commit()


def test_parent_can_only_access_bound_learner() -> None:
    """家长只能读取 parent_learners 中已绑定的学员。"""

    with make_session() as session:
        seed_session(session)
        parent = AccessContext(user_id="P1001", role="parent")
        assert can_access_learner(session, parent, "L1001")
        assert not can_access_learner(session, parent, "L2001")


def test_teacher_scope_is_limited_to_taught_class_and_campus() -> None:
    """教师不能跨自己授课范围或校区读取学员。"""

    with make_session() as session:
        seed_session(session)
        teacher = AccessContext(user_id="T1001", role="teacher", campus_ids=frozenset({"C01"}))
        assert can_access_learner(session, teacher, "L1001")
        assert not can_access_learner(session, teacher, "L2001")


def test_learning_summary_uses_database_values() -> None:
    """学情摘要应来自数据库计算，而不是固定模拟值。"""

    with make_session() as session:
        seed_session(session)
        summary = get_learning_summary(session, AccessContext("P1001", "parent"), "L1001")
        assert summary is not None
        assert summary["remaining_hours"] == 12
        assert summary["consumed_hours"] == 8
        assert summary["attendance_rate"] == 0.5
        assert summary["recent_absences"] == 1


def test_audit_and_report_artifacts_are_traceable() -> None:
    """报表任务和产物应能通过 task_id 追踪，并留下审计记录。"""

    with make_session() as session:
        seed_session(session)
        write_audit_log(
            session,
            actor_user_id="A1001",
            action="report.create",
            resource_type="report_task",
            resource_id="RT001",
            outcome="success",
            metadata={"scope": {"campus_id": "C01"}},
        )
        task = create_report_task(
            session,
            task_id="RT001",
            requester_id="A1001",
            task_type="class_attendance_report",
            scope={"class_id": "CLASS_DANCE_01"},
            metrics=["completion_rate", "absence_top5"],
            template_version="attendance-report-v1",
        )
        artifact = add_report_artifact(
            session,
            artifact_id="ART001",
            task_id=task.id,
            artifact_type="markdown",
            content="# 报表\n",
        )
        session.commit()
        assert artifact.report_task_id == "RT001"
        assert session.get(ReportArtifact, "ART001") is not None


def test_demo_seed_is_idempotent(tmp_path) -> None:
    """开发初始化脚本重复执行时不应产生重复业务数据。"""

    database_url = f"sqlite:///{tmp_path / 'upil.db'}"
    from backend.app.db import build_engine, build_session_factory

    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    factory = build_session_factory(database_url)
    with factory() as session:
        first_added = seed_demo_data(session)
        second_added = seed_demo_data(session)
        assert first_added > 0
        assert second_added == 0
        assert session.get(Learner, "L1001") is not None
