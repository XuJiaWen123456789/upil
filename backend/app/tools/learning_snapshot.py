"""授权学情快照查询工具。"""

from sqlalchemy.orm import Session

from backend.app.services.access_control import AccessContext
from backend.app.tools.contracts import BusinessToolRequest, BusinessToolResult
from backend.app.tools.learning_tools import query_learning_snapshot
from backend.app.tools.registry import BusinessToolRegistry


def execute_learning_snapshot(
    request: BusinessToolRequest,
    *,
    session: Session,
    context: AccessContext,
) -> BusinessToolResult:
    """查询经过资源授权的快照，并只输出结构化契约字段。"""

    if request.tool_name != "learning_snapshot" or not request.learner_id:
        return BusinessToolResult(
            tool_name="learning_snapshot", status="invalid", message="学情工具请求参数无效"
        )
    snapshot = query_learning_snapshot(session, context, request.learner_id)
    if snapshot is None:
        return BusinessToolResult(
            tool_name="learning_snapshot",
            status="denied",
            message="未找到可访问的学情数据",
            handoff_required=True,
        )
    data = {
        key: value.model_dump(mode="json")
        if hasattr(value, "model_dump")
        else [item.model_dump(mode="json") for item in value]
        if isinstance(value, list)
        else value
        for key, value in snapshot.items()
    }
    return BusinessToolResult(
        tool_name="learning_snapshot", status="success", message="学情查询成功", data=data
    )


def build_demo_business_registry(
    *, session: Session, context: AccessContext
) -> BusinessToolRegistry:
    """创建请求范围注册表，只启用已连接本地数据库的学情工具。"""

    registry = BusinessToolRegistry()
    registry.register(
        "learning_snapshot",
        lambda request: execute_learning_snapshot(request, session=session, context=context),
    )
    return registry


def execute_learning_snapshot_via_registry(
    *,
    session: Session,
    context: AccessContext,
    learner_id: str,
    request_id: str | None = None,
    actor_role: str = "system",
) -> BusinessToolResult:
    """供工作流使用统一注册表调用学情工具。"""

    request = BusinessToolRequest(tool_name="learning_snapshot", learner_id=learner_id)
    registry = build_demo_business_registry(session=session, context=context)
    return registry.execute(
        request,
        route="learning_summary",
        has_verified_identity=True,
        actor_role=actor_role,
        request_id=request_id,
    )
