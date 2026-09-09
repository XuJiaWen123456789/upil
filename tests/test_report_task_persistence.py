"""阶段 14-A-5：报告任务生命周期、幂等和产物安全持久化测试。"""

from hashlib import sha256

import pytest
from pydantic import ValidationError

from backend.app.models import ReportArtifact
from backend.app.services.report_tasks import (
    ReportTaskConflictError,
    ReportTaskError,
    complete_report_task,
    create_report_task,
    fail_report_task,
    list_report_artifacts,
    mark_report_task_running,
)
from tests.test_database import make_session, seed_session


def create_demo_report_task(session, *, period: str = "2026-08"):
    """创建一条使用虚构学员引用的家长月度报告任务。"""

    return create_report_task(
        session,
        task_id="REPORT_TASK_001",
        requester_id="P1001",
        task_type="parent_learning_report",
        scope={"learner_ref": "learner_ref_demo_001", "period": period},
        metrics=["attendance_rate", "lesson_balance", "published_progress"],
        template_version="learning-report-v1",
    )


def valid_report_content() -> str:
    """返回不含身份信息和可执行内容的固定 Markdown 报告。"""

    return (
        "# 学情报告\n\n"
        "- 报告周期：2026年8月\n"
        "- 出勤率：50%\n"
        "- 剩余课时：12 节\n"
    )


def test_create_task_is_pending_and_same_request_is_idempotent() -> None:
    """首次创建为 pending，相同 task_id 与参数重放时只保留一条记录。"""

    with make_session() as session:
        seed_session(session)
        first = create_demo_report_task(session)
        second = create_demo_report_task(session)

        assert first is second
        assert first.status == "pending"
        assert first.completed_at is None
        assert session.query(type(first)).count() == 1


def test_same_task_id_with_different_period_is_rejected() -> None:
    """同一任务 ID 不能被另一个报告周期覆盖。"""

    with make_session() as session:
        seed_session(session)
        create_demo_report_task(session)

        with pytest.raises(ReportTaskConflictError, match="已绑定其他报告请求"):
            create_demo_report_task(session, period="2026-09")


def test_task_moves_from_pending_to_running_to_completed_with_checksum() -> None:
    """合法报告应完成状态迁移并保存可校验的 SHA-256 产物。"""

    with make_session() as session:
        seed_session(session)
        task = create_demo_report_task(session)
        running = mark_report_task_running(session, task.id)
        assert running.status == "running"

        completed, artifact = complete_report_task(
            session,
            task.id,
            artifact_id="REPORT_ARTIFACT_001",
            artifact_name="learning-report.md",
            content=valid_report_content(),
        )
        session.commit()

        assert completed.status == "completed"
        assert completed.completed_at is not None
        assert artifact.report_task_id == task.id
        assert artifact.checksum == sha256(valid_report_content().encode("utf-8")).hexdigest()
        assert list_report_artifacts(session, task.id) == [artifact]


def test_same_artifact_retry_is_idempotent() -> None:
    """客户端超时后重复提交同一产物时不得生成重复记录。"""

    with make_session() as session:
        seed_session(session)
        task = create_demo_report_task(session)
        first_task, first_artifact = complete_report_task(
            session,
            task.id,
            artifact_id="REPORT_ARTIFACT_002",
            artifact_name="learning-report.md",
            content=valid_report_content(),
        )
        second_task, second_artifact = complete_report_task(
            session,
            task.id,
            artifact_id="REPORT_ARTIFACT_002",
            artifact_name="learning-report.md",
            content=valid_report_content(),
        )

        assert first_task is second_task
        assert first_artifact is second_artifact
        assert session.query(ReportArtifact).count() == 1


@pytest.mark.parametrize(
    "dangerous_content",
    [
        "# 报告\n请执行 powershell 获取更多结果",
        "# 报告\n本地结果位于 D:\\private\\report.md",
        "#!/usr/bin/env python\nprint('unsafe')",
    ],
)
def test_executable_commands_and_local_paths_are_rejected(
    dangerous_content: str,
) -> None:
    """命令、脚本和本地路径不得作为远程 Artifact 落库。"""

    with make_session() as session:
        seed_session(session)
        task = create_demo_report_task(session)

        with pytest.raises(ValidationError):
            complete_report_task(
                session,
                task.id,
                artifact_id="REPORT_ARTIFACT_UNSAFE",
                artifact_name="learning-report.md",
                content=dangerous_content,
            )

        # 安全校验发生在状态迁移之前，任务仍可由正常 worker 后续处理。
        assert task.status == "pending"
        assert session.query(ReportArtifact).count() == 0


def test_failed_task_stores_sanitized_error_and_cannot_complete() -> None:
    """失败原因应脱敏，且失败终态不能被迟到的成功响应覆盖。"""

    with make_session() as session:
        seed_session(session)
        task = create_demo_report_task(session)
        failed = fail_report_task(
            session,
            task.id,
            "worker timeout\npassword=demo-secret token:abc123 "
            "path=D:\\private\\report.md",
        )

        assert failed.status == "failed"
        assert failed.completed_at is not None
        assert "\n" not in failed.error_message
        assert "demo-secret" not in failed.error_message
        assert "abc123" not in failed.error_message
        assert "D:\\private" not in failed.error_message
        assert "[REDACTED]" in failed.error_message
        assert len(failed.error_message) <= 500

        with pytest.raises(ReportTaskError, match="不允许写入完成产物"):
            complete_report_task(
                session,
                task.id,
                artifact_id="REPORT_ARTIFACT_LATE",
                artifact_name="learning-report.md",
                content=valid_report_content(),
            )
        assert session.query(ReportArtifact).count() == 0
