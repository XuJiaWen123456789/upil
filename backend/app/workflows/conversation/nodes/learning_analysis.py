"""统一学情分析 Agent 节点。

LangGraph 只注册一个学情分析 Agent；个人摘要、家长报告和教师班级统计仍由
各自的单职责处理器执行，避免把三套权限和数据口径重新堆回同一个大文件。
"""

from typing import Any

from backend.app.workflows.conversation.contracts import ConversationState
from backend.app.context.projectors import project_learning_analysis
from backend.app.workflows.conversation.nodes.class_learning_summary import (
    answer_class_learning_summary,
)
from backend.app.workflows.conversation.nodes.learning_report import answer_learning_report
from backend.app.workflows.conversation.nodes.learning_summary import answer_learning_summary


def answer_learning_analysis(state: ConversationState) -> dict[str, Any]:
    """按 Supervisor 已确定的业务路由分发到对应学情处理器。"""

    envelope = state.get("context_envelope")
    if envelope is not None:
        # 投影只用于明确学情 Agent 的可见范围；课时、出勤和报告状态仍必须
        # 由下游授权工具重新读取，不能把摘要当作业务事实。
        project_learning_analysis(envelope)
    route = state.get("route")
    if route == "learning_report":
        return answer_learning_report(state)
    if route == "class_learning_summary":
        return answer_class_learning_summary(state)
    return answer_learning_summary(state)
