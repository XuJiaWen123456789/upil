"""DeepSeekHarness（DSH）执行边界与故障关闭适配层。

本阶段只定义受控执行契约，不连接真实 DSH，不执行用户提交的 Python、Shell、SQL
或任意命令。这样可以先验证 A2A 任务进入编码执行节点前的安全门禁，避免为了
“体现技术点”而把任意代码执行能力直接暴露给客服链路。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.app.a2a.contracts import (
    A2AQualityResult,
    A2ATaskRequest,
    A2ATaskResult,
)


class DshExecutionRejectedError(ValueError):
    """任务不符合 DSH 执行白名单或安全约束。"""


class DshHarnessUnavailableError(RuntimeError):
    """真实 DSH 执行器尚未配置或暂时不可用。"""


@dataclass(frozen=True, slots=True)
class DshExecutionPlan:
    """经过门禁后的最小执行计划，不携带学员快照或自然语言正文。"""

    task_id: str
    protocol_version: str
    skill: str
    max_runtime_seconds: int
    output_format: str


class DshHarness(Protocol):
    """未来真实 DeepSeekHarness 适配器需要实现的最小接口。"""

    provider: str

    def execute(self, task: A2ATaskRequest) -> A2ATaskResult:
        """执行通过门禁的固定任务，并返回经过协议约束的结果。"""
        ...


class DshExecutionGate:
    """在任务交给 DSH 前执行固定技能、输出和安全策略校验。"""

    # 当前只允许三个固定业务技能；不允许把 DSH 变成用户可调用的通用代码执行器。
    allowed_skills = {"learning_summary", "learning_report", "class_learning_report"}
    allowed_output_formats = {"markdown_report"}

    @classmethod
    def authorize(cls, task: A2ATaskRequest) -> DshExecutionPlan:
        """返回不含原始输入的执行计划；任何越权条件都直接拒绝。"""

        if task.skill not in cls.allowed_skills:
            raise DshExecutionRejectedError("DSH 技能不在白名单中")
        if task.constraints.output_format not in cls.allowed_output_formats:
            raise DshExecutionRejectedError("DSH 输出格式不在白名单中")
        if task.constraints.no_external_network is not True:
            raise DshExecutionRejectedError("DSH 任务必须禁止外部网络")
        if task.constraints.no_side_effects is not True:
            raise DshExecutionRejectedError("DSH 任务必须禁止副作用")

        # 计划只保留调度所需的控制字段，不把 learner_ref 或学情正文交给后续日志。
        return DshExecutionPlan(
            task_id=task.task_id,
            protocol_version=task.protocol_version,
            skill=task.skill,
            max_runtime_seconds=task.constraints.max_runtime_seconds,
            output_format=task.constraints.output_format,
        )


class DisabledDshHarness:
    """默认关闭的 DSH 占位适配器，采用 fail-closed 策略。"""

    provider = "dsh_disabled"

    def execute(self, task: A2ATaskRequest) -> A2ATaskResult:
        """先执行门禁，再明确返回未配置，不伪造 DSH 已完成。"""

        DshExecutionGate.authorize(task)
        return self._unavailable_result(task)

    @staticmethod
    def _unavailable_result(task: A2ATaskRequest) -> A2ATaskResult:
        """构造不含敏感信息的人工兜底结果。"""

        message = "DeepSeekHarness 执行器尚未配置，未执行代码，需人工或可信服务兜底"
        return A2ATaskResult(
            task_id=task.task_id,
            correlation_id=task.correlation_id,
            status="failed",
            message=message,
            quality=A2AQualityResult(passed=False, issues=["DSH 执行器未配置"]),
            handoff_required=True,
            retryable=False,
        )
