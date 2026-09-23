"""报告任务服务的历史兼容门面。

实现已按命令、查询、产物和完整性校验拆到 ``services.reporting``。保留本
模块是为了兼容现有部署代码、测试导入和渐进迁移，不在这里新增业务逻辑。
"""

from backend.app.services.reporting import (
    PARENT_LEARNING_REPORT,
    REPORT_TASK_TYPES,
    TEACHER_CLASS_LEARNING_REPORT,
    ReportArtifactIntegrityError,
    ReportArtifactNotReadyError,
    ReportTaskConflictError,
    ReportTaskError,
    ReportTaskNotFoundError,
    ReportTaskStatus,
    add_report_artifact,
    claim_pending_report_task,
    complete_report_task,
    complete_report_task_with_pdf,
    create_report_task,
    fail_report_task,
    get_downloadable_report_artifact,
    get_owned_report_artifacts,
    get_owned_report_task,
    get_report_task,
    get_requester_report_artifacts,
    get_requester_report_task,
    list_class_report_tasks,
    list_report_artifacts,
    list_requester_report_tasks,
    mark_report_task_running,
    set_report_task_status,
)

__all__ = [name for name in globals() if not name.startswith("_")]
