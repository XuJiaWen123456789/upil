"""阶段 14-A-1：学情报告协议、DSH 门禁和 LangGraph 路由回归测试。"""

from datetime import date

import pytest
from pydantic import ValidationError

from backend.app.a2a.contracts import (
    A2ATaskConstraints,
    A2ATaskRequest,
    LearningAnalysisInput,
    LearningReportInput,
)
from backend.app.a2a.dsh_harness import DshExecutionGate
from backend.app.graph import answer_learning_report, build_conversation_graph
from backend.app.services.access_control import AccessContext


def make_report_input() -> LearningReportInput:
    """构造不含真实姓名和原始学员编号的报告输入。"""

    return LearningReportInput(
        learner_ref="learner_ref_demo_001",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        period_label="2026年8月",
        period_type="previous_month",
        metrics=[
            "attendance_rate",
            "attendance_breakdown",
            "lesson_balance",
            "published_progress",
        ],
        scheduled_sessions=2,
        attended_sessions=1,
        excused_absences=0,
        unexcused_absences=1,
        attendance_rate=0.5,
        completed_lessons=8,
        remaining_lessons=12,
        course_summaries=["中国舞基础班：基础节奏与身体协调"],
        published_progress=["节奏模仿积极；下一步加强基本站姿"],
    )


def make_task() -> A2ATaskRequest:
    """构造一个合法的学情报告 A2A 任务。"""

    return A2ATaskRequest(
        task_id="task_learning_report_001",
        correlation_id="req_learning_report_001",
        skill="learning_report",
        input=make_report_input(),
        constraints=A2ATaskConstraints(
            max_runtime_seconds=10,
            output_format="markdown_report",
            no_external_network=True,
            no_side_effects=True,
        ),
    )


def test_report_task_uses_strict_report_input() -> None:
    """报告技能必须解析为 LearningReportInput，而不是旧摘要模型。"""

    task = make_task()
    assert task.skill == "learning_report"
    assert isinstance(task.input, LearningReportInput)
    assert task.input.period_label == "2026年8月"


def test_summary_task_remains_backward_compatible() -> None:
    """原有 learning_summary 合同仍然可以正常解析。"""

    task = A2ATaskRequest(
        task_id="task_learning_summary_001",
        correlation_id="req_learning_summary_001",
        skill="learning_summary",
        input=LearningAnalysisInput(
            learner_ref="learner_ref_demo_001",
            period="recent_30_days",
            metrics=["attendance_rate"],
            attendance_rate=0.5,
            completed_hours=8,
        ),
        constraints=A2ATaskConstraints(
            max_runtime_seconds=10,
            output_format="markdown_report",
            no_external_network=True,
            no_side_effects=True,
        ),
    )
    assert isinstance(task.input, LearningAnalysisInput)


def test_report_contract_rejects_unknown_execution_fields() -> None:
    """报告任务不能携带 command、SQL 或其他协议外字段。"""

    payload = make_task().model_dump(mode="python")
    payload["input"]["command"] = "whoami"
    with pytest.raises(ValidationError):
        A2ATaskRequest.model_validate(payload)


def test_report_contract_rejects_inconsistent_session_counts() -> None:
    """出勤、请假和缺勤不能超过后端计算出的应上课次数。"""

    # model_copy(update=...) 不会重新执行 Pydantic 校验，这里重新构造模型，
    # 才能真实验证协议边界，而不是让测试误判为已拦截异常数据。
    payload = make_report_input().model_dump(mode="python")
    payload["attended_sessions"] = 3
    with pytest.raises(ValidationError):
        LearningReportInput.model_validate(payload)


def test_dsh_gate_allows_report_but_keeps_safe_constraints() -> None:
    """DSH 可以处理固定报告技能，但仍然只能获得最小执行计划。"""

    plan = DshExecutionGate.authorize(make_task())
    assert plan.skill == "learning_report"
    assert not hasattr(plan, "learner_ref")
    assert "learner_ref_demo_001" not in str(plan)


def test_graph_registers_report_route_without_fake_result() -> None:
    """报告路由已注册，缺少会话时必须安全失败而不是伪造报告。"""

    graph = build_conversation_graph()
    result = graph.invoke(
        {
            "route": "learning_report",
            "message": "生成上个月学情报告",
            # 显式注入认证边界产生的家长权限上下文。
            "access_context": AccessContext(user_id="P1001", role="parent"),
        }
    )
    assert result["provider"] == "workflow"
    assert "已绑定的学员编号" in result["answer"]
    assert "12" not in result["answer"]


def test_report_missing_session_has_no_sensitive_output() -> None:
    """会话缺失时不得把输入状态中的学员标识写入用户可见回答。"""

    result = answer_learning_report(
        {
            "route": "learning_report",
            "message": "生成上个月学情报告",
            # 这里只验证数据库会话缺失，身份条件必须先满足。
            "access_context": AccessContext(user_id="P1001", role="parent"),
            "learner_id": "L1001",
        }
    )
    assert result["provider"] == "database"
    assert "L1001" not in result["answer"]
