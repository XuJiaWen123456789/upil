"""报告任务的安全 HTTP 响应投影。"""

from datetime import date

from backend.app.models import ReportTask
from backend.app.schemas import (
    ReportArtifactResponse,
    ReportTaskDetailResponse,
    ReportTaskSummaryResponse,
)


def report_scope_date(task: ReportTask, field: str) -> date | None:
    """从任务范围读取 ISO 日期，脏数据按未知处理而不是抛出 500。"""

    if not isinstance(task.scope, dict):
        return None
    value = task.scope.get(field)
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def report_period_type(task: ReportTask) -> str | None:
    """只允许公开契约中的周期类型进入响应。"""

    if not isinstance(task.scope, dict):
        return None
    value = task.scope.get("period_type")
    allowed = {"current_month", "previous_month", "recent_30_days", "custom"}
    return value if isinstance(value, str) and value in allowed else None


def report_status_message(status: str) -> str:
    """把内部状态映射为固定文案，失败时绝不返回异常原文。"""

    messages = {
        "pending": "报告任务等待处理。",
        "running": "报告正在生成，请稍后查看。",
        "completed": "报告已生成。",
        "failed": "报告生成失败，请稍后重新发起。",
        "cancelled": "报告任务已取消。",
    }
    return messages.get(status, "报告状态暂时不可用。")


def report_summary_response(
    task: ReportTask, *, download_available: bool | None = None
) -> ReportTaskSummaryResponse:
    """将 ORM 任务投影为不含内部范围和请求者编号的最小响应。"""

    if download_available is None:
        download_available = task.status == "completed"
    return ReportTaskSummaryResponse(
        task_id=task.id,
        task_type=task.task_type,
        status=task.status,
        period_start=report_scope_date(task, "period_start"),
        period_end=report_scope_date(task, "period_end"),
        period_type=report_period_type(task),
        template_version=task.template_version,
        created_at=task.created_at,
        completed_at=task.completed_at,
        download_available=download_available,
        message=report_status_message(task.status),
    )


def report_detail_response(
    task: ReportTask, artifacts: list, downloadable_artifact_id: str | None
) -> ReportTaskDetailResponse:
    """将任务和产物元数据投影为公共详情响应。"""

    summary = report_summary_response(
        task, download_available=downloadable_artifact_id is not None
    )
    return ReportTaskDetailResponse(
        **summary.model_dump(),
        artifacts=[
            ReportArtifactResponse(
                artifact_id=artifact.id,
                artifact_type=artifact.artifact_type,
                created_at=artifact.created_at,
                download_available=artifact.id == downloadable_artifact_id,
            )
            for artifact in artifacts
        ],
    )
