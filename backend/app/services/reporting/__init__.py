"""报告任务领域服务的公开接口。

调用方可从本包导入；旧的 ``services.report_tasks`` 仍作为兼容门面存在。
"""

from .artifacts import add_report_artifact
from .commands import (
    claim_pending_report_task,
    complete_report_task,
    complete_report_task_with_pdf,
    create_report_task,
    fail_report_task,
    mark_report_task_running,
    set_report_task_status,
)
from .constants import (
    PARENT_LEARNING_REPORT,
    REPORT_TASK_TYPES,
    TEACHER_CLASS_LEARNING_REPORT,
    ReportTaskStatus,
)
from .exceptions import (
    ReportArtifactIntegrityError,
    ReportArtifactNotReadyError,
    ReportTaskConflictError,
    ReportTaskError,
    ReportTaskNotFoundError,
)
from .queries import (
    get_downloadable_report_artifact,
    get_owned_report_artifacts,
    get_owned_report_task,
    get_report_task,
    get_requester_report_artifacts,
    get_requester_report_task,
    list_class_report_tasks,
    list_report_artifacts,
    list_requester_report_tasks,
)

__all__ = [
    "PARENT_LEARNING_REPORT",
    "REPORT_TASK_TYPES",
    "TEACHER_CLASS_LEARNING_REPORT",
    "ReportArtifactIntegrityError",
    "ReportArtifactNotReadyError",
    "ReportTaskConflictError",
    "ReportTaskError",
    "ReportTaskNotFoundError",
    "ReportTaskStatus",
    "add_report_artifact",
    "claim_pending_report_task",
    "complete_report_task",
    "complete_report_task_with_pdf",
    "create_report_task",
    "fail_report_task",
    "get_downloadable_report_artifact",
    "get_owned_report_artifacts",
    "get_owned_report_task",
    "get_report_task",
    "get_requester_report_artifacts",
    "get_requester_report_task",
    "list_class_report_tasks",
    "list_report_artifacts",
    "list_requester_report_tasks",
    "mark_report_task_running",
    "set_report_task_status",
]
