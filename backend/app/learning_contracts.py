"""学情分析和家长报告的数据契约。

这些模型定义了学情分析智能体可以读取和输出的字段边界。数据库查询结果
先经过契约校验，再交给上层智能体组织自然语言，避免把任意 ORM 对象直接
暴露给模型或接口。
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class LearnerProfile(BaseModel):
    """学员基础资料，只返回客服业务真正需要的脱敏字段。"""

    learner_id: str
    learner_name: str
    active: bool


class AttendanceSummary(BaseModel):
    """指定时间范围内的出勤统计结果。"""

    learner_id: str
    total_lessons: int = Field(ge=0)
    present_lessons: int = Field(ge=0)
    absent_lessons: int = Field(ge=0)
    leave_lessons: int = Field(ge=0)
    attendance_rate: float = Field(ge=0, le=1)
    period_start: date | None = None
    period_end: date | None = None


class LessonBalance(BaseModel):
    """学员课时账户的确定性快照。"""

    learner_id: str
    total_hours: int = Field(ge=0)
    consumed_hours: int = Field(ge=0)
    remaining_hours: int = Field(ge=0)


class ProgressRecord(BaseModel):
    """来自结构化学情资料的阶段进度记录。"""

    learner_id: str
    course_id: str
    course_name: str
    current_stage: str
    completion_rate: float = Field(ge=0, le=1)
    strengths: list[str] = Field(default_factory=list)
    next_focus: list[str] = Field(default_factory=list)
    teacher_note: str
    updated_at: date


class LearningSummary(BaseModel):
    """供学情分析智能体使用的组合摘要。"""

    profile: LearnerProfile
    balance: LessonBalance
    attendance: AttendanceSummary
    progress: list[ProgressRecord] = Field(default_factory=list)


class LearningReportPeriod(BaseModel):
    """家长报告允许使用的明确统计周期。"""

    period_start: date
    period_end: date
    period_label: str = Field(min_length=1, max_length=64)
    # 周期类型用于审计和后续前端筛选，不参与事实计算。
    period_type: Literal["current_month", "previous_month", "recent_30_days", "custom"]

    @classmethod
    def validate_range(cls, values):
        """保留一个简单的兼容入口，实际字段校验由业务服务完成。"""

        return values


class PublishedProgress(BaseModel):
    """可展示给家长的阶段反馈，不包含原始学员标识或内部教师备注。"""

    course_name: str = Field(min_length=1, max_length=100)
    current_stage: str = Field(min_length=1, max_length=100)
    completion_rate: float = Field(ge=0, le=1)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    next_focus: list[str] = Field(default_factory=list, max_length=10)
    updated_at: date


class LearningReportSnapshot(BaseModel):
    """交给报告编排节点的脱敏聚合快照。

    快照不保存姓名、手机号、原始学员 ID、原始出勤明细或内部教师备注，
    只保留完成报告所需的周期、统计指标和已发布阶段反馈。
    """

    schema_version: Literal["learning-report/v1"] = "learning-report/v1"
    report_scope: Literal["parent_self_learner"] = "parent_self_learner"
    learner_ref: str = Field(min_length=3, max_length=128)
    period: LearningReportPeriod
    course_summaries: list[str] = Field(default_factory=list, max_length=20)
    scheduled_sessions: int = Field(ge=0)
    attended_sessions: int = Field(ge=0)
    excused_absences: int = Field(ge=0)
    unexcused_absences: int = Field(ge=0)
    attendance_rate: float = Field(ge=0, le=1)
    completed_lessons: int = Field(ge=0)
    remaining_lessons: int = Field(ge=0)
    published_progress: list[PublishedProgress] = Field(default_factory=list, max_length=20)
