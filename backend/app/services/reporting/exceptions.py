"""报告任务领域异常。

HTTP 层只依赖这些稳定异常，不感知数据库或对象存储实现细节。
"""


class ReportTaskError(ValueError):
    """报告任务状态或产物参数不符合业务约束。"""


class ReportTaskNotFoundError(ReportTaskError):
    """查询或更新的报告任务不存在。"""


class ReportTaskConflictError(ReportTaskError):
    """同一个任务或产物 ID 已绑定不同业务请求。"""


class ReportArtifactNotReadyError(ReportTaskError):
    """报告任务尚未形成可下载的最终产物。"""


class ReportArtifactIntegrityError(ReportTaskError):
    """报告产物数量、类型、内容或校验和不满足下载要求。"""
