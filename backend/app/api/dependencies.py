"""FastAPI 依赖工厂。

本模块只负责根据统一配置组装适配器，不包含路由判断和业务查询。路由通过
这些稳定函数注入模型、MinIO 与会话存储，测试也可以覆盖同一个函数对象。
"""

from backend.app.api.runtime import conversation_store, settings
from backend.app.integrations.llm import build_langchain_llm
from backend.app.integrations.minio import MinioMediaStore
from backend.app.memory.conversation import ConversationStore
from backend.app.services.report_runtime import report_pdf_runtime_available


def get_report_store() -> MinioMediaStore | None:
    """仅在报告 PDF 功能开启时创建私有报告存储。"""

    if not settings.report_pdf_enabled or not report_pdf_runtime_available():
        return None
    return MinioMediaStore(settings)


def get_conversation_store() -> ConversationStore:
    """返回按配置创建的会话存储，不让路由绑定具体后端。"""

    return conversation_store


def get_intent_model():
    """按配置创建零温度 Supervisor；未配置时由识别服务确定性降级。

    Router 只输出受控结构化决策，不承担自然语言创作，因此温度必须固定为
    0。这里不复用全局 ``LLM_TEMPERATURE``，避免以后为了优化普通回答的
    表达多样性而意外降低路由结果的可重复性。
    """

    return build_langchain_llm(
        settings,
        model_name=settings.llm_router_model or settings.llm_model,
        temperature=0,
    )


def get_lead_intent_model():
    """创建短超时、零温度的招生意向旁路模型。"""

    return build_langchain_llm(
        settings,
        model_name=settings.lead_intent_model or settings.llm_model,
        temperature=0,
        timeout_seconds=settings.lead_intent_timeout_seconds,
    )
