"""家长学情报告节点。"""

from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.app.services.learning_reports import (
    ReportPeriodResolutionError,
    build_learning_report_snapshot,
)
from backend.app.services.report_execution import execute_parent_report
from backend.app.workflows.conversation.contracts import ConversationState


def answer_learning_report(state: ConversationState) -> dict[str, Any]:
    """构建授权快照并调用家长报告领域执行服务。"""

    resolution_answer = state.get("learner_resolution_answer")
    if resolution_answer:
        return {"answer": resolution_answer, "provider": "workflow"}

    context = state.get("access_context")
    if context is None or context.role != "parent":
        return {
            "answer": "当前学情报告入口仅支持已登录家长查询本人绑定的学员。",
            "provider": "workflow",
        }
    learner_id = state.get("learner_id")
    if not learner_id:
        return {
            "answer": "为了保护学员信息，请先提供已绑定的学员编号，并说明报告周期。",
            "provider": "workflow",
        }
    session = state.get("session")
    if session is None:
        return {
            "answer": "当前缺少生成学情报告所需的会话信息，请稍后重试。",
            "provider": "database",
        }
    try:
        snapshot = build_learning_report_snapshot(
            session,
            context,
            learner_id,
            state.get("rewritten_query") or state["message"],
        )
    except ReportPeriodResolutionError:
        return {"answer": "请说明报告周期，例如上个月、本月、最近30天或具体起止日期。", "provider": "workflow"}
    except SQLAlchemyError:
        session.rollback()
        return {"answer": "学情数据服务暂时不可用，未生成报告，请稍后重试。", "provider": "database"}
    if snapshot is None:
        return {"answer": "暂未找到可访问的学员数据，请核对绑定关系后再试。", "provider": "database"}

    execution = execute_parent_report(
        session,
        requester_id=context.user_id,
        snapshot=snapshot,
        request_id=state.get("request_id") or "report_chat_request",
        store=state.get("report_store"),
        settings=state.get("report_pdf_settings"),
    )
    return {
        "answer": execution.markdown or execution.message,
        "provider": execution.provider,
        "report_task_id": execution.task.id,
        "report_status": execution.status,
    }
