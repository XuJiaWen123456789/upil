"""阶段 13-B：本地 Mock A2A 学情分析节点的协议和安全回归测试。"""

from datetime import date

import pytest
from pydantic import ValidationError

from backend.app.a2a.contracts import (
    A2ATaskConstraints,
    A2ATaskRequest,
    LearningAnalysisInput,
    LearningReportInput,
)
from backend.app.a2a.mock_learning_agent import MockLearningAnalysisAgent
from backend.app.integrations.a2a_client import (
    LocalMockA2AClient,
    build_learning_report_task,
)
from backend.app.learning_contracts import (
    AttendanceSummary,
    LearnerProfile,
    LearningReportPeriod,
    LearningReportSnapshot,
    LearningSummary,
    LessonBalance,
    PublishedProgress,
    ProgressRecord,
)


def make_snapshot() -> LearningSummary:
    """构造完全虚构的学情快照，避免测试依赖真实学员数据。"""

    return LearningSummary(
        profile=LearnerProfile(learner_id="L1001", learner_name="演示学员", active=True),
        balance=LessonBalance(learner_id="L1001", total_hours=20, consumed_hours=8, remaining_hours=12),
        attendance=AttendanceSummary(
            learner_id="L1001",
            total_lessons=10,
            present_lessons=9,
            absent_lessons=1,
            leave_lessons=0,
            attendance_rate=0.9,
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
        ),
        progress=[
            ProgressRecord(
                learner_id="L1001",
                course_id="DANCE-01",
                course_name="中国舞基础班",
                current_stage="基础组合",
                completion_rate=0.6,
                strengths=["能够完成基础组合"],
                next_focus=["加强节奏练习"],
                teacher_note="演示记录",
                updated_at=date(2026, 8, 30),
            )
        ],
    )


def make_report_snapshot() -> LearningReportSnapshot:
    """构造报告任务使用的脱敏快照，完全不依赖真实学员数据。"""

    return LearningReportSnapshot(
        learner_ref="learner_ref_demo_001",
        period=LearningReportPeriod(
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            period_label="2026年8月",
            period_type="previous_month",
        ),
        course_summaries=["中国舞基础班：基础节奏与身体协调"],
        scheduled_sessions=2,
        attended_sessions=1,
        excused_absences=0,
        unexcused_absences=1,
        attendance_rate=0.5,
        completed_lessons=8,
        remaining_lessons=12,
        published_progress=[
            PublishedProgress(
                course_name="中国舞基础班",
                current_stage="基础节奏与身体协调",
                completion_rate=0.4,
                strengths=["节奏模仿积极"],
                next_focus=["加强基本站姿"],
                updated_at=date(2026, 8, 30),
            )
        ],
    )


def test_valid_task_and_constraints() -> None:
    """合法任务应只允许 learning_summary 和两个强制安全开关。"""

    task = A2ATaskRequest(
        task_id="task_demo_001",
        correlation_id="req_demo_001",
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
    assert task.skill == "learning_summary"


def test_protocol_rejects_unknown_fields_and_arbitrary_skill() -> None:
    """协议层必须拒绝 command、password 和任意技能名称。"""

    with pytest.raises(ValidationError):
        LearningAnalysisInput(
            learner_ref="learner_ref_demo_001",
            period="recent_30_days",
            metrics=["attendance_rate"],
            attendance_rate=0.9,
            completed_hours=8,
            password="not-allowed",
        )
    with pytest.raises(ValidationError):
        A2ATaskConstraints(
            max_runtime_seconds=10,
            output_format="markdown_report",
            no_external_network=False,
            no_side_effects=True,
        )


def test_client_redacts_learner_identity_and_maps_correlation_id() -> None:
    """客户端只能传 learner_ref，request_id 必须映射为 correlation_id。"""

    agent = MockLearningAnalysisAgent()
    client = LocalMockA2AClient(agent)
    result = client.analyze(make_snapshot(), request_id="req_demo_101")

    assert result.status == "completed"
    assert result.correlation_id == "req_demo_101"
    assert "演示学员" not in result.artifacts[0].content
    assert "L1001" not in result.artifacts[0].content
    assert "本地 Mock" in result.message


def test_mock_report_task_generates_safe_learning_report_artifact() -> None:
    """报告任务应生成唯一固定产物，并包含家长需要的核心统计项。"""

    task = build_learning_report_task(
        make_report_snapshot(), request_id="req_report_mock_001", timeout_seconds=10
    )
    assert task.skill == "learning_report"
    assert isinstance(task.input, LearningReportInput)
    assert task.input.period_label == "2026年8月"
    assert "L1001" not in task.model_dump_json()

    result = LocalMockA2AClient().generate_report(
        make_report_snapshot(), request_id="req_report_mock_001"
    )

    assert result.status == "completed"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.name == "learning-report.md"
    assert "2026年8月" in artifact.content
    assert "出勤率：50%" in artifact.content
    assert "本周期已完成课时：8 节" in artifact.content
    assert "当前剩余课时：12 节" in artifact.content
    assert "加强基本站姿" in artifact.content
    assert "teacher_note" not in artifact.content
    assert "演示学员" not in artifact.content
    assert "L1001" not in artifact.content


def test_report_timeout_retries_at_most_two_times_then_handoff() -> None:
    """报告任务与摘要任务共用超时重试上限，最多执行初次调用加两次重试。"""

    agent = MockLearningAnalysisAgent()
    client = LocalMockA2AClient(agent, max_retries=2)
    result = client.generate_report(
        make_report_snapshot(),
        request_id="req_report_mock_002",
        behavior="timeout",
    )

    assert agent.call_count == 3
    assert result.status == "failed"
    assert result.handoff_required is True
    assert "重试上限" in result.message


def test_task_ids_are_unique() -> None:
    """每次调度都必须生成新的任务 ID，不能复用上一次任务。"""

    client = LocalMockA2AClient()
    first = client.analyze(make_snapshot(), request_id="req_demo_102")
    second = client.analyze(make_snapshot(), request_id="req_demo_103")
    assert first.task_id != second.task_id


def test_timeout_retries_at_most_two_times_then_handoff() -> None:
    """超时最多重试两次，第三次仍失败时必须人工兜底。"""

    agent = MockLearningAnalysisAgent()
    client = LocalMockA2AClient(agent, max_retries=2)
    result = client.analyze(make_snapshot(), request_id="req_demo_104", behavior="timeout")

    assert agent.call_count == 3
    assert result.status == "failed"
    assert result.handoff_required is True
    assert "重试上限" in result.message


def test_failed_node_is_not_retried_and_requires_handoff() -> None:
    """明确业务失败不是可恢复超时，不应盲目重试。"""

    agent = MockLearningAnalysisAgent()
    client = LocalMockA2AClient(agent, max_retries=2)
    result = client.analyze(make_snapshot(), request_id="req_demo_105", behavior="failed")

    assert agent.call_count == 1
    assert result.status == "failed"
    assert result.handoff_required is True
    assert result.quality is not None
    assert result.quality.passed is False


def test_invalid_artifact_is_rejected_and_requires_handoff() -> None:
    """危险 Artifact 必须在主系统被拒绝，不能继续生成客服话术。"""

    client = LocalMockA2AClient()
    result = client.analyze(make_snapshot(), request_id="req_demo_106", behavior="invalid_artifact")

    assert result.status == "failed"
    assert result.handoff_required is True
    assert "安全校验" in result.message


def test_mock_agent_does_not_execute_user_code() -> None:
    """Mock 节点只生成固定 Markdown，不接受 command 或脚本字段。"""

    agent = MockLearningAnalysisAgent()
    task = A2ATaskRequest(
        task_id="task_demo_107",
        correlation_id="req_demo_107",
        skill="learning_summary",
        input=LearningAnalysisInput(
            learner_ref="learner_ref_demo_107",
            period="recent_30_days",
            metrics=["progress_notes"],
            attendance_rate=1.0,
            completed_hours=0,
            progress_notes=["演示记录"],
        ),
        constraints=A2ATaskConstraints(
            max_runtime_seconds=10,
            output_format="markdown_report",
            no_external_network=True,
            no_side_effects=True,
        ),
    )
    result = agent.process(task)
    assert result.status == "completed"
    assert "subprocess" not in result.artifacts[0].content
