"""FAQ 智能体的回答服务。

回答优先走 RAGFlow 知识库；知识库未配置或暂时不可用时，可选地走
LangChain 模型；两者都不可用时返回离线兜底话术。该顺序保证 FAQ 不会
在没有事实依据时假装给出机构政策。
"""

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from backend.app.config import Settings, get_settings
from backend.app.integrations.llm import invoke_langchain_llm, stream_langchain_llm
from backend.app.integrations.ragflow import RagflowClient
from backend.app.schemas import AgentResponse, SourceReference


OFFLINE_FAQ_ANSWER = (
    "这是 uPil 的演示咨询通道。目前可以回答课程、校区、装备、请假、调课、补课和活动等问题。"
    "正式接入知识库后，回答会附带可追溯的资料来源。"
)


# RAGFlow 可能把图号、相似度或文档名混入模型正文；这些内容属于内部审计信息。
# 这里只清理展示标记，不改写业务事实；事实约束仍由提示词和检索证据负责。
_INTERNAL_MARKER_PATTERNS = (
    re.compile(r"图\s*\d+(?:\s*图\s*\d+)*"),
    re.compile(r"(?:Top\s*\d+|相似度|关键词相似度|向量相似度|混合相似度)\s*[:：]?\s*[\d.]+%?"),
    # RAGFlow 可能把引用序号写入正文，家长端只应看到清理后的业务话术。
    re.compile(r"\[ID\s*:\s*\d+\]"),
)


def sanitize_public_faq_answer(answer: str) -> str:
    """删除公开客服正文中的内部标记，保留来源供后台审计。"""

    cleaned = answer.strip()
    for pattern in _INTERNAL_MARKER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    # 文件名仅在单独成行时删除，避免误伤普通正文。
    cleaned = re.sub(r"(?m)^\s*[\w一-龥（）()、·\-]+\.md\s*$", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\s+([，。；：！？])", r"\1", cleaned)
    return cleaned.strip(" \n\t：:，,;")


def answer_faq_question(
    question: str,
    *,
    ragflow: RagflowClient | None = None,
    settings: Settings | None = None,
) -> str:
    """按 RAGFlow、LangChain、离线话术的顺序生成 FAQ 文本，兼容旧调用方。"""

    return answer_faq_result(question, ragflow=ragflow, settings=settings).answer


def answer_faq_result(
    question: str,
    *,
    ragflow: RagflowClient | None = None,
    settings: Settings | None = None,
) -> AgentResponse:
    """按统一结果结构返回 FAQ 回答、来源和实际提供方。"""

    current = settings or get_settings()
    # 公开咨询显式使用公开 Assistant；旧配置为空时由客户端兼容回退。
    public_chat_id = current.ragflow_public_chat_id or current.ragflow_chat_id
    rag_result = (ragflow or RagflowClient(current, chat_id=public_chat_id)).ask_result(question)
    if rag_result:
        # 对外正文与内部来源分离，避免将图号、文件名和分数展示给家长。
        rag_result.answer = sanitize_public_faq_answer(rag_result.answer)
        return rag_result

    prompt = (
        "你是素质教育机构客服。只回答课程、校区、装备、请假、调课、补课和活动相关问题。"
        "如果缺少机构知识库事实，请明确说需要人工确认，不要编造政策。\n用户问题："
        f"{question}"
    )
    model_answer = invoke_langchain_llm(prompt, current)
    if model_answer:
        return AgentResponse(
            answer=sanitize_public_faq_answer(model_answer),
            provider="langchain",
        )
    return AgentResponse(answer=OFFLINE_FAQ_ANSWER, provider="offline")


@dataclass(slots=True)
class FAQStreamChunk:
    """FAQ 流式过程中的内部片段，不直接暴露给 HTTP 层。"""

    content: str
    provider: str
    sources: list[SourceReference] = field(default_factory=list)


async def stream_faq_answer(
    question: str,
    *,
    ragflow: RagflowClient | None = None,
    settings: Settings | None = None,
) -> AsyncIterator[FAQStreamChunk]:
    """按 RAGFlow、LangChain、离线回退顺序产生 FAQ 流式片段。"""

    current = settings or get_settings()
    # 公开咨询显式使用公开 Assistant，避免误读服务规则专用知识域。
    public_chat_id = current.ragflow_public_chat_id or current.ragflow_chat_id
    client = ragflow or RagflowClient(current, chat_id=public_chat_id)
    # RAGFlow 当前适配器使用同步 HTTP 客户端，因此放到线程中避免阻塞 SSE 事件循环。
    rag_result = await asyncio.to_thread(client.ask_result, question)
    if rag_result:
        # 与同步路径保持一致，SSE 正文也不暴露内部引用标记。
        rag_result.answer = sanitize_public_faq_answer(rag_result.answer)
        # RAGFlow 非流式响应也按片段输出，保证客户端协议统一；后续可替换为 RAGFlow stream API。
        for content in _split_text(rag_result.answer):
            yield FAQStreamChunk(content, "ragflow", rag_result.sources)
        return

    prompt = (
        "你是素质教育机构客服。只回答课程、校区、装备、请假、调课、补课和活动相关问题。"
        "如果缺少机构知识库事实，请明确说需要人工确认，不要编造政策。\n用户问题："
        f"{question}"
    )
    emitted = False
    async for content in stream_langchain_llm(prompt, current):
        emitted = True
        yield FAQStreamChunk(content, "langchain")
    if not emitted:
        for content in _split_text(OFFLINE_FAQ_ANSWER):
            yield FAQStreamChunk(content, "offline")


def _split_text(text: str, chunk_size: int = 12) -> list[str]:
    """将非流式文本切成稳定的小片段，避免逐字符事件造成额外开销。"""

    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]
