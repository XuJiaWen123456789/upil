"""服务规则 Assistant 节点。"""

from typing import Any

from backend.app.schemas import AgentResponse
from backend.app.context.projectors import project_service_rules
from backend.app.services.service_rules import answer_service_rules_result
from backend.app.workflows.conversation.contracts import ConversationState


def answer_service_rules(state: ConversationState) -> dict[str, Any]:
    """查询规则知识域，不推断订单金额或其他动态事实。"""

    envelope = state.get("context_envelope")
    projection = project_service_rules(envelope) if envelope is not None else {}
    result: AgentResponse = answer_service_rules_result(
        projection.get("query") or state.get("rewritten_query") or state["message"]
    )
    return {
        "answer": result.answer,
        "provider": result.provider,
        "sources": result.sources,
    }
