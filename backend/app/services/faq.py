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
from backend.app.prompts import load_prompt
from backend.app.schemas import AgentResponse, SourceReference


OFFLINE_GREETING_ANSWER = (
    "您好，我是 uPil 学习顾问。请问您想了解课程、校区、请假、课时，"
    "还是孩子的学情报告？"
)

# 课程目录属于稳定、低风险的机构基础信息。即使知识库或模型暂时不可用，
# 家长询问“都有什么课程”时也应得到可继续决策的具体答案，而不是再次看到
# 服务范围介绍。这里仅给出课程名称、建议年龄和选择入口；费用、实时名额、
# 插班及个别适配仍交由知识库或教务数据回答，避免离线常量越过事实边界。
OFFLINE_COURSE_CATALOG_ANSWER = (
    "目前课程分为四个方向：\n"
    "- 舞蹈：舞蹈启蒙班（4 至 6 岁）、中国舞基础班（6 至 12 岁）、"
    "中国舞进阶班（8 至 16 岁）；\n"
    "- 美术：少儿美术创意班（5 至 10 岁）、素描基础班（10 至 14 岁）；\n"
    "- 音乐：音乐启蒙班（4 至 8 岁）、童声合唱班（7 至 12 岁）；\n"
    "- 少儿编程：少儿编程基础班（8 至 12 岁）、编程项目实践班（10 至 14 岁）。\n"
    "您可以告诉我孩子的年龄、兴趣和是否有基础，我可以继续帮您筛选。"
    "具体班级与实时名额以校区当前安排为准。"
)

OFFLINE_FAQ_ANSWER = (
    "您好，我是 uPil 学习顾问。目前可以为您解答课程、校区、装备、请假、"
    "调课、补课和活动等问题。涉及实时名额、费用或个别安排时，我会提示您进一步确认。"
)


# 纯问候不需要访问知识库或大模型。确定性短路既能降低响应延迟，也能避免
# 外部知识服务不可用时把普通问候回答成开发阶段说明。正则只匹配整句问候，
# “你好，我想了解舞蹈课”仍会进入正常 FAQ 检索，不会丢失用户的实际问题。
_GREETING_PATTERN = re.compile(
    r"^\s*(?:你好|您好|嗨|哈喽|hello|hi|早上好|上午好|中午好|下午好|晚上好)[！!。。，,\s]*$",
    re.IGNORECASE,
)

# 课程目录问题只识别“整体有哪些课”，不拦截年龄适配、费用、试听、名额等
# 需要具体事实支撑的问题。采用多个短语模板而非单个宽泛关键词，是为了避免
# 把“课程有哪些优势”误判成课程列表查询。
_COURSE_CATALOG_PATTERNS = (
    re.compile(r"(?:有|开设|提供)(?:哪些|什么)(?:课程|课)"),
    re.compile(r"(?:课程|课)(?:都)?有(?:哪些|什么)"),
    re.compile(r"(?:全部|所有|整体)?课程(?:体系)?(?:介绍|一览|目录)"),
    re.compile(r"(?:介绍|看看|了解)(?:一下)?(?:全部|所有|整体)?课程(?:体系)?"),
)
_COURSE_DETAIL_TERMS = (
    "适合",
    "几岁",
    "年龄",
    "多久",
    "时长",
    "多少钱",
    "费用",
    "价格",
    "收费",
    "名额",
    "试听",
    "报名",
    "校区",
    "优势",
    "好处",
    "区别",
    "比较",
    "推荐",
    "怎么选",
)


def is_course_catalog_question(question: str) -> bool:
    """判断用户是否在询问整体课程目录，而非某门课程的具体规则。"""

    normalized = re.sub(r"[！!。？，,、；;：:\s]", "", question).casefold()
    if not normalized or any(term in normalized for term in _COURSE_DETAIL_TERMS):
        return False
    return any(pattern.search(normalized) for pattern in _COURSE_CATALOG_PATTERNS)


def build_offline_faq_answer(question: str) -> str:
    """根据问题选择稳定、面向真实业务场景的离线回答。"""

    if _GREETING_PATTERN.fullmatch(question):
        return OFFLINE_GREETING_ANSWER
    if is_course_catalog_question(question):
        return OFFLINE_COURSE_CATALOG_ANSWER
    return OFFLINE_FAQ_ANSWER


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

    # 纯问候和整体课程目录直接返回。两者都是稳定的低风险事实，无需为固定
    # 文案产生外部网络调用；其他 FAQ 仍按 RAGFlow、模型、离线兜底的顺序处理。
    offline_answer = build_offline_faq_answer(question)
    if offline_answer in {OFFLINE_GREETING_ANSWER, OFFLINE_COURSE_CATALOG_ANSWER}:
        return AgentResponse(answer=offline_answer, provider="offline")

    current = settings or get_settings()
    # 公开咨询只使用公开 Assistant，禁止回退到其他知识域。
    public_chat_id = current.ragflow_public_chat_id
    try:
        rag_result = (
            ragflow or RagflowClient(current, chat_id=public_chat_id)
        ).ask_result(question)
    except Exception:
        # 自定义适配器、测试桩或第三方 SDK 仍可能抛出 RAGFlow 客户端没有
        # 覆盖的异常。FAQ 边界必须把它收敛为“知识服务不可用”，不能让
        # 用户看到 HTTP 503、内部地址或供应商异常正文。
        rag_result = None
    if rag_result:
        # 对外正文与内部来源分离，避免将图号、文件名和分数展示给家长。
        rag_result.answer = sanitize_public_faq_answer(rag_result.answer)
        return rag_result

    prompt = f"{load_prompt('faq_fallback.txt')}\n用户问题：{question}"
    model_answer = invoke_langchain_llm(prompt, current)
    if model_answer:
        return AgentResponse(
            answer=sanitize_public_faq_answer(model_answer),
            provider="langchain",
        )
    return AgentResponse(answer=offline_answer, provider="offline")


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

    # 流式入口与同步入口使用同一确定性规则，保证聊天接口和图节点结果一致。
    offline_answer = build_offline_faq_answer(question)
    if offline_answer in {OFFLINE_GREETING_ANSWER, OFFLINE_COURSE_CATALOG_ANSWER}:
        for content in _split_text(offline_answer):
            yield FAQStreamChunk(content, "offline")
        return

    current = settings or get_settings()
    # 公开咨询显式使用公开 Assistant，避免误读服务规则专用知识域。
    public_chat_id = current.ragflow_public_chat_id
    client = ragflow or RagflowClient(current, chat_id=public_chat_id)
    # RAGFlow 当前适配器使用同步 HTTP 客户端，因此放到线程中避免阻塞 SSE 事件循环。
    try:
        rag_result = await asyncio.to_thread(client.ask_result, question)
    except Exception:
        # 外部检索失败后继续尝试模型/固定话术，并保证 SSE 能正常完成。
        rag_result = None
    if rag_result:
        # 与同步路径保持一致，SSE 正文也不暴露内部引用标记。
        rag_result.answer = sanitize_public_faq_answer(rag_result.answer)
        # RAGFlow 非流式响应也按片段输出，保证客户端协议统一；后续可替换为 RAGFlow stream API。
        for content in _split_text(rag_result.answer):
            yield FAQStreamChunk(content, "ragflow", rag_result.sources)
        return

    prompt = f"{load_prompt('faq_fallback.txt')}\n用户问题：{question}"
    emitted = False
    async for content in stream_langchain_llm(prompt, current):
        emitted = True
        yield FAQStreamChunk(content, "langchain")
    if not emitted:
        for content in _split_text(offline_answer):
            yield FAQStreamChunk(content, "offline")


def _split_text(text: str, chunk_size: int = 12) -> list[str]:
    """将非流式文本切成稳定的小片段，避免逐字符事件造成额外开销。"""

    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]
