"""报告任务状态推进和最终产物写入命令。

所有函数只执行当前事务内的数据库变更；是否提交或执行 MinIO 补偿仍由
报告执行工作流负责。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.models import ReportArtifact, ReportTask

from .artifacts import add_report_artifact
from .constants import ALLOWED_TRANSITIONS, ReportTaskStatus
from .exceptions import ReportTaskConflictError, ReportTaskError
from .integrity import (
    content_checksum,
    safe_error_message,
    validate_legacy_markdown_write,
    validate_pdf_write_metadata,
)
from .queries import get_report_task, list_report_artifacts


def create_report_task(
    session: Session,
    *,
    task_id: str,
    requester_id: str,
    task_type: str,
    scope: dict[str, Any],
    metrics: list[str],
    template_version: str | None = None,
) -> ReportTask:
    """创建待执行任务，相同 ID 和相同参数重放时保持幂等。"""

    existing = session.get(ReportTask, task_id)
    if existing is not None:
        same_request = (
            existing.requester_id == requester_id
            and existing.task_type == task_type
            and existing.scope == scope
            and existing.metrics == metrics
            and existing.template_version == template_version
        )
        if not same_request:
            raise ReportTaskConflictError("task_id 已绑定其他报告请求")
        return existing

    task = ReportTask(
        id=task_id,
        requester_id=requester_id,
        task_type=task_type,
        status="pending",
        scope=scope,
        metrics=metrics,
        template_version=template_version,
    )
    session.add(task)
    session.flush()
    return task


def set_report_task_status(
    session: Session,
    task_id: str,
    status: ReportTaskStatus,
    *,
    error_message: str | None = None,
) -> ReportTask:
    """按有限状态机推进状态，同一状态的重复写入保持幂等。"""

    task = get_report_task(session, task_id)
    current = task.status
    if current == status:
        if status == "failed" and error_message and not task.error_message:
            task.error_message = safe_error_message(error_message)
            session.flush()
        return task
    if status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ReportTaskError(f"不允许将报告任务从 {current} 改为 {status}")

    task.status = status
    if status == "failed":
        task.error_message = safe_error_message(error_message or "报告任务执行失败")
    elif status in {"running", "completed", "cancelled"}:
        task.error_message = None
    if status in {"completed", "failed", "cancelled"}:
        task.completed_at = datetime.utcnow()
    session.flush()
    return task


def mark_report_task_running(session: Session, task_id: str) -> ReportTask:
    """将待执行任务推进到 running。"""

    return set_report_task_status(session, task_id, "running")


def claim_pending_report_task(session: Session, task_id: str) -> bool:
    """通过条件 UPDATE 原子取得唯一执行权，防止重复生成和上传报告。"""

    result = session.execute(
        update(ReportTask)
        .where(ReportTask.id == task_id, ReportTask.status == "pending")
        .values(status="running", error_message=None, completed_at=None)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def fail_report_task(
    session: Session, task_id: str, error_message: str
) -> ReportTask:
    """将任务置为失败，并保存脱敏后的有限长度错误说明。"""

    return set_report_task_status(
        session, task_id, "failed", error_message=error_message
    )


def complete_report_task(
    session: Session,
    task_id: str,
    *,
    artifact_id: str,
    artifact_name: str,
    content: str,
) -> tuple[ReportTask, ReportArtifact]:
    """保存历史兼容的 Markdown 产物并完成任务。"""

    task = get_report_task(session, task_id)
    if task.status not in {"pending", "running"}:
        if task.status == "completed":
            existing = _find_artifact(session, task_id, artifact_id)
            if existing is not None and existing.checksum == content_checksum(content):
                return task, existing
        raise ReportTaskError(f"当前任务状态 {task.status} 不允许写入完成产物")

    # 仅用于读取旧数据的兼容命令；新报告执行链路不会调用本函数。
    if not artifact_id:
        raise ReportTaskError("历史 Markdown 产物 ID 不能为空")
    validate_legacy_markdown_write(artifact_name, content)
    if task.status == "pending":
        mark_report_task_running(session, task_id)

    checksum = content_checksum(content)
    existing = _find_artifact(session, task_id, artifact_id)
    if existing is not None:
        if existing.checksum == checksum:
            set_report_task_status(session, task_id, "completed")
            return task, existing
        raise ReportTaskConflictError("Artifact ID 已绑定不同报告内容")

    artifact = add_report_artifact(
        session,
        artifact_id=artifact_id,
        task_id=task_id,
        artifact_type="markdown",
        content=content,
        checksum=checksum,
    )
    set_report_task_status(session, task_id, "completed")
    return task, artifact


def complete_report_task_with_pdf(
    session: Session,
    task_id: str,
    *,
    pdf_artifact_id: str,
    pdf_object_key: str,
    pdf_checksum: str,
    pdf_filename: str,
    pdf_size_bytes: int,
    pdf_page_count: int,
) -> tuple[ReportTask, ReportArtifact]:
    """保存唯一 PDF 元数据并完成任务，二进制由私有存储托管。"""

    task = get_report_task(session, task_id)
    if task.status == "completed":
        existing_pdf = _find_artifact(session, task_id, pdf_artifact_id)
        if (
            existing_pdf is not None
            and existing_pdf.checksum == pdf_checksum
            and existing_pdf.object_key == pdf_object_key
            and len(list_report_artifacts(session, task_id)) == 1
        ):
            return task, existing_pdf
        raise ReportTaskError("已完成任务的报告产物不一致")
    if task.status not in {"pending", "running"}:
        raise ReportTaskError(f"当前任务状态 {task.status} 不允许写入完成产物")

    validate_pdf_write_metadata(
        object_key=pdf_object_key,
        checksum=pdf_checksum,
        filename=pdf_filename,
        size_bytes=pdf_size_bytes,
        page_count=pdf_page_count,
    )
    if list_report_artifacts(session, task_id):
        raise ReportTaskConflictError("报告任务已经存在产物")
    if task.status == "pending":
        mark_report_task_running(session, task_id)

    pdf_artifact = add_report_artifact(
        session,
        artifact_id=pdf_artifact_id,
        task_id=task_id,
        artifact_type="pdf",
        content=None,
        checksum=pdf_checksum,
        object_key=pdf_object_key,
        media_type="application/pdf",
        filename=pdf_filename,
        size_bytes=pdf_size_bytes,
        page_count=pdf_page_count,
    )
    set_report_task_status(session, task_id, "completed")
    return task, pdf_artifact


def _find_artifact(
    session: Session, task_id: str, artifact_id: str
) -> ReportArtifact | None:
    """按任务和产物 ID 联合查询，禁止跨任务复用同名产物。"""

    return (
        session.query(ReportArtifact)
        .filter(
            ReportArtifact.id == artifact_id,
            ReportArtifact.report_task_id == task_id,
        )
        .one_or_none()
    )
