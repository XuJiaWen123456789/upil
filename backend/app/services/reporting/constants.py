"""报告任务类型和状态机常量。

常量单独维护，避免查询、命令和 HTTP 层分别复制任务类型字符串。
"""

from typing import Literal


ReportTaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]

# 家长与教师报告共用生命周期，但业务类型必须始终分开授权。
PARENT_LEARNING_REPORT = "parent_learning_report"
TEACHER_CLASS_LEARNING_REPORT = "teacher_class_learning_report"
REPORT_TASK_TYPES = frozenset(
    {PARENT_LEARNING_REPORT, TEACHER_CLASS_LEARNING_REPORT}
)

# 终态不可逆，防止迟到的 worker 响应覆盖已经确定的业务结果。
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "failed", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}
