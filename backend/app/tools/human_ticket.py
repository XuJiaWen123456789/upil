"""幂等人工工单创建工具。"""

from backend.app.integrations.business_adapters import (
    BusinessAdapterTimeout,
    BusinessAdapterUnavailable,
    BusinessSystemsAdapter,
    HumanTicketCommand,
    HumanTicketData,
)
from backend.app.tools.contracts import BusinessToolRequest, BusinessToolResult


def execute_human_ticket(
    request: BusinessToolRequest, *, adapter: BusinessSystemsAdapter
) -> BusinessToolResult:
    """调用工单适配器，幂等语义由适配器契约保证。"""

    command = HumanTicketCommand(
        reason=request.reason or "",
        idempotency_key=request.idempotency_key or "",
        learner_id=request.learner_id,
        order_id=request.order_id,
    )
    try:
        data: HumanTicketData = adapter.create_human_ticket(command)
    except BusinessAdapterTimeout:
        return BusinessToolResult(
            tool_name="create_human_ticket",
            status="failed",
            message="客服工单系统响应超时，请保留本次请求信息并转人工确认",
            handoff_required=True,
            error_code="TOOL_TIMEOUT",
        )
    except BusinessAdapterUnavailable:
        return BusinessToolResult(
            tool_name="create_human_ticket",
            status="failed",
            message="当前无法创建人工工单，请转人工客服处理",
            handoff_required=True,
            error_code="TOOL_UNAVAILABLE",
        )
    return BusinessToolResult(
        tool_name="create_human_ticket",
        status="success",
        message=data.message,
        data=data.model_dump(mode="json"),
    )
