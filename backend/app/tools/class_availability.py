"""班级名额只读查询工具。"""

from backend.app.integrations.business_adapters import (
    BusinessAdapterTimeout,
    BusinessAdapterUnavailable,
    BusinessSystemsAdapter,
    ClassAvailabilityData,
    ClassAvailabilityQuery,
)
from backend.app.tools.contracts import BusinessToolRequest, BusinessToolResult


def execute_class_availability(
    request: BusinessToolRequest, *, adapter: BusinessSystemsAdapter
) -> BusinessToolResult:
    """调用显式注入的教务适配器，失败时不伪造动态名额。"""

    query = ClassAvailabilityQuery(
        course_id=request.course_id,
        course_name=request.course_name,
        campus_id=request.campus_id,
        campus_name=request.campus_name,
    )
    try:
        data: ClassAvailabilityData = adapter.query_class_availability(query)
    except BusinessAdapterTimeout:
        return BusinessToolResult(
            tool_name="class_availability",
            status="failed",
            message="教务系统响应超时，请稍后重试或转人工客服",
            handoff_required=True,
            error_code="TOOL_TIMEOUT",
        )
    except BusinessAdapterUnavailable:
        return BusinessToolResult(
            tool_name="class_availability",
            status="failed",
            message="当前无法取得可信的班级名额，请转人工客服确认",
            handoff_required=True,
            error_code="TOOL_UNAVAILABLE",
        )
    return BusinessToolResult(
        tool_name="class_availability",
        status="success",
        message="班级名额查询成功",
        data=data.model_dump(mode="json"),
    )
