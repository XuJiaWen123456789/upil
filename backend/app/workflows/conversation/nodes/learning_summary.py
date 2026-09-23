"""个人学情摘要节点。"""

from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.app.learning_contracts import LearningSummary
from backend.app.services.report_narrative import build_learning_summary_text
from backend.app.tools.learning_snapshot import execute_learning_snapshot_via_registry
from backend.app.workflows.conversation.contracts import ConversationState


def answer_learning_summary(state: ConversationState) -> dict[str, Any]:
    """读取可信数据库事实，并在本进程按固定规则生成个人学情摘要。"""

    # 家长绑定解析由 SSE 边界统一完成。多孩子、无绑定或显式越权时，
    # 这里直接返回安全提示，禁止继续查询或退回 FAQ 生成泛化答案。
    resolution_answer = state.get("learner_resolution_answer")
    if resolution_answer:
        return {"answer": resolution_answer, "provider": "database"}

    context = state.get("access_context")
    if context is None:
        return {"answer": "当前用户身份无效，请重新登录后再查询。", "provider": "workflow"}
    if context.role == "parent" and not state.get("learner_id"):
        return {
            "answer": "为了保护学员信息，请先提供已绑定的学员编号。",
            "provider": "database",
        }

    session = state.get("session")
    learner_id = state.get("learner_id")
    if session is None or learner_id is None:
        return {
            "answer": "当前缺少学情查询所需的会话信息，请转人工客服处理。",
            "provider": "database",
        }

    try:
        tool_result = execute_learning_snapshot_via_registry(
            session=session,
            context=context,
            learner_id=learner_id,
            request_id=state.get("request_id"),
            actor_role=context.role,
        )
    except SQLAlchemyError:
        return {
            "answer": "学情数据服务暂时不可用，请稍后重试或转人工客服。",
            "provider": "database",
        }

    if tool_result.status != "success":
        if tool_result.status == "denied":
            return {
                "answer": "暂未找到对应的学员数据，或当前账号无权访问该学员，请核对后转人工确认。",
                "provider": "database",
            }
        return {
            "answer": "学情数据服务暂时不可用，请稍后重试或转人工客服。",
            "provider": "database",
        }

    data = tool_result.data
    profile = data["profile"]
    balance = data["balance"]
    attendance_data = data["attendance"]
    if not all(isinstance(item, dict) for item in (profile, balance, attendance_data)):
        return {
            "answer": "学情数据服务返回结果无法校验，请转人工客服处理。",
            "provider": "database",
        }

    try:
        snapshot = LearningSummary.model_validate(data)
    except Exception:
        return {
            "answer": "学情数据服务返回结果无法校验，请转人工客服处理。",
            "provider": "database",
        }
    return {
        "answer": build_learning_summary_text(snapshot),
        "provider": "database",
    }
