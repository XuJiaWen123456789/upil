"""学情分析任务及 Artifact 产物记录服务。

报表在业务上属于学情分析智能体的输出形式；这里的任务表用于保存任务
生命周期和产物引用，为 A2A 远程任务重放、审计和异步查询提供基础。

本模块只负责业务状态和数据库持久化，不负责调用模型、A2A 网络或 DSH。
这样可以让任务状态在 API 重启后仍然可查询，也便于后续把内存任务仓库
替换为队列或独立 worker，而不改变上层状态契约。
"""

from datetime import datetime
from hashlib import sha256
import re
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend.app.a2a.contracts import A2AArtifact
from backend.app.models import ReportArtifact, ReportTask


ReportTaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class ReportTaskError(ValueError):
    """报告任务状态或产物参数不符合业务约束。"""


class ReportTaskNotFoundError(ReportTaskError):
    """查询或更新的报告任务不存在。"""


class ReportTaskConflictError(ReportTaskError):
    """同一个任务 ID 被不同的业务请求重复使用。"""


# 只允许单向推进任务状态；终态不能被后续请求覆盖，避免重复回写结果。
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "failed", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


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
    """创建一条待执行的分析任务记录，并保持相同 ID 的幂等语义。

    重试时上层会再次提交同一个任务 ID。若任务参数完全一致，直接返回
    已有记录；若参数不同，则抛出冲突，不允许覆盖原任务。
    """

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


def get_report_task(session: Session, task_id: str) -> ReportTask:
    """按任务 ID 获取持久化记录；不存在时统一抛出业务异常。"""

    task = session.get(ReportTask, task_id)
    if task is None:
        raise ReportTaskNotFoundError("报告任务不存在")
    return task


def set_report_task_status(
    session: Session,
    task_id: str,
    status: ReportTaskStatus,
    *,
    error_message: str | None = None,
) -> ReportTask:
    """按有限状态机推进任务状态，重复写入同一状态保持幂等。"""

    task = get_report_task(session, task_id)
    current = task.status
    if current == status:
        # 重试请求可能重复提交 running 或 failed；不重复改变完成时间。
        if status == "failed" and error_message and not task.error_message:
            task.error_message = _safe_error_message(error_message)
            session.flush()
        return task
    if status not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ReportTaskError(f"不允许将报告任务从 {current} 改为 {status}")

    task.status = status
    if status == "failed":
        task.error_message = _safe_error_message(error_message or "报告任务执行失败")
    elif status in {"running", "completed", "cancelled"}:
        # running 和成功完成时不保留前一次失败描述，防止查询端误判状态。
        task.error_message = None
    if status in {"completed", "failed", "cancelled"}:
        task.completed_at = datetime.utcnow()
    session.flush()
    return task


def mark_report_task_running(session: Session, task_id: str) -> ReportTask:
    """将待执行任务置为 running。"""

    return set_report_task_status(session, task_id, "running")


def fail_report_task(
    session: Session,
    task_id: str,
    error_message: str,
) -> ReportTask:
    """将任务置为失败，并保存脱敏后的有限长度错误说明。"""

    return set_report_task_status(
        session,
        task_id,
        "failed",
        error_message=error_message,
    )


def add_report_artifact(
    session: Session,
    *,
    artifact_id: str,
    task_id: str,
    artifact_type: str,
    content: str,
    checksum: str | None = None,
) -> ReportArtifact:
    """将分析结果或执行轨迹作为任务产物保存。"""

    artifact = ReportArtifact(
        id=artifact_id,
        report_task_id=task_id,
        artifact_type=artifact_type,
        content=content,
        checksum=checksum,
    )
    session.add(artifact)
    session.flush()
    return artifact


def complete_report_task(
    session: Session,
    task_id: str,
    *,
    artifact_id: str,
    artifact_name: str,
    content: str,
) -> tuple[ReportTask, ReportArtifact]:
    """以一个经过安全校验的 Markdown Artifact 完成报告任务。

    远程节点返回的内容必须先通过 A2AArtifact 契约；代码、命令、本地路径
    和过大的正文会在落库前被拒绝。相同 Artifact 重复提交时返回已有记录，
    便于处理客户端超时后的幂等重试。
    """

    task = get_report_task(session, task_id)
    if task.status not in {"pending", "running"}:
        if task.status == "completed":
            existing = _find_artifact(session, task_id, artifact_id)
            if existing is not None and existing.checksum == _content_checksum(content):
                return task, existing
        raise ReportTaskError(f"当前任务状态 {task.status} 不允许写入完成产物")

    # 使用与 A2A 结果复核相同的 Artifact 合同，避免持久化层出现更宽的安全口径。
    # 先校验再推进状态，危险产物被拒绝时不会把 pending 任务误改成 running。
    validated = A2AArtifact(
        artifact_id=artifact_id,
        media_type="text/markdown",
        name=artifact_name,
        content_ref=f"artifact://{artifact_id}",
        content=content,
    )

    # 处于 pending 的任务先进入 running，再进入 completed，保持状态机可观测。
    if task.status == "pending":
        mark_report_task_running(session, task_id)

    checksum = _content_checksum(validated.content)
    existing = _find_artifact(session, task_id, validated.artifact_id)
    if existing is not None:
        if existing.checksum == checksum:
            set_report_task_status(session, task_id, "completed")
            return task, existing
        raise ReportTaskConflictError("Artifact ID 已绑定不同报告内容")

    artifact = add_report_artifact(
        session,
        artifact_id=validated.artifact_id,
        task_id=task_id,
        artifact_type="markdown",
        content=validated.content,
        checksum=checksum,
    )
    set_report_task_status(session, task_id, "completed")
    return task, artifact


def list_report_artifacts(session: Session, task_id: str) -> list[ReportArtifact]:
    """返回任务产物；先校验任务存在，避免用查询差异泄露任务信息。"""

    get_report_task(session, task_id)
    return list(
        session.query(ReportArtifact)
        .filter(ReportArtifact.report_task_id == task_id)
        .order_by(ReportArtifact.created_at.asc(), ReportArtifact.id.asc())
        .all()
    )


def _find_artifact(
    session: Session,
    task_id: str,
    artifact_id: str,
) -> ReportArtifact | None:
    """按任务和产物 ID 查询，防止跨任务复用同名产物。"""

    return (
        session.query(ReportArtifact)
        .filter(
            ReportArtifact.id == artifact_id,
            ReportArtifact.report_task_id == task_id,
        )
        .one_or_none()
    )


def _content_checksum(content: str) -> str:
    """使用 SHA-256 生成正文校验和，便于幂等比对和审计。"""

    return sha256(content.encode("utf-8")).hexdigest()


def _safe_error_message(message: str) -> str:
    """错误信息只保存单行有限长度文本，不保存远程响应正文或请求快照。"""

    safe_message = " ".join(message.split())

    # 对常见凭据格式做最后一道脱敏，防止下游异常对象把密钥带入任务表。
    safe_message = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret)"
        r"\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        safe_message,
    )
    safe_message = re.sub(
        r"(?i)\bbearer\s+[^\s,;]+",
        "Bearer [REDACTED]",
        safe_message,
    )

    # 本地绝对路径与远程服务内部目录不属于业务错误信息，统一替换。
    safe_message = re.sub(
        r"(?i)\b[A-Z]:\\[^\s,;]+",
        "[REDACTED_PATH]",
        safe_message,
    )
    safe_message = re.sub(
        r"(?<!:)\/(?:home|tmp|var|opt|root|Users)\/[^\s,;]+",
        "[REDACTED_PATH]",
        safe_message,
        flags=re.IGNORECASE,
    )
    return safe_message[:500]
