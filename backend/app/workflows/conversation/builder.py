"""LangGraph 图结构构建器。

本模块只声明节点和边，不包含节点业务、Prompt、工具实现或通信协议。
"""

from langgraph.graph import END, START, StateGraph

from backend.app.workflows.conversation.contracts import ConversationState
from backend.app.workflows.conversation.nodes import (
    answer_clarification,
    answer_faq,
    answer_human_handoff,
    answer_learning_analysis,
    answer_report_history,
    answer_service_rules,
    answer_small_talk,
    answer_out_of_scope,
)
from backend.app.workflows.conversation.routing import classify_intent, route_to_agent


def build_conversation_graph():
    """构建单路由、单业务分支的 uPil 对话图。"""

    graph = StateGraph(ConversationState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("faq_agent", answer_faq)
    graph.add_node("service_rules_agent", answer_service_rules)
    graph.add_node("learning_analysis_agent", answer_learning_analysis)
    graph.add_node("report_history", answer_report_history)
    graph.add_node("human_handoff", answer_human_handoff)
    graph.add_node("clarification", answer_clarification)
    graph.add_node("small_talk", answer_small_talk)
    graph.add_node("out_of_scope", answer_out_of_scope)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_to_agent,
        {
            "faq": "faq_agent",
            "service_rules": "service_rules_agent",
            "learning_summary": "learning_analysis_agent",
            "class_learning_summary": "learning_analysis_agent",
            "learning_report": "learning_analysis_agent",
            "report_history": "report_history",
            "human_handoff": "human_handoff",
            "clarification": "clarification",
            "small_talk": "small_talk",
            "out_of_scope": "out_of_scope",
        },
    )
    for node_name in (
        "faq_agent",
        "service_rules_agent",
        "learning_analysis_agent",
        "report_history",
        "human_handoff",
        "clarification",
        "small_talk",
        "out_of_scope",
    ):
        graph.add_edge(node_name, END)
    return graph.compile()


conversation_graph = build_conversation_graph()
