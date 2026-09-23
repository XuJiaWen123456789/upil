"""订单状态只读查询工具。"""

from backend.app.integrations.business_adapters import (
    BusinessAdapterTimeout,
    BusinessAdapterUnavailable,
    BusinessSystemsAdapter,
    OrderStatusData,
    OrderStatusQuery,
)
from backend.app.tools.contracts import BusinessToolRequest, BusinessToolResult


def execute_order_status(
    request: BusinessToolRequest, *, adapter: BusinessSystemsAdapter
) -> BusinessToolResult:
    """读取受控订单状态，不计算或承诺最终退款金额。"""

    query = OrderStatusQuery(order_id=request.order_id or "")
    try:
        data: OrderStatusData = adapter.query_order_status(query)
    except BusinessAdapterTimeout:
        return BusinessToolResult(
            tool_name="order_status",
            status="failed",
            message="订单系统响应超时，请稍后重试或转人工客服",
            handoff_required=True,
            error_code="TOOL_TIMEOUT",
        )
    except BusinessAdapterUnavailable:
        return BusinessToolResult(
            tool_name="order_status",
            status="failed",
            message="当前无法取得可信的订单状态，请转人工客服确认",
            handoff_required=True,
            error_code="TOOL_UNAVAILABLE",
        )
    return BusinessToolResult(
        tool_name="order_status",
        status="success",
        message="订单状态查询成功",
        data=data.model_dump(mode="json"),
    )
