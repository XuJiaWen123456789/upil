"""阶段 14-A-6：学情报告 LangGraph 编排、持久化和失败降级测试。"""

from backend.app.graph import answer_learning_report
from backend.app.integrations.a2a_client import LocalMockA2AClient
from backend.app.models import ReportTask
from backend.app.services.access_control import AccessContext
from backend.app.services.report_tasks import list_report_artifacts
from tests.test_database import make_session, seed_session


def report_state(session, **updates):
    """构造固定日期报告请求，避免测试依赖运行当天所在月份。"""

    state = {
        "route": "learning_report",
        "message": "生成 2026-08-01 至 2026-08-31 的学情报告",
        # 认证在图外完成，报告节点只能消费可信权限上下文。
        "access_context": AccessContext(user_id="P1001", role="parent"),
        "learner_id": "L1001",
        "request_id": "req_report_graph_001",
        "session": session,
        "a2a_learning_enabled": True,
        "a2a_learning_client": LocalMockA2AClient(),
    }
    state.update(updates)
    return state


def test_report_graph_completes_and_persists_artifact() -> None:
    """合法家长请求应完成 A2A 报告，并持久化任务和唯一产物。"""

    with make_session() as session:
        seed_session(session)
        result = answer_learning_report(report_state(session))

        assert result["provider"] == "a2a_mock"
        assert result["a2a_status"] == "completed"
        assert result["a2a_task_id"].startswith("task_")
        assert "# 家长学情报告" in result["answer"]
        assert "2026年8月" in result["answer"]
        assert "出勤率：50%" in result["answer"]
        assert "当前剩余课时：12 节" in result["answer"]

        task = session.get(ReportTask, result["report_task_id"])
        assert task is not None
        assert task.status == "completed"
        assert "L1001" not in str(task.scope)
        artifacts = list_report_artifacts(session, task.id)
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "markdown"
        assert artifacts[0].checksum is not None


def test_report_graph_reuses_completed_request_id() -> None:
    """同一请求 ID 重放时应返回持久化报告，不重复执行 A2A。"""

    with make_session() as session:
        seed_session(session)
        client = LocalMockA2AClient()
        state = report_state(session, a2a_learning_client=client)
        first = answer_learning_report(state)
        second = answer_learning_report(state)

        assert first["report_task_id"] == second["report_task_id"]
        assert second["provider"] == "report_cache"
        assert second["answer"] == first["answer"]
        assert client.agent.call_count == 1


def test_report_graph_requires_explicit_period_without_creating_task() -> None:
    """周期缺失时必须先澄清，且数据库中不能出现报告任务。"""

    with make_session() as session:
        seed_session(session)
        result = answer_learning_report(
            report_state(session, message="帮我生成孩子的学情报告")
        )

        assert result["provider"] == "workflow"
        assert "报告周期" in result["answer"]
        assert session.query(ReportTask).count() == 0


def test_report_graph_denies_unbound_learner_without_leaking_data() -> None:
    """家长访问未绑定学员时不生成任务，也不泄露该学员是否存在。"""

    with make_session() as session:
        seed_session(session)
        result = answer_learning_report(report_state(session, learner_id="L2001"))

        assert result["provider"] == "database"
        assert "L2001" not in result["answer"]
        assert "剩余" not in result["answer"]
        assert session.query(ReportTask).count() == 0


def test_report_graph_marks_task_failed_when_a2a_rejects_artifact() -> None:
    """非法远程产物不得展示或落库，主任务必须进入 failed 终态。"""

    client = LocalMockA2AClient()
    original_generate = client.generate_report

    def generate_invalid(snapshot, *, request_id):
        return original_generate(
            snapshot, request_id=request_id, behavior="invalid_artifact"
        )

    client.generate_report = generate_invalid  # type: ignore[method-assign]

    with make_session() as session:
        seed_session(session)
        result = answer_learning_report(
            report_state(
                session,
                request_id="req_report_graph_invalid",
                a2a_learning_client=client,
            )
        )

        assert result["a2a_status"] == "failed"
        assert "#!/bin/sh" not in result["answer"]
        task = session.get(ReportTask, result["report_task_id"])
        assert task is not None
        assert task.status == "failed"
        assert list_report_artifacts(session, task.id) == []


def test_report_graph_marks_task_failed_when_a2a_is_disabled() -> None:
    """报告 A2A 未启用时保留失败任务，不伪造或回退到旧数据报告。"""

    with make_session() as session:
        seed_session(session)
        result = answer_learning_report(
            report_state(
                session,
                request_id="req_report_graph_disabled",
                a2a_learning_enabled=False,
                a2a_learning_client=None,
            )
        )

        assert result["a2a_status"] == "failed"
        assert "学情报告生成服务暂时不可用" in result["answer"]
        task = session.get(ReportTask, result["report_task_id"])
        assert task is not None
        assert task.status == "failed"
        assert list_report_artifacts(session, task.id) == []
