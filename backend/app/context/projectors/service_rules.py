"""服务规则 Agent 的上下文投影。"""


def project_service_rules(envelope) -> dict[str, object]:
    """服务规则 Agent 不接收长期偏好和招生联系方式。"""

    return {"query": envelope.rewritten_query or envelope.message, "recent_turns": envelope.recent_turns}
