"""阶段 13-F：DSH 执行门禁、默认关闭和安全失败测试。"""

from __future__ import annotations

import pytest

from backend.app.a2a.contracts import (
    A2ATaskConstraints,
    A2ATaskRequest,
    LearningAnalysisInput,
)
from backend.app.a2a.dsh_harness import (
    DisabledDshHarness,
    DshExecutionGate,
    DshExecutionRejectedError,
)


def make_task() -> A2ATaskRequest:
    """构造脱敏的固定学情任务，所有字段均为虚构演示值。"""

    return A2ATaskRequest(
        task_id="task_dsh_gate_001",
        correlation_id="req_dsh_gate_001",
        skill="learning_summary",
        input=LearningAnalysisInput(
            learner_ref="learner_ref_demo_001",
            period="recent_30_days",
            metrics=["attendance_rate"],
            attendance_rate=0.9,
            completed_hours=8,
        ),
        constraints=A2ATaskConstraints(
            max_runtime_seconds=10,
            output_format="markdown_report",
            no_external_network=True,
            no_side_effects=True,
        ),
    )


def test_gate_returns_minimal_plan_without_sensitive_input() -> None:
    """合法任务可以形成执行计划，但计划不能包含学情输入。"""

    task = make_task()
    plan = DshExecutionGate.authorize(task)

    assert plan.task_id == task.task_id
    assert plan.skill == "learning_summary"
    assert plan.max_runtime_seconds == 10
    assert not hasattr(plan, "learner_ref")
    assert "learner_ref_demo_001" not in str(plan)


@pytest.mark.parametrize(
    "field, value",
    [
        ("no_external_network", False),
        ("no_side_effects", False),
    ],
)
def test_gate_rejects_disabled_safety_switch(field: str, value: bool) -> None:
    """任何安全开关被关闭时，DSH 门禁必须拒绝任务。"""

    task = make_task()
    constraints = task.constraints.model_copy(update={field: value})
    unsafe_task = task.model_copy(update={"constraints": constraints})

    with pytest.raises(DshExecutionRejectedError):
        DshExecutionGate.authorize(unsafe_task)


def test_gate_rejects_non_whitelisted_skill() -> None:
    """报表或任意编码技能不能借用学情分析入口执行。"""

    task = make_task().model_copy(update={"skill": "learning_summary"})
    # 使用 model_construct 模拟未来协议新增技能，验证运行时门禁仍然存在。
    unsafe_task = task.model_copy()
    object.__setattr__(unsafe_task, "skill", "arbitrary_code")

    with pytest.raises(DshExecutionRejectedError):
        DshExecutionGate.authorize(unsafe_task)


def test_disabled_harness_fails_closed_without_fake_success() -> None:
    """未配置真实 DSH 时不能伪造完成，必须人工兜底。"""

    result = DisabledDshHarness().execute(make_task())

    assert result.status == "failed"
    assert result.handoff_required is True
    assert result.retryable is False
    assert "未执行代码" in result.message
    assert "learner_ref_demo_001" not in result.message
