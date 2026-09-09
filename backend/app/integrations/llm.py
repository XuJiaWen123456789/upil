"""LangChain 大模型适配器。

本模块采用可选依赖策略：只有同时开启配置、提供模型参数并安装
langchain-openai 时才创建 ChatOpenAI。未配置时返回 None，由业务服务
使用可解释的离线回退，便于开发、测试和答辩演示。
"""

from collections.abc import AsyncIterator
from typing import Any

from backend.app.config import Settings, get_settings


def _message_content(message: Any) -> str:
    """将 LangChain AIMessage 的 content 统一转换成文本。"""

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    # 某些多模态模型返回文本块列表；这里只提取文本，避免把原始对象泄露给上层。
    if isinstance(content, list):
        parts = [item.get("text", "") for item in content if isinstance(item, dict)]
        return "".join(parts).strip()
    return str(content).strip()


def build_langchain_llm(settings: Settings | None = None):
    """按配置创建 LangChain ChatOpenAI 实例，无法创建时返回 None。"""

    current = settings or get_settings()
    if not current.llm_enabled or not current.llm_api_key or not current.llm_model:
        return None

    try:
        # SDK 放在可选依赖中，避免离线测试环境因未安装供应商包而启动失败。
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None

    kwargs: dict[str, Any] = {
        "api_key": current.llm_api_key,
        "model": current.llm_model,
        "temperature": current.llm_temperature,
        # 超时后由业务层走确定性回退；只允许少量 SDK 重试，避免 429 时
        # 在入口请求中长时间等待。
        "timeout": current.llm_timeout_seconds,
        "max_retries": current.llm_max_retries,
    }
    if current.llm_base_url:
        # OpenAI-compatible 服务（包括部分国产模型网关）可复用同一适配器。
        kwargs["base_url"] = current.llm_base_url
    return ChatOpenAI(**kwargs)


def invoke_langchain_llm(prompt: str, settings: Settings | None = None) -> str | None:
    """调用 LangChain 模型并返回文本；未配置或调用失败时返回 None。"""

    llm = build_langchain_llm(settings)
    if llm is None:
        return None
    try:
        return _message_content(llm.invoke(prompt)) or None
    except Exception:
        # 适配器吞掉外部服务细节，调用方可回退到安全的固定话术并记录监控。
        return None


async def stream_langchain_llm(
    prompt: str, settings: Settings | None = None
) -> AsyncIterator[str]:
    """通过 LangChain astream 输出模型片段；未配置或失败时不产生片段。"""

    llm = build_langchain_llm(settings)
    if llm is None:
        return

    try:
        # astream 能让上层在模型生成过程中立即转发片段，而不是等待完整回答。
        async for chunk in llm.astream(prompt):
            content = _message_content(chunk)
            if content:
                yield content
    except Exception:
        # 真实项目应在这里接入结构化日志和指标；用户侧由调用方执行安全回退。
        return
