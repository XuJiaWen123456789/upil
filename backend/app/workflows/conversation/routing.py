"""对话图的确定性路由函数。"""

from typing import Any

from backend.app.workflows.conversation.contracts import ConversationState, RouteName


def classify_route(message: str) -> RouteName:
    """提供同步旧调用方使用的保守路由基线。

    SSE 主入口通常已经生成结构化计划；本函数只在调用方没有提供受控
    route 时使用，且输出始终限制在图的白名单中。
    """

    if any(keyword in message for keyword in ("人工", "投诉", "争议", "不满意")):
        return "human_handoff"
    if any(keyword in message for keyword in ("查看学习报告", "查看学情报告", "历史学情报告")):
        return "report_history"
    if any(keyword in message for keyword in (
        "学习情况", "阶段反馈", "学习进度", "近期表现", "最近表现",
        "课时", "消课", "出勤", "考勤", "缺勤",
    )):
        return "learning_summary"
    if any(
        keyword in message
        for keyword in (
            "请假",
            "补课",
            "调课",
            "调到其他时间",
            "换个时间",
            "延期",
            "顺延",
            "过期",
            "退费",
            "退款",
            "受伤",
            "过敏",
        )
    ):
        return "service_rules"
    return "faq"


def classify_intent(state: ConversationState) -> dict[str, Any]:
    """保留已规划路由，缺失时才应用确定性基线。"""

    return {"route": state.get("route") or classify_route(state["message"])}


def route_to_agent(state: ConversationState) -> RouteName:
    """读取分类节点写入的白名单路由。"""

    return state["route"]
