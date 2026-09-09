"""uPil 学情分析 A2A 客户端的共享任务构造与本地 Mock 实现。"""

from __future__ import annotations

import hashlib
from typing import Protocol
from uuid import uuid4

from backend.app.a2a.contracts import (
    A2AQualityResult,
    A2ATaskConstraints,
    A2ATaskRequest,
    A2ATaskResult,
    ClassLearningReportInput,
    LearningAnalysisInput,
    LearningReportInput,
)
from backend.app.a2a.mock_learning_agent import MockA2ATimeoutError, MockLearningAnalysisAgent
from backend.app.learning_contracts import LearningReportSnapshot, LearningSummary
from backend.app.class_learning_contracts import ClassLearningSummary


class A2AResultValidationError(ValueError):
    """远程结果未通过安全和完整性检查。"""


class A2ALearningClient(Protocol):
    """LangGraph 依赖的最小客户端接口，便于 Mock 与 HTTP 实现互换。"""

    provider: str

    def analyze(self, snapshot: LearningSummary, *, request_id: str) -> A2ATaskResult:
        """分析经过授权的结构化快照，并返回严格 A2A 结果。"""
        ...

    def generate_report(
        self, snapshot: LearningReportSnapshot, *, request_id: str
    ) -> A2ATaskResult:
        """根据已授权报告快照生成固定格式的学情报告。"""
        ...

    def generate_class_report(
        self, snapshot: ClassLearningSummary, *, request_id: str
    ) -> A2ATaskResult:
        """根据已授权的班级聚合结果生成班级运营报表。"""
        ...


def build_learning_task(
    snapshot: LearningSummary,
    *,
    request_id: str,
    timeout_seconds: int,
) -> A2ATaskRequest:
    """构造最小化、脱敏的学情任务，不向子节点发送姓名和内部编号。"""

    learner_digest = hashlib.sha256(snapshot.profile.learner_id.encode("utf-8")).hexdigest()[:16]
    progress_notes: list[str] = []
    for record in snapshot.progress:
        progress_notes.extend(record.strengths[:2])
        progress_notes.extend(record.next_focus[:2])
    payload = LearningAnalysisInput(
        learner_ref=f"learner_ref_{learner_digest}",
        period="recent_30_days",
        metrics=["attendance_rate", "completed_hours", "progress_notes"],
        attendance_rate=snapshot.attendance.attendance_rate,
        completed_hours=snapshot.balance.consumed_hours,
        progress_notes=progress_notes[:20],
    )
    return A2ATaskRequest(
        task_id=f"task_{uuid4().hex}",
        correlation_id=request_id,
        skill="learning_summary",
        input=payload,
        constraints=A2ATaskConstraints(
            max_runtime_seconds=timeout_seconds,
            output_format="markdown_report",
            no_external_network=True,
            no_side_effects=True,
        ),
    )


def build_learning_report_task(
    snapshot: LearningReportSnapshot,
    *,
    request_id: str,
    timeout_seconds: int,
) -> A2ATaskRequest:
    """将主服务生成的报告快照转换为最小化的报告 A2A 任务。

    快照已经完成权限校验和脱敏，这里只做协议映射，不重新查询数据库，也不把
    原始学员编号、姓名、教师内部备注或出勤明细发送给远程节点。
    """

    published_progress: list[str] = []
    for item in snapshot.published_progress:
        strengths = "、".join(item.strengths[:3]) or "暂无"
        next_focus = "、".join(item.next_focus[:3]) or "暂无"
        published_progress.append(
            f"课程：{item.course_name}；阶段：{item.current_stage}；"
            f"完成度：{item.completion_rate:.0%}；优势：{strengths}；下一步：{next_focus}"
        )

    payload = LearningReportInput(
        learner_ref=snapshot.learner_ref,
        period_start=snapshot.period.period_start,
        period_end=snapshot.period.period_end,
        period_label=snapshot.period.period_label,
        period_type=snapshot.period.period_type,
        metrics=[
            "attendance_rate",
            "attendance_breakdown",
            "lesson_balance",
            "published_progress",
        ],
        scheduled_sessions=snapshot.scheduled_sessions,
        attended_sessions=snapshot.attended_sessions,
        excused_absences=snapshot.excused_absences,
        unexcused_absences=snapshot.unexcused_absences,
        attendance_rate=snapshot.attendance_rate,
        completed_lessons=snapshot.completed_lessons,
        remaining_lessons=snapshot.remaining_lessons,
        course_summaries=snapshot.course_summaries,
        published_progress=published_progress,
    )
    return A2ATaskRequest(
        task_id=f"task_{uuid4().hex}",
        correlation_id=request_id,
        skill="learning_report",
        input=payload,
        constraints=A2ATaskConstraints(
            max_runtime_seconds=timeout_seconds,
            output_format="markdown_report",
            no_external_network=True,
            no_side_effects=True,
        ),
    )


def _stable_private_ref(prefix: str, value: str) -> str:
    """把内部范围标识转换成稳定的不可逆引用。

    班级和校区是报表范围所必需的业务维度，但远程节点没有必要知道主库的
    原始 ID。使用带前缀的短摘要既能在审计日志中关联同一范围，又避免将
    数据库主键直接扩散到 A2A 边界。
    """

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def build_class_learning_report_task(
    snapshot: ClassLearningSummary,
    *,
    request_id: str,
    timeout_seconds: int,
) -> A2ATaskRequest:
    """构造班级报表任务，并在发送前完成最小化脱敏。

    `ClassLearningSummary` 可能包含内部用途的 learner_metrics、姓名和原始
    学员编号；这些字段只服务于主系统授权查询和确定性统计，绝不能整体
    `model_dump` 后发送给远程节点。这里只发送：

    - 班级/校区的不可逆范围引用；
    - 课程名称和统计周期；
    - 主系统已经计算好的汇总指标；
    - 仅带序号和次数的匿名缺勤 TOP5；
    - 低课时人数，而不是低课时学员名单。
    """

    # 排名顺序已经由数据库工具固定为“缺勤次数降序、学员编号升序”。
    # 这里不重新排序、不接收姓名，只把已有顺序映射为匿名序号。
    absence_top5 = [
        f"学员-{rank:02d}：缺勤 {metric.absent_lessons} 次"
        for rank, metric in enumerate(snapshot.absence_top5, start=1)
    ]
    payload = ClassLearningReportInput(
        class_ref=_stable_private_ref("class_ref", snapshot.class_id),
        course_name=snapshot.course_name,
        # 当前汇总契约只保留校区名称，因此使用名称生成稳定引用；不把内部
        # Campus 主键暴露给远程节点。后续若契约增加 campus_id，可直接替换。
        campus_ref=_stable_private_ref("campus_ref", snapshot.campus_name),
        period_start=snapshot.period_start,
        period_end=snapshot.period_end,
        period_label=f"{snapshot.period_start} 至 {snapshot.period_end}",
        enrolled_learners=snapshot.enrolled_learners,
        scheduled_lessons=snapshot.scheduled_lessons,
        expected_attendance_records=snapshot.expected_attendance_records,
        marked_attendance_records=snapshot.marked_attendance_records,
        attended_records=snapshot.attended_records,
        absent_records=snapshot.absent_records,
        excused_records=snapshot.excused_records,
        unmarked_records=snapshot.unmarked_records,
        completion_rate=snapshot.completion_rate,
        attendance_rate=snapshot.attendance_rate,
        low_balance_threshold=snapshot.low_balance_threshold,
        absence_top5=absence_top5,
        low_balance_learner_count=len(snapshot.low_balance_learners),
    )
    return A2ATaskRequest(
        task_id=f"task_{uuid4().hex}",
        correlation_id=request_id,
        skill="class_learning_report",
        input=payload,
        constraints=A2ATaskConstraints(
            max_runtime_seconds=timeout_seconds,
            output_format="markdown_report",
            no_external_network=True,
            no_side_effects=True,
        ),
    )


def validate_a2a_result(result: A2ATaskResult, task: A2ATaskRequest) -> A2ATaskResult:
    """在主系统复核协议版本、任务关联、状态和产物内容安全性。"""

    if result.protocol_version != task.protocol_version:
        raise A2AResultValidationError("A2A 协议版本不一致")
    if result.task_id != task.task_id or result.correlation_id != task.correlation_id:
        raise A2AResultValidationError("任务关联 ID 不一致")
    if result.status == "failed":
        if not result.handoff_required or result.artifacts:
            raise A2AResultValidationError("失败任务的兜底状态不正确")
        return result
    if result.status != "completed" or len(result.artifacts) != 1:
        raise A2AResultValidationError("任务没有返回唯一的完成产物")
    artifact = result.artifacts[0]
    if artifact.media_type != "text/markdown" or not artifact.content_ref.startswith("artifact://"):
        raise A2AResultValidationError("产物格式或引用不符合要求")
    lowered = artifact.content.lower()
    if any(token in lowered for token in ("#!/", "subprocess", "powershell", "cmd.exe")):
        raise A2AResultValidationError("产物包含可执行内容")
    local_paths = ("d:" + chr(92), "c:" + chr(92), "/etc/", "/var/")
    if any(token in lowered for token in local_paths):
        raise A2AResultValidationError("产物暴露了本地路径")
    return result


class LocalMockA2AClient:
    """本地演示客户端，模拟主系统对远程 A2A 子节点的调度与降级。"""

    def __init__(
        self,
        agent: MockLearningAnalysisAgent | None = None,
        *,
        max_retries: int = 2,
        timeout_seconds: int = 10,
    ) -> None:
        if max_retries < 0 or max_retries > 2:
            raise ValueError("本阶段最多允许 2 次重试")
        self.agent = agent or MockLearningAnalysisAgent()
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    def analyze(
        self,
        snapshot: LearningSummary,
        *,
        request_id: str,
        behavior: str = "success",
    ) -> A2ATaskResult:
        """将本地学情快照脱敏后提交给 Mock 节点，并执行有限重试。"""

        task = build_learning_task(
            snapshot, request_id=request_id, timeout_seconds=self.timeout_seconds
        )
        return self._execute_task(task, behavior=behavior)

    def generate_report(
        self,
        snapshot: LearningReportSnapshot,
        *,
        request_id: str,
        behavior: str = "success",
    ) -> A2ATaskResult:
        """提交报告任务；报告和摘要共用相同的重试、校验和降级策略。"""

        task = build_learning_report_task(
            snapshot, request_id=request_id, timeout_seconds=self.timeout_seconds
        )
        return self._execute_task(task, behavior=behavior)

    def generate_class_report(
        self,
        snapshot: ClassLearningSummary,
        *,
        request_id: str,
        behavior: str = "success",
    ) -> A2ATaskResult:
        """提交班级学情报表任务，并复用统一的重试、校验和降级策略。"""

        task = build_class_learning_report_task(
            snapshot, request_id=request_id, timeout_seconds=self.timeout_seconds
        )
        return self._execute_task(task, behavior=behavior)

    def _execute_task(self, task: A2ATaskRequest, *, behavior: str) -> A2ATaskResult:
        """执行一个已经构造好的任务，并统一处理有限重试和安全校验。"""

        attempts = 0
        while True:
            attempts += 1
            try:
                result = self.agent.process(task, behavior=behavior)
                validated = validate_a2a_result(result, task)
                # 质量校验在主系统完成，远程节点不能自行宣称结果可信。
                if validated.status == "failed":
                    return validated.model_copy(
                        update={
                            "quality": A2AQualityResult(
                                passed=False,
                                issues=["远程子节点返回失败状态"],
                            )
                        }
                    )
                return validated.model_copy(
                    update={"quality": A2AQualityResult(passed=True, issues=[])}
                )
            except MockA2ATimeoutError:
                if attempts > self.max_retries:
                    return A2ATaskResult(
                        task_id=task.task_id,
                        correlation_id=task.correlation_id,
                        status="failed",
                        message="学情分析服务暂时不可用，已达到重试上限",
                        handoff_required=True,
                        retryable=False,
                    )
                # 只对明确的超时错误重试，业务失败和结果校验失败不重试。
            except A2AResultValidationError:
                return A2ATaskResult(
                    task_id=task.task_id,
                    correlation_id=task.correlation_id,
                    status="failed",
                    message="学情分析结果未通过安全校验，已停止处理",
                    handoff_required=True,
                    retryable=False,
                )

    provider = "a2a_mock"
