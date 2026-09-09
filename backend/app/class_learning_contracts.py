"""班级级学情分析的数据契约。

本模块只描述经过授权和确定性计算后的班级统计结果，不负责查询数据库、
调用大模型或执行远程任务。后续 A2A/DSH 报表节点只能接收脱敏后的聚合
结果，不能直接接触本模块对应的 ORM 查询对象。

契约的意义是把“统计口径”和“数据结构”固定下来：数据库查询可以演进，
报告模板可以替换，但下游不能随意改变完课率、出勤率和缺勤统计的含义。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClassLearnerMetric(BaseModel):
    """班级内单名学员的统计指标。

    该模型服务于已授权的教师或管理员内部查询；发送给远程报表节点前，
    应将 learner_id 和 learner_name 替换为不可逆的匿名引用或掩码。
    """

    # 额外字段一律拒绝，防止把不必要的手机号、联系方式等隐私字段带入
    # 班级统计结果，更防止下游误以为这些字段也是可展示的业务指标。
    model_config = ConfigDict(extra="forbid")

    learner_id: str = Field(min_length=1, max_length=64)
    learner_name: str = Field(min_length=1, max_length=100)
    scheduled_lessons: int = Field(ge=0)
    marked_lessons: int = Field(ge=0)
    attended_lessons: int = Field(ge=0)
    absent_lessons: int = Field(ge=0)
    excused_lessons: int = Field(ge=0)
    unmarked_lessons: int = Field(ge=0)
    completion_rate: float = Field(ge=0, le=1)
    attendance_rate: float = Field(ge=0, le=1)
    remaining_hours: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "ClassLearnerMetric":
        """确保单名学员各类课次不会超过统计周期内的计划课次。"""

        if self.marked_lessons + self.unmarked_lessons != self.scheduled_lessons:
            raise ValueError("marked_lessons 与 unmarked_lessons 必须合计为 scheduled_lessons")
        if self.attended_lessons + self.absent_lessons + self.excused_lessons != self.marked_lessons:
            raise ValueError("出勤、缺勤和请假课次必须合计为已登记课次")
        return self


class ClassLearningSummary(BaseModel):
    """经过权限校验后的班级学情汇总结果。

    该模型仍可能包含单名学员的内部统计行，因此返回给 A2A/DSH 前必须
    按调用场景进行匿名化；“已经通过 Pydantic 校验”不等于“可以直接外发”。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["class-learning/v1"] = "class-learning/v1"
    class_id: str = Field(min_length=1, max_length=64)
    class_name: str = Field(min_length=1, max_length=100)
    course_name: str = Field(min_length=1, max_length=100)
    campus_name: str = Field(min_length=1, max_length=100)
    period_start: date
    period_end: date
    scheduled_lessons: int = Field(ge=0)
    enrolled_learners: int = Field(ge=0)
    expected_attendance_records: int = Field(ge=0)
    marked_attendance_records: int = Field(ge=0)
    attended_records: int = Field(ge=0)
    absent_records: int = Field(ge=0)
    excused_records: int = Field(ge=0)
    unmarked_records: int = Field(ge=0)
    completion_rate: float = Field(ge=0, le=1)
    attendance_rate: float = Field(ge=0, le=1)
    low_balance_threshold: int = Field(ge=0, le=10000)
    missing_hour_accounts: int = Field(ge=0)
    # 三组名单服务于不同消费方：完整内部明细、缺勤排行和低课时运营提醒。
    # 生产外发前不应无差别发送完整 learner_metrics。
    learner_metrics: list[ClassLearnerMetric] = Field(default_factory=list, max_length=1000)
    absence_top5: list[ClassLearnerMetric] = Field(default_factory=list, max_length=5)
    low_balance_learners: list[ClassLearnerMetric] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def summary_counts_are_consistent(self) -> "ClassLearningSummary":
        """校验班级统计总数和名单规模，阻止明显错误数据继续流转。"""

        if self.period_start > self.period_end:
            raise ValueError("统计开始日期不能晚于结束日期")
        expected = self.scheduled_lessons * self.enrolled_learners
        if self.expected_attendance_records != expected:
            raise ValueError("expected_attendance_records 与班级计划课次不一致")
        if self.marked_attendance_records + self.unmarked_records != self.expected_attendance_records:
            raise ValueError("已登记和未登记考勤记录必须合计为应登记记录")
        if self.attended_records + self.absent_records + self.excused_records != self.marked_attendance_records:
            raise ValueError("出勤、缺勤和请假记录必须合计为已登记记录")
        if len(self.learner_metrics) != self.enrolled_learners:
            raise ValueError("learner_metrics 必须覆盖全部有效报名学员")
        return self
