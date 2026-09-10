"""阶段 13-D：独立 HTTP A2A 子服务和客户端的安全回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import backend.app.a2a.mock_server as mock_server
from backend.app.a2a.contracts import A2ATaskResult
from backend.app.integrations.a2a_client import (
    build_learning_report_task,
    build_learning_task,
)
from backend.app.integrations.a2a_http_client import HttpA2ALearningClient
from backend.app.services.access_control import AccessContext
from tests.test_a2a_learning_agent import make_snapshot
from tests.test_a2a_learning_agent import make_report_snapshot


SERVICE_TOKEN = "stage13d-local-token-only"


@pytest.fixture
def server_client(monkeypatch: pytest.MonkeyPatch):
    """为子服务注入测试令牌，不读取或暴露开发机真实配置。"""

    monkeypatch.setattr(
        mock_server,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="test",
            a2a_learning_service_token=SERVICE_TOKEN,
        ),
    )
    # 每个 HTTP 用例独立清理任务状态，避免幂等缓存互相污染。
    mock_server.task_store.clear()
    mock_server.agent.call_count = 0
    with TestClient(mock_server.app) as client:
        yield client
    mock_server.task_store.clear()
    mock_server.agent.call_count = 0


def test_http_agent_health_check(server_client: TestClient) -> None:
    """健康检查只应暴露服务状态和协议版本。"""

    response = server_client.get("/health")
    assert response.status_code == 200
    assert response.json()["protocol_version"] == "upil-a2a/1.0"
    assert SERVICE_TOKEN not in response.text


def test_http_agent_accepts_authorized_task(server_client: TestClient) -> None:
    """合法令牌和严格任务应得到唯一 Markdown Artifact。"""

    task = build_learning_task(
        make_snapshot(), request_id="req_http_server_001", timeout_seconds=10
    )
    response = server_client.post(
        "/internal/a2a/tasks",
        headers={"X-A2A-Service-Token": SERVICE_TOKEN},
        json=task.model_dump(mode="json"),
    )
    assert response.status_code == 200
    result = A2ATaskResult.model_validate(response.json())
    assert result.status == "completed"
    assert result.correlation_id == "req_http_server_001"
    assert len(result.artifacts) == 1


def test_http_agent_accepts_authorized_report_task(server_client: TestClient) -> None:
    """同一 A2A HTTP 端点应根据 skill 处理家长报告任务。"""

    task = build_learning_report_task(
        make_report_snapshot(), request_id="req_http_report_001", timeout_seconds=10
    )
    response = server_client.post(
        "/internal/a2a/tasks",
        headers={"X-A2A-Service-Token": SERVICE_TOKEN},
        json=task.model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = A2ATaskResult.model_validate(response.json())
    assert result.status == "completed"
    assert result.artifacts[0].name == "learning-report.md"
    assert "出勤率：50%" in result.artifacts[0].content


def test_http_agent_deduplicates_repeated_task(server_client: TestClient) -> None:
    """同一 HTTP 任务重复提交时返回缓存结果且 Agent 只执行一次。"""

    task = build_learning_task(
        make_snapshot(), request_id="req_http_idempotent_001", timeout_seconds=10
    )
    headers = {"X-A2A-Service-Token": SERVICE_TOKEN}
    first = server_client.post("/internal/a2a/tasks", headers=headers, json=task.model_dump(mode="json"))
    second = server_client.post("/internal/a2a/tasks", headers=headers, json=task.model_dump(mode="json"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert mock_server.agent.call_count == 1
    assert mock_server.task_store.metrics()["deduplicated"] == 1


def test_http_agent_rejects_task_id_conflict(server_client: TestClient) -> None:
    """同一 task_id 携带不同学情内容时返回 409，不覆盖原结果。"""

    first_task = build_learning_task(
        make_snapshot(), request_id="req_http_conflict_001", timeout_seconds=10
    )
    second_task = first_task.model_copy(
        update={
            "input": first_task.input.model_copy(update={"completed_hours": 99})
        }
    )
    headers = {"X-A2A-Service-Token": SERVICE_TOKEN}
    first = server_client.post("/internal/a2a/tasks", headers=headers, json=first_task.model_dump(mode="json"))
    conflict = server_client.post("/internal/a2a/tasks", headers=headers, json=second_task.model_dump(mode="json"))

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert mock_server.agent.call_count == 1


def test_http_agent_can_query_task_result(server_client: TestClient) -> None:
    """已完成任务可以按 task_id 查询，不返回原始请求快照。"""

    task = build_learning_task(
        make_snapshot(), request_id="req_http_query_001", timeout_seconds=10
    )
    headers = {"X-A2A-Service-Token": SERVICE_TOKEN}
    created = server_client.post("/internal/a2a/tasks", headers=headers, json=task.model_dump(mode="json"))
    queried = server_client.get(f"/internal/a2a/tasks/{task.task_id}", headers=headers)

    assert created.status_code == 200
    assert queried.status_code == 200
    assert queried.json() == created.json()
    assert "learner_ref" not in queried.text
    assert "演示学员" not in queried.text


def test_http_agent_returns_404_for_unknown_task(server_client: TestClient) -> None:
    """未知任务和已过期任务统一返回 404。"""

    response = server_client.get(
        "/internal/a2a/tasks/task_not_found_001",
        headers={"X-A2A-Service-Token": SERVICE_TOKEN},
    )
    assert response.status_code == 404


def test_http_agent_exposes_redacted_metrics(server_client: TestClient) -> None:
    """指标端点只返回脱敏计数，并要求内部服务令牌。"""

    headers = {"X-A2A-Service-Token": SERVICE_TOKEN}
    task = build_learning_task(
        make_snapshot(), request_id="req_http_metrics_001", timeout_seconds=10
    )
    server_client.post("/internal/a2a/tasks", headers=headers, json=task.model_dump(mode="json"))
    response = server_client.get("/internal/a2a/metrics", headers=headers)

    assert response.status_code == 200
    assert response.json()["executed"] == 1
    assert response.json()["stored"] == 1
    assert "L1001" not in response.text
    assert "learner_ref" not in response.text
    assert SERVICE_TOKEN not in response.text

    unauthorized = server_client.get("/internal/a2a/metrics")
    assert unauthorized.status_code == 401


def test_http_agent_rejects_wrong_token(server_client: TestClient) -> None:
    """错误服务令牌不能访问内部任务端点。"""

    task = build_learning_task(
        make_snapshot(), request_id="req_http_server_002", timeout_seconds=10
    )
    response = server_client.post(
        "/internal/a2a/tasks",
        headers={"X-A2A-Service-Token": "wrong-token-not-valid"},
        json=task.model_dump(mode="json"),
    )
    assert response.status_code == 401


def test_http_agent_rejects_unknown_execution_fields(server_client: TestClient) -> None:
    """command、SQL、URL 等协议外字段必须被 422 拒绝。"""

    task = build_learning_task(
        make_snapshot(), request_id="req_http_server_003", timeout_seconds=10
    ).model_dump(mode="json")
    task["command"] = "whoami"
    task["sql"] = "SELECT * FROM learners"
    task["url"] = "http://example.invalid"
    response = server_client.post(
        "/internal/a2a/tasks",
        headers={"X-A2A-Service-Token": SERVICE_TOKEN},
        json=task,
    )
    assert response.status_code == 422


def test_http_client_preserves_correlation_and_redacts_identity() -> None:
    """跨 HTTP 请求仍需保持关联 ID，且不能发出姓名和内部学员编号。"""

    captured_body = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.content.decode("utf-8")
        task = build_task_from_request(request)
        result = mock_server.agent.process(task)
        return httpx.Response(200, json=result.model_dump(mode="json"))

    client = make_http_client(httpx.MockTransport(handler))
    result = client.analyze(make_snapshot(), request_id="req_http_client_001")

    assert result.status == "completed"
    assert result.correlation_id == "req_http_client_001"
    assert result.quality is not None and result.quality.passed is True
    assert "演示学员" not in captured_body
    assert "L1001" not in captured_body
    assert SERVICE_TOKEN not in captured_body


def test_http_client_can_generate_report() -> None:
    """HTTP 客户端的报告方法应复用标准任务端点并通过结果校验。"""

    captured_body = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.content.decode("utf-8")
        task = build_task_from_request(request)
        result = mock_server.agent.process(task)
        return httpx.Response(200, json=result.model_dump(mode="json"))

    result = make_http_client(httpx.MockTransport(handler)).generate_report(
        make_report_snapshot(), request_id="req_http_report_002"
    )

    assert result.status == "completed"
    assert result.correlation_id == "req_http_report_002"
    assert result.artifacts[0].name == "learning-report.md"
    assert "当前剩余课时：12 节" in result.artifacts[0].content
    assert '"skill":"learning_report"' in captured_body
    assert "演示学员" not in captured_body
    assert "L1001" not in captured_body


def test_http_client_retries_timeout_at_most_two_times() -> None:
    """真实 HTTP 超时只允许首次调用加两次重试。"""

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("演示超时", request=request)

    result = make_http_client(httpx.MockTransport(handler)).analyze(
        make_snapshot(), request_id="req_http_client_002"
    )
    assert attempts == 3
    assert result.status == "failed"
    assert result.handoff_required is True


def test_http_client_retry_reuses_task_and_server_deduplicates() -> None:
    """服务端已完成但响应超时时，客户端重试不应重复执行 Agent。"""

    # 本测试直接复用 Mock 子服务的任务仓库，模拟“服务端已写入、客户端未收到响应”。
    mock_server.task_store.clear()
    mock_server.agent.call_count = 0
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        task = build_task_from_request(request)
        result, _ = mock_server.task_store.execute(task, mock_server.agent.process)
        if attempts == 1:
            # 第一次请求在服务端完成后模拟网络读超时，迫使客户端使用同一 task_id 重试。
            raise httpx.ReadTimeout("响应读取超时", request=request)
        return httpx.Response(200, json=result.model_dump(mode="json"))

    result = make_http_client(httpx.MockTransport(handler)).analyze(
        make_snapshot(), request_id="req_http_idempotent_timeout_001"
    )

    assert attempts == 2
    assert mock_server.agent.call_count == 1
    assert result.status == "completed"
    assert mock_server.task_store.metrics()["deduplicated"] == 1
    mock_server.task_store.clear()
    mock_server.agent.call_count = 0


def test_http_client_does_not_retry_non_2xx() -> None:
    """认证失败等非 2xx 响应不能盲目重试。"""

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"detail": "认证失败"})

    result = make_http_client(httpx.MockTransport(handler)).analyze(
        make_snapshot(), request_id="req_http_client_003"
    )
    assert attempts == 1
    assert result.status == "failed"


def test_http_client_rejects_invalid_artifact_response() -> None:
    """远端伪造的危险 Artifact 必须由主系统再次拒绝。"""

    def handler(request: httpx.Request) -> httpx.Response:
        task = build_task_from_request(request)
        result = mock_server.agent.process(task, behavior="invalid_artifact")
        # model_construct 产物先序列化，模拟不可信远端返回非法内容。
        return httpx.Response(200, json=result.model_dump(mode="json"))

    result = make_http_client(httpx.MockTransport(handler)).analyze(
        make_snapshot(), request_id="req_http_client_004"
    )
    assert result.status == "failed"
    assert result.quality is not None and result.quality.passed is False


def test_langgraph_uses_http_provider_for_completed_result() -> None:
    """独立 HTTP 客户端成功时，LangGraph 应标记 a2a_http 提供方。"""

    from backend.app.graph import answer_learning_summary
    from tests.test_database import make_session, seed_session

    def handler(request: httpx.Request) -> httpx.Response:
        task = build_task_from_request(request)
        result = mock_server.agent.process(task)
        return httpx.Response(200, json=result.model_dump(mode="json"))

    session = make_session()
    seed_session(session)
    result = answer_learning_summary(
        {
            "access_context": AccessContext(user_id="P1001", role="parent"),
            "learner_id": "L1001",
            "request_id": "req_graph_http_001",
            "session": session,
            "a2a_learning_enabled": True,
            "a2a_learning_client": make_http_client(httpx.MockTransport(handler)),
        }
    )
    assert result["provider"] == "a2a_http"
    assert result["a2a_status"] == "completed"
    assert result["a2a_correlation_id"] == "req_graph_http_001"
    assert "本地 Mock 学情分析智能体" in result["answer"]


def test_langgraph_falls_back_to_database_when_http_service_fails() -> None:
    """HTTP 子服务不可用时仍返回可信数据库摘要，不编造动态数据。"""

    from backend.app.graph import answer_learning_summary
    from tests.test_database import make_session, seed_session

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "演示服务不可用"})

    session = make_session()
    seed_session(session)
    result = answer_learning_summary(
        {
            "access_context": AccessContext(user_id="P1001", role="parent"),
            "learner_id": "L1001",
            "request_id": "req_graph_http_002",
            "session": session,
            "a2a_learning_enabled": True,
            "a2a_learning_client": make_http_client(httpx.MockTransport(handler)),
        }
    )
    assert result["provider"] == "database"
    assert result["a2a_status"] == "failed"
    assert "剩余课时" in result["answer"]
    assert "增强服务暂时不可用" in result["answer"]


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:8101",
        "http://192.168.1.9:8101",
        "http://user:pass@127.0.0.1:8101",
        "http://127.0.0.1:8101?target=http://example.invalid",
    ],
)
def test_http_client_rejects_non_loopback_or_unsafe_url(base_url: str) -> None:
    """阶段 13-D 不允许公网、局域网、URL 凭据或可变目标参数。"""

    with pytest.raises(ValueError):
        HttpA2ALearningClient(base_url=base_url, service_token=SERVICE_TOKEN)


def make_http_client(transport: httpx.BaseTransport) -> HttpA2ALearningClient:
    """构造使用内存 HTTP Transport 的客户端，避免测试依赖端口。"""

    return HttpA2ALearningClient(
        base_url="http://127.0.0.1:8101",
        service_token=SERVICE_TOKEN,
        max_retries=2,
        timeout_seconds=10,
        transport=transport,
    )


def build_task_from_request(request: httpx.Request):
    """从测试 HTTP 请求恢复严格任务，并核对内部认证头。"""

    import json

    from backend.app.a2a.contracts import A2ATaskRequest

    assert request.headers["X-A2A-Service-Token"] == SERVICE_TOKEN
    return A2ATaskRequest.model_validate(json.loads(request.content))
