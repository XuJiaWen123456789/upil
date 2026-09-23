"""公开 FAQ 回答节点。"""

from typing import Any

from backend.app.schemas import AgentResponse
from backend.app.context.projectors import project_faq
from backend.app.services.faq import answer_faq_result
from backend.app.workflows.conversation.contracts import ConversationState


def answer_faq(state: ConversationState) -> dict[str, Any]:
    """查询公开知识服务并返回统一回答、提供方和来源。"""

    envelope = state.get("context_envelope")
    projection = project_faq(envelope) if envelope is not None else {}
    result: AgentResponse = answer_faq_result(
        projection.get("query") or state.get("rewritten_query") or state["message"]
    )
    return {
        "answer": result.answer,
        "provider": result.provider,
        "sources": result.sources,
    }
