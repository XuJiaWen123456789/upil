"""工作流场景到业务工具的显式授权策略。"""

from dataclasses import dataclass

from backend.app.tools.contracts import BusinessToolRequest, ToolName


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """一个受控业务场景允许调用的工具集合。"""

    route: str
    allowed_tools: tuple[ToolName, ...]
    requires_identity: bool
    write_operation: bool


# 路由由工作流决定，工具层只验证显式映射，不接受模型新增路由。
TOOL_POLICIES: dict[str, ToolPolicy] = {
    "learning_summary": ToolPolicy(
        "learning_summary", ("learning_snapshot",), True, False
    ),
    "schedule_or_seat": ToolPolicy(
        "schedule_or_seat", ("class_availability",), False, False
    ),
    "fee_refund": ToolPolicy(
        "fee_refund", ("order_status", "create_human_ticket"), True, False
    ),
    "complaint": ToolPolicy(
        "complaint", ("create_human_ticket",), True, True
    ),
    "human_handoff": ToolPolicy(
        "human_handoff", ("create_human_ticket",), False, True
    ),
}


def resolve_tool_policy(route: str) -> ToolPolicy | None:
    """查询固定工具策略；未知路由默认无权限。"""

    return TOOL_POLICIES.get(route)


def validate_tool_request(request: BusinessToolRequest) -> str | None:
    """执行跨工具的必填参数检查，返回稳定提示。"""

    if request.tool_name == "learning_snapshot" and not request.learner_id:
        return "查询学情快照必须提供学员编号"
    if request.tool_name == "class_availability":
        if not request.course_id and not request.course_name:
            return "查询班级名额必须提供课程信息"
        if not request.campus_id and not request.campus_name:
            return "查询班级名额必须提供校区信息"
    if request.tool_name == "order_status" and not request.order_id:
        return "查询订单状态必须提供订单编号"
    if request.tool_name == "create_human_ticket":
        if not request.reason or not request.reason.strip():
            return "创建人工工单必须提供问题说明"
        if not request.idempotency_key:
            return "创建人工工单必须提供幂等键"
    return None
