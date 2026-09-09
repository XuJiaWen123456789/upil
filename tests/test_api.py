"""FastAPI 健康检查和 SSE 路由测试。"""

import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from backend.app.db import Base, get_session
from backend.app.integrations.minio import MinioMediaStore
from backend.app.main import (
    app,
    get_a2a_learning_client,
    get_conversation_store,
    get_intent_model,
    get_media_store,
)
from backend.app.models import MediaAsset
from backend.app.config import Settings
from backend.app.services.faq import FAQStreamChunk, OFFLINE_FAQ_ANSWER
from backend.app.services.conversation_state import InMemoryConversationStore
from backend.app.services.dependency_health import check_dependencies, overall_status
from backend.app.a2a.mock_learning_agent import MockLearningAnalysisAgent
from backend.app.integrations.a2a_client import LocalMockA2AClient
import backend.app.main as main_module

from tests.test_database import make_session, seed_session


# API 测试使用固定的内存数据库，避免依赖开发机上的 PostgreSQL 服务。
api_session: Session = make_session()
seed_session(api_session)


# 使用带 PNG 文件头的演示字节，配合假的 MinIO 客户端验证完整 HTTP 流程。
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"demo-image"


def override_get_session():
    """为 API 测试注入预置数据，模拟真实请求的数据库依赖。"""

    yield api_session


app.dependency_overrides[get_session] = override_get_session
# API 回归默认不访问真实 DeepSeek，真实网络测试由专用测试文件显式开启。
app.dependency_overrides[get_intent_model] = lambda: None
app.dependency_overrides[get_conversation_store] = InMemoryConversationStore


client = TestClient(app)


def parse_sse_events(body: str) -> list[tuple[str, dict]]:
    """将 SSE 文本解析为便于断言的事件列表。"""

    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def parse_sse_response(response) -> list[tuple[str, dict]]:
    """读取测试响应正文并复用 SSE 解析器。"""

    return parse_sse_events(response.content.decode("utf-8"))


def test_health() -> None:
    """健康检查应返回稳定的 ok 状态。"""

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_frontend_shell_is_served_without_exposing_backend_details() -> None:
    """根路径应返回客服演示页，静态页面不应包含密钥或后端配置。"""

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "星河素质教育中心智能客服" in response.text
    assert "RAGFLOW_API_KEY" not in response.text
    assert "LLM_API_KEY" not in response.text


def test_frontend_assets_are_served() -> None:
    """客服页依赖的 JavaScript 和 CSS 应能由同一 FastAPI 入口访问。"""

    script = client.get("/app.js")
    stylesheet = client.get("/style.css")

    assert script.status_code == 200
    assert "consumeSse" in script.text
    assert stylesheet.status_code == 200
    assert "chat-layout" in stylesheet.text


def test_frontend_debug_learner_control_is_staging_only() -> None:
    """验证演示学员字段只作为调试入口存在，不暴露后端密钥。"""

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="demo-learner-field"' in response.text
    assert 'value="L1001"' in response.text
    assert "仅调试" in response.text


def test_dependency_health_is_safe_when_optional_services_are_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖检查只返回脱敏状态，未配置的可选服务不能阻塞主 API。"""

    monkeypatch.setattr(main_module, "check_dependencies", lambda settings: {
        "database": "ok",
        "minio": "disabled",
        "ragflow": "not_configured",
        "a2a_learning": "disabled",
    })
    response = client.get("/api/v1/health/dependencies")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["a2a_learning"] == "disabled"
    assert "api_key" not in response.text.lower()
    assert "password" not in response.text.lower()


def test_dependency_health_returns_degraded_for_failed_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖故障应标记 degraded，但仍返回可解析的稳定结构。"""

    monkeypatch.setattr(main_module, "check_dependencies", lambda settings: {
        "database": "ok",
        "minio": "error",
        "ragflow": "unavailable",
        "a2a_learning": "disabled",
    })
    response = client.get("/api/v1/health/dependencies")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_dependency_health_probe_failures_are_collapsed_to_safe_status() -> None:
    """探针内部异常不能泄露连接细节，只能转换为 error 状态。"""

    result = check_dependencies(
        database_probe=lambda: (_ for _ in ()).throw(RuntimeError("secret host")),
        minio_probe=lambda: True,
        ragflow_probe=lambda: True,
        a2a_probe=lambda: True,
    )
    assert result["database"] == "error"
    assert overall_status(result) == "degraded"


def test_http_request_id_is_returned() -> None:
    """HTTP 请求没有携带追踪 ID 时，服务端应自动生成并返回。"""

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req_")


def test_http_request_id_is_propagated() -> None:
    """可信上游传入的安全追踪 ID 可以原样透传到响应头。"""

    response = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "req_demo_001"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req_demo_001"


def test_invalid_http_request_id_is_replaced() -> None:
    """包含空格等非法字符的追踪 ID 必须被服务端重新生成。"""

    response = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "bad id"},
    )

    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    assert request_id.startswith("req_")
    assert " " not in request_id


def test_demo_class_availability_endpoint() -> None:
    """固定用途的演示接口应返回 Fake Adapter 的只读演示结果。"""

    response = client.post(
        "/api/v1/internal/demo/class-availability",
        headers={"X-Request-ID": "req_demo_002"},
        json={
            "course_name": "中国舞基础班",
            "campus_name": "星河中心校区",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req_demo_002"

    body = response.json()
    assert body["tool_name"] == "class_availability"
    assert body["status"] == "success"
    assert body["data"]["available_seats"] == 3
    assert "演示" in body["message"]


def test_demo_tool_endpoint_rejects_arbitrary_tool_name() -> None:
    """固定演示接口不能被扩展为客户端指定任意工具名的万能入口。"""

    response = client.post(
        "/api/v1/internal/demo/class-availability",
        json={
            "tool_name": "run_shell",
            "course_name": "中国舞基础班",
            "campus_name": "星河中心校区",
        },
    )

    assert response.status_code == 422


def test_stream_routes_faq(monkeypatch: pytest.MonkeyPatch) -> None:
    """普通校区问题应进入 FAQ 分支并产生 token 事件。

    此测试显式注入离线流，避免开发机 .env 中的真实 API 配置让默认单元
    测试访问网络；真实 DeepSeek 调用由 test_real_intent_model 单独负责。
    """

    async def fake_offline_faq_stream(question: str):
        for index in range(0, len(OFFLINE_FAQ_ANSWER), 12):
            yield FAQStreamChunk(
                content=OFFLINE_FAQ_ANSWER[index : index + 12],
                provider="offline",
            )

    monkeypatch.setattr("backend.app.main.stream_faq_answer", fake_offline_faq_stream)

    response = client.post("/api/v1/chat/stream", json={"message": "请问校区在哪里"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = parse_sse_response(response)
    assert events[0] == ("status", {"stage": "accepted"})
    assert any(event == "token" for event, _ in events)
    assert events[-1] == (
        "complete",
        {
            "route": "faq",
            "provider": "offline",
            "sources": [],
            "recognition_source": "deterministic_fallback",
        },
    )


def test_stream_routes_learning_summary() -> None:
    """带学员编号的课时问题应返回演示学情摘要。"""

    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "查询课时和出勤", "learner_id": "L1001"},
    )
    assert response.status_code == 200
    events = parse_sse_response(response)
    assert events[-1] == (
        "complete",
        {
            "route": "learning_summary",
            "provider": "database",
            "sources": [],
            "recognition_source": "deterministic_guard",
        },
    )
    answer = "".join(data["content"] for event, data in events if event == "token")
    assert "剩余课时 12 节" in answer


def test_stream_learning_summary_uses_a2a_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式开启功能开关后，可信学情快照应进入 Mock A2A 分析节点。"""

    monkeypatch.setattr(main_module.settings, "a2a_learning_enabled", True)
    mock_client = LocalMockA2AClient()
    app.dependency_overrides[get_a2a_learning_client] = lambda: mock_client
    try:
        response = client.post(
            "/api/v1/chat/stream",
            headers={"X-Request-ID": "req_a2a_demo_001"},
            json={"message": "查询课时和出勤", "learner_id": "L1001"},
        )
        assert response.status_code == 200
        events = parse_sse_response(response)
        a2a_events = [data for event, data in events if event == "status" and data.get("stage") == "a2a_task"]
        assert len(a2a_events) == 1
        assert a2a_events[0]["status"] == "completed"
        assert a2a_events[0]["correlation_id"] == "req_a2a_demo_001"
        assert a2a_events[0]["task_id"].startswith("task_")
        assert events[-1][1]["provider"] == "a2a_mock"
        answer = "".join(data["content"] for event, data in events if event == "token")
        assert "剩余课时 12 节" in answer
        assert "本地 Mock 学情分析智能体" in answer
    finally:
        app.dependency_overrides.pop(get_a2a_learning_client, None)


def test_stream_learning_report_uses_a2a_and_returns_persisted_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """报告请求应从真实 SSE 入口进入 LangGraph、A2A 和持久化链路。"""

    monkeypatch.setattr(main_module.settings, "a2a_learning_enabled", True)
    mock_client = LocalMockA2AClient()
    app.dependency_overrides[get_a2a_learning_client] = lambda: mock_client
    try:
        response = client.post(
            "/api/v1/chat/stream",
            headers={"X-Request-ID": "req_report_sse_001"},
            json={
                "message": "生成学情报告，时间为 2026-08-01 至 2026-08-31",
                "actor_role": "parent",
                "actor_user_id": "P1001",
                "learner_id": "L1001",
            },
        )

        assert response.status_code == 200
        events = parse_sse_response(response)
        task_event = next(
            data
            for event, data in events
            if event == "status" and data.get("stage") == "a2a_task"
        )
        assert task_event["status"] == "completed"
        assert task_event["correlation_id"] == "req_report_sse_001"
        assert task_event["task_id"].startswith("task_")
        assert events[-1][1]["route"] == "learning_report"
        assert events[-1][1]["provider"] == "a2a_mock"

        answer = "".join(
            data["content"] for event, data in events if event == "token"
        )
        assert "# 家长学情报告" in answer
        assert "2026年8月" in answer
        assert "出勤率：50%" in answer
        assert "当前剩余课时：12 节" in answer
        # SSE 对外内容不得泄露原始学员编号或内部匿名引用。
        assert "L1001" not in answer
        assert "learner_ref_" not in answer
    finally:
        app.dependency_overrides.pop(get_a2a_learning_client, None)


def test_stream_learning_summary_falls_back_when_a2a_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2A 连续超时时应返回可信数据库摘要，并通过 SSE 标明回退。"""

    monkeypatch.setattr(main_module.settings, "a2a_learning_enabled", True)
    agent = MockLearningAnalysisAgent()
    mock_client = LocalMockA2AClient(agent=agent, max_retries=2)

    # 测试专用客户端固定模拟超时，不把故障模式开放为 HTTP 请求参数。
    original_analyze = mock_client.analyze

    def timeout_analyze(snapshot, *, request_id):
        return original_analyze(snapshot, request_id=request_id, behavior="timeout")

    monkeypatch.setattr(mock_client, "analyze", timeout_analyze)
    app.dependency_overrides[get_a2a_learning_client] = lambda: mock_client
    try:
        response = client.post(
            "/api/v1/chat/stream",
            headers={"X-Request-ID": "req_a2a_demo_002"},
            json={"message": "查询课时和出勤", "learner_id": "L1001"},
        )
        assert response.status_code == 200
        events = parse_sse_response(response)
        task_event = next(
            data
            for event, data in events
            if event == "status" and data.get("stage") == "a2a_task"
        )
        assert task_event["status"] == "failed"
        assert task_event["fallback"] == "database"
        assert task_event["correlation_id"] == "req_a2a_demo_002"
        assert agent.call_count == 3
        assert events[-1][1]["provider"] == "database"
        answer = "".join(data["content"] for event, data in events if event == "token")
        assert "剩余课时 12 节" in answer
        assert "增强服务暂时不可用" in answer
    finally:
        app.dependency_overrides.pop(get_a2a_learning_client, None)


def test_stream_routes_service_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """服务规则请求应通过专用 SSE 分支返回，不应进入公开 FAQ。"""

    async def fake_service_rules_stream(question: str):
        assert "请假" in question
        yield FAQStreamChunk(content="请按服务规则提交申请。", provider="ragflow")

    monkeypatch.setattr("backend.app.main.stream_service_rules_answer", fake_service_rules_stream)
    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "孩子生病请假后可以补课吗"},
    )

    assert response.status_code == 200
    events = parse_sse_response(response)
    assert events[-1] == (
        "complete",
        {
            "route": "service_rules",
            "provider": "ragflow",
            "sources": [],
            "recognition_source": "deterministic_guard",
        },
    )


def test_stream_rewrites_multi_turn_course_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一会话切换课程后，FAQ 检索必须收到已消解的独立问题。"""

    captured_questions: list[str] = []

    async def capture_faq_stream(question: str):
        captured_questions.append(question)
        yield FAQStreamChunk(content="测试回答", provider="offline")

    store = InMemoryConversationStore()
    app.dependency_overrides[get_conversation_store] = lambda: store
    monkeypatch.setattr("backend.app.main.stream_faq_answer", capture_faq_stream)
    try:
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "孩子8岁，想学中国舞进阶班",
                "conversation_id": "switch-course",
            },
        )
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "不是舞蹈，是编程项目实践班",
                "conversation_id": "switch-course",
            },
        )
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "message": "这个课程适合多大孩子？需要什么基础？",
                "conversation_id": "switch-course",
            },
        )
        assert response.status_code == 200
        assert captured_questions[-1] == "编程项目实践班适合多大孩子？需要什么基础？"
        events = parse_sse_response(response)
        assert events[-1][1]["route"] == "faq"
    finally:
        # 恢复模块级默认覆盖，防止本测试的局部 Store 影响后续用例。
        app.dependency_overrides[get_conversation_store] = InMemoryConversationStore


def test_stream_live_seat_query_never_calls_static_faq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """实时名额工具尚未接入时应转人工，不能让 RAG 回答动态事实。"""

    async def forbidden_faq_stream(question: str):
        raise AssertionError("实时名额请求不应调用静态 FAQ")
        yield  # pragma: no cover - 仅保持异步生成器类型

    monkeypatch.setattr("backend.app.main.stream_faq_answer", forbidden_faq_stream)
    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "编程项目实践班现在还有名额吗？"},
    )
    assert response.status_code == 200
    events = parse_sse_response(response)
    assert events[-1][1]["route"] == "human_handoff"
    assert events[-1][1]["recognition_source"] == "deterministic_guard"


def test_parent_privacy_prompt() -> None:
    """家长未提供学员编号时应先提示绑定信息要求。"""

    response = client.post("/api/v1/chat/stream", json={"message": "查询课时和出勤"})
    assert response.status_code == 200
    events = parse_sse_response(response)
    answer = "".join(data["content"] for event, data in events if event == "token")
    assert events[-1] == (
        "complete",
        {
            "route": "learning_summary",
            "provider": "database",
            "sources": [],
            "recognition_source": "deterministic_guard",
        },
    )
    assert "请先提供已绑定的学员编号" in answer


def test_parent_cannot_read_unbound_learner() -> None:
    """API 接入数据库后，家长访问未绑定学员应得到统一的无数据提示。"""

    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "查询课时和出勤", "learner_id": "L2001"},
    )
    assert response.status_code == 200
    events = parse_sse_response(response)
    answer = "".join(data["content"] for event, data in events if event == "token")
    assert "无权访问" in answer


def test_learning_snapshot_endpoint_returns_contract() -> None:
    """结构化学情接口应返回可供工具或 A2A 任务序列化的字段。"""

    response = client.get("/api/v1/learners/L1001/learning-snapshot")
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["learner_id"] == "L1001"
    assert body["balance"]["remaining_hours"] == 12
    assert body["attendance"]["attendance_rate"] == 0.5
    assert body["progress"][0]["course_name"] == "中国舞基础"


def test_learning_snapshot_endpoint_hides_unbound_learner() -> None:
    """结构化接口不能通过 learner_id 直接读取未绑定学员。"""

    response = client.get("/api/v1/learners/L2001/learning-snapshot")
    assert response.status_code == 404
    assert response.json()["detail"] == "未找到可访问的学情数据"


def test_class_learning_summary_endpoint_returns_contract() -> None:
    """班级统计 API 应返回确定性指标和可供后续 A2A 序列化的结构。"""

    response = client.get(
        "/api/v1/classes/CLASS_DANCE_01/learning-summary",
        params={
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "actor_role": "teacher",
            "actor_user_id": "T1001",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "class-learning/v1"
    assert body["class_name"] == "舞蹈一班"
    assert body["enrolled_learners"] == 1
    assert body["scheduled_lessons"] == 2
    assert body["expected_attendance_records"] == 2
    assert body["attended_records"] == 1
    assert body["absent_records"] == 1
    assert body["completion_rate"] == 0.5
    assert body["attendance_rate"] == 0.5
    assert body["learner_metrics"][0]["learner_id"] == "L1001"


def test_class_learning_summary_endpoint_hides_unauthorized_class() -> None:
    """家长或未授课教师不能读取包含多名学员的班级聚合数据。"""

    parent_response = client.get(
        "/api/v1/classes/CLASS_DANCE_01/learning-summary",
        params={
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "actor_role": "parent",
            "actor_user_id": "P1001",
        },
    )
    teacher_response = client.get(
        "/api/v1/classes/CLASS_DANCE_01/learning-summary",
        params={
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "actor_role": "teacher",
            "actor_user_id": "T1002",
        },
    )

    assert parent_response.status_code == 404
    assert teacher_response.status_code == 404
    assert parent_response.json()["detail"] == "未找到可访问的班级学情数据"


def test_class_learning_summary_endpoint_validates_query_parameters() -> None:
    """日期范围和低课时阈值错误不能进入数据库统计流程。"""

    reversed_period = client.get(
        "/api/v1/classes/CLASS_DANCE_01/learning-summary",
        params={
            "period_start": "2026-08-31",
            "period_end": "2026-08-01",
            "actor_role": "teacher",
            "actor_user_id": "T1001",
        },
    )
    invalid_threshold = client.get(
        "/api/v1/classes/CLASS_DANCE_01/learning-summary",
        params={
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "low_balance_threshold": "-1",
            "actor_role": "teacher",
            "actor_user_id": "T1001",
        },
    )

    assert reversed_period.status_code == 422
    assert "开始日期" in reversed_period.json()["detail"]
    assert invalid_threshold.status_code == 422
    assert "greater than or equal to 0" in invalid_threshold.text


def test_media_upload_review_and_presigned_url_flow() -> None:
    """媒体应经历上传、管理员审核后，家长才能获得短时访问地址。"""

    class FakeMinio:
        def __init__(self) -> None:
            self.objects = {}

        def bucket_exists(self, bucket: str) -> bool:
            return False

        def make_bucket(self, bucket: str, location: str) -> None:
            pass

        def put_object(self, bucket: str, object_key: str, stream, **kwargs) -> None:
            self.objects[object_key] = stream.read()

        def presigned_get_object(self, bucket: str, object_key: str, expires) -> str:
            assert object_key in self.objects
            return f"http://minio.test/{bucket}/{object_key}?signature=demo"

        def remove_object(self, bucket: str, object_key: str) -> None:
            self.objects.pop(object_key, None)

    store = MinioMediaStore(Settings(media_max_bytes=100), client=FakeMinio())
    app.dependency_overrides[get_media_store] = lambda: store
    try:
        response = client.post(
            "/api/v1/media/images",
            files={"file": ("teacher.png", PNG_BYTES, "image/png")},
            data={
                "title": "演示教师",
                "alt_text": "卡通教师头像",
                "source_document": "教师与校区环境.md",
                "visibility": "public_faq",
                "actor_role": "admin",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["review_status"] == "pending"
        assert "object_key" not in body
        asset_id = body["asset_id"]
        assert api_session.get(MediaAsset, asset_id) is not None

        # 待审核素材不能被家长访问，即使它的可见范围是 public_faq。
        pending = client.get(f"/api/v1/media/{asset_id}/url")
        assert pending.status_code == 404

        reviewed = client.post(
            f"/api/v1/media/{asset_id}/review?actor_role=admin",
            json={"review_status": "approved"},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["review_status"] == "approved"

        url_response = client.get(f"/api/v1/media/{asset_id}/url")
        assert url_response.status_code == 200
        assert url_response.json()["url"].startswith("http://minio.test/")
        assert url_response.json()["expires_seconds"] == 600
    finally:
        app.dependency_overrides.pop(get_media_store, None)


def test_parent_cannot_upload_media() -> None:
    """家长不能向机构媒体桶写入内容。"""

    response = client.post(
        "/api/v1/media/images",
        files={"file": ("teacher.png", PNG_BYTES, "image/png")},
        data={
            "title": "越权素材",
            "alt_text": "不应上传",
            "source_document": "unknown.md",
            "actor_role": "parent",
        },
    )
    assert response.status_code == 403
