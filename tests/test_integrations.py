"""LangChain、RAGFlow 和 FAQ 流式适配器的离线契约测试。"""

import pytest

from backend.app.config import Settings
from backend.app.schemas import AgentResponse
from backend.app.services import faq as faq_service
from backend.app.integrations.ragflow import RagflowClient
from backend.app.services.faq import (
    OFFLINE_FAQ_ANSWER,
    answer_faq_question,
    sanitize_public_faq_answer,
    stream_faq_answer,
)


def test_faq_has_safe_offline_fallback() -> None:
    """未配置外部服务时，FAQ 仍返回稳定的离线话术。"""

    settings = Settings(ragflow_api_key="", ragflow_chat_id="", llm_enabled=False)
    assert answer_faq_question("请问校区在哪里", settings=settings) == OFFLINE_FAQ_ANSWER


def test_ragflow_requires_complete_configuration() -> None:
    """缺少 API Key 或 Chat ID 时不应发起外部请求。"""

    client = RagflowClient(Settings(ragflow_api_key="", ragflow_chat_id=""))
    assert client.ask("请问如何请假") is None


def test_ragflow_extracts_openai_compatible_content() -> None:
    """RAGFlow OpenAI 兼容响应应被转换成普通文本。"""

    data = {"choices": [{"message": {"content": "请按校区规则办理。"}}]}
    assert RagflowClient._extract_content(data) == "请按校区规则办理。"


def test_ragflow_extracts_limited_source_references() -> None:
    """来源应只保留有限条数和短片段，避免将知识库原文大量返回。"""

    data = {
        "references": [
            {
                "chunk_id": "chunk-1",
                "document_name": "请假制度.md",
                "content": "A" * 800,
                "similarity": 0.92,
            }
        ]
    }
    sources = RagflowClient._extract_sources(data)
    assert len(sources) == 1
    assert sources[0].source_id == "chunk-1"
    assert sources[0].title == "请假制度.md"
    assert len(sources[0].snippet or "") == 500
    assert sources[0].score == pytest.approx(0.92)


def test_ragflow_extracts_v027_nested_references_and_image_id() -> None:
    """RAGFlow v0.27 的 message.reference.chunks 应转换为统一来源。"""

    data = {
        "choices": [
            {
                "message": {
                    "content": "舞蹈课程有助于提升身体协调性。",
                    "reference": {
                        "chunks": [
                            {
                                "id": "chunk-v027-1",
                                "document_name": "课程价值与能力培养.md",
                                "content": "舞蹈课程通过节奏训练和动作练习培养身体协调性。",
                                "image_id": "asset-course-1",
                                "similarity": 0.87,
                            }
                        ]
                    },
                }
            }
        ]
    }

    sources = RagflowClient._extract_sources(data)
    assert len(sources) == 1
    assert sources[0].source_id == "chunk-v027-1"
    assert sources[0].title == "课程价值与能力培养.md"
    assert sources[0].media_asset_id == "asset-course-1"
    assert sources[0].score == pytest.approx(0.87)


def test_ragflow_extracts_direct_message_reference_list() -> None:
    """当前 RAGFlow 返回 message.reference 列表时应正确提取来源。"""

    data = {
        "choices": [
            {
                "message": {
                    "content": "课堂设备由机构提供。",
                    "reference": [
                        {
                            "id": "chunk-current-1",
                            "document_name": "课程装备准备要求.md",
                            "content": "少儿编程课程的课堂电脑和基础软件由机构提供。",
                            "similarity": 0.8165,
                        }
                    ],
                }
            }
        ]
    }

    sources = RagflowClient._extract_sources(data)

    assert len(sources) == 1
    assert sources[0].source_id == "chunk-current-1"
    assert sources[0].title == "课程装备准备要求.md"
    assert sources[0].snippet == "少儿编程课程的课堂电脑和基础软件由机构提供。"
    assert sources[0].score == pytest.approx(0.8165)


def test_ragflow_deduplicates_same_document_and_keeps_best_chunk() -> None:
    """同一文档的多个切片只保留分数最高者，避免来源列表重复。"""

    data = {
        "references": [
            {
                "id": "chunk-low",
                "document_name": "课程装备准备要求.md",
                "content": "较低相关性的装备说明。",
                "similarity": 0.61,
            },
            {
                "id": "chunk-best",
                "document_name": "课程装备准备要求.md",
                "content": "课堂电脑和基础软件由机构提供。",
                "similarity": 0.91,
            },
            {
                "id": "chunk-other",
                "document_name": "课程介绍与适龄建议.md",
                "content": "少儿编程基础班的设备说明。",
                "similarity": 0.82,
            },
        ]
    }

    sources = RagflowClient._extract_sources(data)

    assert [source.title for source in sources] == [
        "课程装备准备要求.md",
        "课程介绍与适龄建议.md",
    ]
    assert sources[0].source_id == "chunk-best"
    assert sources[0].score == pytest.approx(0.91)


def test_ragflow_returns_empty_sources_for_missing_or_invalid_references() -> None:
    """缺少引用或引用格式异常时应安全返回空列表，不抛出异常。"""

    assert RagflowClient._extract_sources({"choices": [{"message": {}}]}) == []
    assert (
        RagflowClient._extract_sources(
            {"choices": [{"message": {"reference": {"chunks": "invalid"}}}]}
        )
        == []
    )


def test_ragflow_ignores_non_mapping_references() -> None:
    """引用列表中的异常元素不能影响其他合法来源的解析。"""

    data = {
        "choices": [
            {
                "message": {
                    "reference": [
                        "invalid-reference",
                        {
                            "id": "chunk-valid-1",
                            "document_name": "公开咨询FAQ.md",
                            "content": "试听安排以课程顾问确认结果为准。",
                        },
                    ]
                }
            }
        ]
    }

    sources = RagflowClient._extract_sources(data)

    assert len(sources) == 1
    assert sources[0].source_id == "chunk-valid-1"


def test_ragflow_uses_recommended_openai_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """客户端应调用推荐路径并显式请求可追溯引用。"""

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "请参考课程手册。"}}]}

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("backend.app.integrations.ragflow.httpx.post", fake_post)
    settings = Settings(
        ragflow_base_url="http://localhost:19380/",
        ragflow_api_key="test-ragflow-key",
        ragflow_chat_id="chat-demo-1",
    )

    result = RagflowClient(settings).ask_result("舞蹈课有什么好处")

    assert result is not None
    assert result.provider == "ragflow"
    assert captured["url"] == (
        "http://localhost:19380/api/v1/openai/chat-demo-1/chat/completions"
    )
    assert captured["headers"] == {"Authorization": "Bearer test-ragflow-key"}
    assert captured["timeout"] == 15.0
    assert captured["json"] == {
        "model": "model",
        "messages": [{"role": "user", "content": "舞蹈课有什么好处"}],
        "stream": False,
        "extra_body": {"reference": True},
    }


def test_ragflow_supports_explicit_assistant_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """不同业务智能体传入显式 Chat ID 时，不能误用旧的默认 Chat ID。"""

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "服务规则回答"}}]}

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr("backend.app.integrations.ragflow.httpx.post", fake_post)
    settings = Settings(
        ragflow_base_url="http://localhost:19380",
        ragflow_api_key="test-key",
        ragflow_chat_id="legacy-chat",
    )

    result = RagflowClient(settings, chat_id="service-rules-chat").ask_result("如何请假")

    assert result is not None
    assert captured["url"] == (
        "http://localhost:19380/api/v1/openai/service-rules-chat/chat/completions"
    )


def test_service_rules_uses_its_dedicated_assistant(monkeypatch: pytest.MonkeyPatch) -> None:
    """服务规则服务应使用服务规则 Chat ID，而不是公开咨询 Chat ID。"""

    from backend.app.services import service_rules

    used: dict[str, object] = {}

    class FakeClient:
        def __init__(self, settings: Settings, chat_id: str | None = None) -> None:
            used["chat_id"] = chat_id

        def ask_result(self, question: str) -> AgentResponse:
            return AgentResponse(answer="请按服务规则办理。", provider="ragflow")

    monkeypatch.setattr(service_rules, "RagflowClient", FakeClient)
    settings = Settings(
        ragflow_api_key="test-key",
        ragflow_chat_id="public-legacy",
        ragflow_service_rules_chat_id="service-rules-chat",
    )

    result = service_rules.answer_service_rules_result("如何请假", settings=settings)

    assert result.answer == "请按服务规则办理。"
    assert used["chat_id"] == "service-rules-chat"


def test_ragflow_result_contains_provider_and_sources() -> None:
    """RAGFlow 统一结果应同时包含回答提供方和来源列表。"""

    class FakeRagflow:
        def ask_result(self, question: str) -> AgentResponse:
            return AgentResponse(
                answer="请参考请假制度。",
                provider="ragflow",
                sources=[{"source_id": "chunk-1", "title": "请假制度.md"}],
            )

    result = faq_service.answer_faq_result("如何请假", ragflow=FakeRagflow())
    assert result.provider == "ragflow"
    assert result.sources[0].source_id == "chunk-1"


@pytest.mark.anyio
async def test_faq_stream_uses_offline_chunks_when_external_services_disabled() -> None:
    """没有外部配置时仍应产生多个稳定片段，而不是一次性阻塞返回。"""

    settings = Settings(ragflow_api_key="", ragflow_chat_id="", llm_enabled=False)
    chunks = [
        chunk
        async for chunk in stream_faq_answer("请问校区在哪里", settings=settings)
    ]
    assert chunks
    assert all(chunk.provider == "offline" for chunk in chunks)
    assert "".join(chunk.content for chunk in chunks) == OFFLINE_FAQ_ANSWER
    assert all(len(chunk.content) <= 12 for chunk in chunks)


@pytest.mark.anyio
async def test_faq_stream_forwards_langchain_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """LangChain 异步片段应原样进入 FAQ 流式服务，并标记提供方。"""

    async def fake_stream(prompt: str, settings: Settings):
        yield "第一段"
        yield "第二段"

    monkeypatch.setattr(faq_service, "stream_langchain_llm", fake_stream)
    settings = Settings(ragflow_api_key="", ragflow_chat_id="", llm_enabled=True)
    chunks = [
        chunk
        async for chunk in stream_faq_answer("请问如何请假", settings=settings)
    ]
    assert [(chunk.provider, chunk.content) for chunk in chunks] == [
        ("langchain", "第一段"),
        ("langchain", "第二段"),
    ]


def test_public_faq_answer_removes_internal_markers() -> None:
    """公开正文删除图号、分数、引用序号和单独成行文件名，但保留业务事实。"""

    answer = "编程课无需提前购买电脑图 1[ID:0]。课堂设备由机构提供。\n课程介绍与适龄建议.md"
    cleaned = sanitize_public_faq_answer(answer)
    assert "图 1" not in cleaned
    assert "[ID:0]" not in cleaned
    assert "课程介绍与适龄建议.md" not in cleaned
    assert "无需提前购买电脑" in cleaned
    assert "课堂设备由机构提供" in cleaned
