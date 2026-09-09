"""uPil 学情分析子节点使用的最小 A2A 任务合同。

本模块只定义可验证的数据边界，不负责网络传输，也不实现真正的代码执行。
阶段 13-B 使用本地 Mock 节点验证任务生命周期；后续接入真实协议时，可以
复用这些字段约束，而不必让远程节点获得数据库或真实身份数据。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


# ID 只能包含可审计的 ASCII 字符，禁止把姓名、手机号或自然语言问题塞进 ID。
SafeId = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]

# 指标名称是跨智能体共享的白名单；新增报告能力时复用旧指标，避免让
# 远程节点通过任意字符串表达未授权的数据字段。
MetricName = Literal[
    "attendance_rate",
    "completed_hours",
    "progress_notes",
    "attendance_breakdown",
    "lesson_balance",
    "published_progress",
]
TaskSkill = Literal["learning_summary", "learning_report", "class_learning_report"]
TaskStatus = Literal["working", "completed", "failed", "cancelled"]
ProtocolVersion = Literal["upil-a2a/1.0"]


class StrictModel(BaseModel):
    """所有协议模型统一拒绝未知字段，避免字段注入进入子节点。"""

    model_config = ConfigDict(extra="forbid")


class LearningAnalysisInput(StrictModel):
    """脱敏后的学情分析输入，不包含真实姓名、联系方式或完整聊天记录。"""

    learner_ref: SafeId
    period: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    metrics: list[MetricName] = Field(min_length=1, max_length=3)
    attendance_rate: float = Field(ge=0, le=1)
    completed_hours: int = Field(ge=0, le=10000)
    progress_notes: list[
        Annotated[str, StringConstraints(min_length=1, max_length=200)]
    ] = Field(default_factory=list, max_length=20)

    @field_validator("metrics")
    @classmethod
    def metrics_must_be_unique(cls, value: list[MetricName]) -> list[MetricName]:
        """防止重复指标造成下游统计语义不明确。"""

        if len(value) != len(set(value)):
            raise ValueError("metrics 中不能包含重复指标")
        return value


class LearningReportInput(StrictModel):
    """家长学情报告的脱敏聚合输入。

    报告节点只接收后端已经核验和计算后的统计结果，不接收原始出勤明细、
    学员姓名、联系方式、教师内部备注或任何可执行脚本。日期和统计数字由
    主系统确定，远程节点只负责按照固定模板组织报告表达。
    """

    learner_ref: SafeId
    period_start: date
    period_end: date
    period_label: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    period_type: Literal[
        "current_month",
        "previous_month",
        "recent_30_days",
        "custom",
    ]
    metrics: list[MetricName] = Field(min_length=1, max_length=6)
    scheduled_sessions: int = Field(ge=0, le=10000)
    attended_sessions: int = Field(ge=0, le=10000)
    excused_absences: int = Field(ge=0, le=10000)
    unexcused_absences: int = Field(ge=0, le=10000)
    attendance_rate: float = Field(ge=0, le=1)
    completed_lessons: int = Field(ge=0, le=10000)
    remaining_lessons: int = Field(ge=0, le=10000)
    course_summaries: list[
        Annotated[str, StringConstraints(min_length=1, max_length=300)]
    ] = Field(default_factory=list, max_length=20)
    published_progress: list[
        Annotated[str, StringConstraints(min_length=1, max_length=300)]
    ] = Field(default_factory=list, max_length=20)

    @field_validator("metrics")
    @classmethod
    def report_metrics_must_be_unique(cls, value: list[MetricName]) -> list[MetricName]:
        """拒绝重复指标，避免报告模板出现重复段落或重复统计口径。"""

        if len(value) != len(set(value)):
            raise ValueError("报告 metrics 中不能包含重复指标")
        return value

    @field_validator(
        "attended_sessions",
        "excused_absences",
        "unexcused_absences",
    )
    @classmethod
    def session_counts_cannot_exceed_schedule(cls, value: int, info) -> int:
        """限制单项课次数量，防止远程报告节点接收明显不合理的统计值。"""

        scheduled = info.data.get("scheduled_sessions")
        if scheduled is not None and value > scheduled:
            raise ValueError("出勤或缺勤课次数不能超过应上课次数")
        return value

    @model_validator(mode="after")
    def session_counts_are_consistent(self) -> "LearningReportInput":
        """校验同一周期内各类课次合计不能超过应上课次数。"""

        classified_sessions = (
            self.attended_sessions
            + self.excused_absences
            + self.unexcused_absences
        )
        if classified_sessions > self.scheduled_sessions:
            raise ValueError("出勤、请假和缺勤课次数合计不能超过应上课次数")
        return self


class ClassLearningReportInput(StrictModel):
    """班级学情报表的脱敏聚合输入。

    该输入由主系统在完成角色、班级范围和统计周期校验后生成。它只包含
    班级级汇总指标和匿名缺勤排行，不包含学员姓名、手机号、原始 learner ID、
    原始考勤明细、SQL、脚本或文件路径；远程节点只负责固定模板排版。
    """

    class_ref: SafeId
    course_name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    campus_ref: SafeId
    period_start: date
    period_end: date
    period_label: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    enrolled_learners: int = Field(ge=0, le=10000)
    scheduled_lessons: int = Field(ge=0, le=10000)
    expected_attendance_records: int = Field(ge=0, le=1000000)
    marked_attendance_records: int = Field(ge=0, le=1000000)
    attended_records: int = Field(ge=0, le=1000000)
    absent_records: int = Field(ge=0, le=1000000)
    excused_records: int = Field(ge=0, le=1000000)
    unmarked_records: int = Field(ge=0, le=1000000)
    completion_rate: float = Field(ge=0, le=1)
    attendance_rate: float = Field(ge=0, le=1)
    low_balance_threshold: int = Field(ge=0, le=10000)
    absence_top5: list[
        Annotated[str, StringConstraints(min_length=1, max_length=100)]
    ] = Field(default_factory=list, max_length=5)
    low_balance_learner_count: int = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def report_counts_are_consistent(self) -> "ClassLearningReportInput":
        """在进入远程节点前复核日期、课次和考勤分母关系。"""

        if self.period_start > self.period_end:
            raise ValueError("班级报表统计开始日期不能晚于结束日期")
        if self.expected_attendance_records != self.scheduled_lessons * self.enrolled_learners:
            raise ValueError("应登记考勤数与班级课次和人数不一致")
        if self.marked_attendance_records + self.unmarked_records != self.expected_attendance_records:
            raise ValueError("已登记和未登记考勤数不一致")
        if self.attended_records + self.absent_records + self.excused_records != self.marked_attendance_records:
            raise ValueError("出勤、缺勤和请假数不一致")
        if self.absent_records == 0 and self.absence_top5:
            raise ValueError("没有缺勤记录时不能返回缺勤排行")
        return self


class A2ATaskConstraints(StrictModel):
    """远程任务的最小安全约束；两个安全开关必须保持为 true。"""

    max_runtime_seconds: int = Field(gt=0, le=60)
    output_format: Literal["markdown_report"]
    # Literal[True] 让调用方无法关闭安全边界。
    no_external_network: Literal[True]
    no_side_effects: Literal[True]


class A2ATaskRequest(StrictModel):
    """发送给学情摘要或学情报告子节点的最小任务体。"""

    protocol_version: ProtocolVersion = "upil-a2a/1.0"
    task_id: SafeId
    parent_task_id: SafeId | None = None
    correlation_id: SafeId
    skill: TaskSkill
    # 两种输入模型都拒绝未知字段，且字段集合不同，Pydantic 会在边界处
    # 自动区分摘要任务和报告任务，不把任意 JSON 透传给远程服务。
    input: LearningAnalysisInput | LearningReportInput | ClassLearningReportInput
    constraints: A2ATaskConstraints


class A2AArtifact(StrictModel):
    """子节点产出的可审计结果，不允许返回脚本或本地文件路径。"""

    artifact_id: SafeId
    media_type: Literal["text/markdown"]
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    content_ref: Annotated[
        str,
        StringConstraints(
            min_length=12,
            max_length=160,
            pattern=r"^artifact://[A-Za-z0-9_.:-]+$",
        ),
    ]
    content: Annotated[str, StringConstraints(min_length=1, max_length=12000)]

    @field_validator("content", "name")
    @classmethod
    def reject_executable_or_local_content(cls, value: str) -> str:
        """拒绝 shell、Python 代码和 Windows/Linux 本地路径等危险产物。"""

        lowered = value.lower()
        forbidden = ("#!/", "import os", "subprocess", "powershell", "cmd.exe")
        if any(token in lowered for token in forbidden):
            raise ValueError("Artifact 不得包含可执行代码或命令")
        backslash = chr(92)
        if backslash in value or lowered.startswith(("/", "c:", "d:")):
            raise ValueError("Artifact 不得暴露本地文件路径")
        return value


class A2AQualityResult(StrictModel):
    """主系统对远程结果执行的最小质量校验结果。"""

    passed: bool
    issues: list[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = Field(
        default_factory=list,
        max_length=10,
    )
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class A2ATaskResult(StrictModel):
    """A2A 任务结果；失败结果必须明确是否需要人工兜底。"""

    protocol_version: ProtocolVersion = "upil-a2a/1.0"
    task_id: SafeId
    correlation_id: SafeId
    status: TaskStatus
    message: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    artifacts: list[A2AArtifact] = Field(default_factory=list, max_length=5)
    quality: A2AQualityResult | None = None
    handoff_required: bool = False
    retryable: bool = False

    @field_validator("artifacts")
    @classmethod
    def artifact_ids_must_be_unique(cls, value: list[A2AArtifact]) -> list[A2AArtifact]:
        """避免同一任务返回重复产物，便于审计和前端展示。"""

        ids = [artifact.artifact_id for artifact in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Artifact ID 必须唯一")
        return value
