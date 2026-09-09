"""服务规则与异常处置智能体的回答服务。

该服务与公开咨询 FAQ 使用不同的 RAGFlow Assistant，保证请假、退费、
安全和异常处置资料不会被普通课程咨询误召回。没有服务规则 Assistant
时只返回安全的不可用提示，不使用通用模型猜测机构政策。
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from backend.app.config import Settings, get_settings
from backend.app.integrations.ragflow import RagflowClient
from backend.app.schemas import AgentResponse, SourceReference
from backend.app.services.faq import sanitize_public_faq_answer


OFFLINE_SERVICE_RULES_ANSWER = (
    "服务规则查询暂时不可用，当前无法确认该办理规则。"
    "请通过官方渠道联系教务或人工客服核实。"
)


def _client(settings: Settings, ragflow: RagflowClient | None = None) -> RagflowClient:
    """创建服务规则专用客户端，优先使用独立 Assistant。"""

    if ragflow is not None:
        return ragflow
    chat_id = settings.ragflow_service_rules_chat_id or settings.ragflow_chat_id
    return RagflowClient(settings, chat_id=chat_id)


def answer_service_rules_result(
    question: str,
    *,
    ragflow: RagflowClient | None = None,
    settings: Settings | None = None,
) -> AgentResponse:
    """返回服务规则回答；RAGFlow 不可用时保持保守兜底。"""

    current = settings or get_settings()
    result = _client(current, ragflow).ask_result(question)
    if result:
        # 统一清理 RAGFlow 管理信息，避免内部引用标记进入用户端正文。
        result.answer = sanitize_public_faq_answer(result.answer)
        return result
    return AgentResponse(answer=OFFLINE_SERVICE_RULES_ANSWER, provider="offline")


def answer_service_rules_question(
    question: str,
    *,
    ragflow: RagflowClient | None = None,
    settings: Settings | None = None,
) -> str:
    """兼容同步调用方的纯文本接口。"""

    return answer_service_rules_result(question, ragflow=ragflow, settings=settings).answer


@dataclass(slots=True)
class ServiceRulesStreamChunk:
    """服务规则流式过程中的内部片段。"""

    content: str
    provider: str
    sources: list[SourceReference] = field(default_factory=list)


async def stream_service_rules_answer(
    question: str,
    *,
    ragflow: RagflowClient | None = None,
    settings: Settings | None = None,
) -> AsyncIterator[ServiceRulesStreamChunk]:
    """将服务规则 Assistant 的回答转换为统一 SSE 片段。"""

    current = settings or get_settings()
    result = await asyncio.to_thread(
        _client(current, ragflow).ask_result,
        question,
    )
    if result:
        result.answer = sanitize_public_faq_answer(result.answer)
        # 当前 RAGFlow 适配器取完整回答；这里分片只负责协议兼容。
        for index in range(0, len(result.answer), 12):
            yield ServiceRulesStreamChunk(
                result.answer[index : index + 12], "ragflow", result.sources
            )
        return

    for index in range(0, len(OFFLINE_SERVICE_RULES_ANSWER), 12):
        yield ServiceRulesStreamChunk(
            OFFLINE_SERVICE_RULES_ANSWER[index : index + 12], "offline"
        )
