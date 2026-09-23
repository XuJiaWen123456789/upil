"""人工转接节点的上下文投影。"""


def project_handoff(envelope) -> dict[str, object]:
    """人工转接只保留可解释的业务路由和追踪 ID。"""

    return {"route": envelope.route, "request_id": envelope.request_id}
