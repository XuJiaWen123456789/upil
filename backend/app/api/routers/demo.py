"""本地开发专用的受限业务工具联调路由。"""

import json
import logging

from fastapi import APIRouter, HTTPException, Request

from backend.app.api.dependencies import settings
from backend.app.integrations.business_adapters import (
    ClassAvailabilityData,
    FakeBusinessSystemsAdapter,
)
from backend.app.schemas import DemoClassAvailabilityRequest
from backend.app.tools.adapter_registry import register_business_system_adapter
from backend.app.tools.contracts import BusinessToolRequest, BusinessToolResult
from backend.app.tools.registry import BusinessToolRegistry


logger = logging.getLogger(__name__)
router = APIRouter()


def emit_safe_tool_audit(event: dict[str, str | int | float | None]) -> None:
    """输出契约化工具日志，不记录原始问题和业务请求参数。"""

    logger.info("business_tool_audit %s", json.dumps(event, ensure_ascii=False))


@router.post(
    "/api/v1/internal/demo/class-availability",
    response_model=BusinessToolResult,
)
async def demo_class_availability(
    request: DemoClassAvailabilityRequest,
    http_request: Request,
) -> BusinessToolResult:
    """在非生产环境执行固定只读班级名额查询。"""

    if settings.app_env.lower() not in {"development", "test", "local"}:
        raise HTTPException(status_code=404, detail="接口不存在")
    adapter = FakeBusinessSystemsAdapter(
        availability={
            ("中国舞基础班", "星河中心校区"): ClassAvailabilityData(
                course_name="中国舞基础班",
                campus_name="星河中心校区",
                available_seats=3,
                schedule_options=["周六 10:00"],
                checked_at="2026-09-07T12:00:00+08:00",
            )
        }
    )
    registry = BusinessToolRegistry(audit_sink=emit_safe_tool_audit)
    register_business_system_adapter(registry, adapter=adapter)
    result = registry.execute(
        BusinessToolRequest(
            tool_name="class_availability",
            course_name=request.course_name,
            campus_name=request.campus_name,
        ),
        route="schedule_or_seat",
        actor_role="demo",
        request_id=http_request.state.request_id,
    )
    if result.status == "success":
        result = result.model_copy(
            update={"message": "班级名额查询完成；当前结果仅供参考，实时名额以教务系统为准"}
        )
    return result
