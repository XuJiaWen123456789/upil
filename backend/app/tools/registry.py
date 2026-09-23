"""请求范围的业务工具注册表。"""

import time
from uuid import uuid4

from backend.app.tools.contracts import (
    BusinessToolHandler,
    BusinessToolRequest,
    BusinessToolResult,
    ToolAuditSink,
    ToolErrorCode,
    ToolName,
)
from backend.app.tools.policies import resolve_tool_policy, validate_tool_request


def _observe_result(
    result: BusinessToolResult,
    *,
    request_id: str,
    tool_call_id: str,
    route: str,
    started_at: float,
    error_code: ToolErrorCode | None = None,
) -> BusinessToolResult:
    """补齐统一追踪字段，耗时使用不受系统时钟回拨影响的单调时钟。"""

    return result.model_copy(
        update={
            "request_id": request_id,
            "tool_call_id": tool_call_id,
            "route": route,
            "duration_ms": round(max(0.0, (time.monotonic() - started_at) * 1000), 3),
            "error_code": error_code,
        }
    )


class BusinessToolRegistry:
    """只执行已注册且通过场景、身份和参数门禁的工具。"""

    def __init__(self, audit_sink: ToolAuditSink | None = None) -> None:
        self._handlers: dict[ToolName, BusinessToolHandler] = {}
        self.audit_events: list[dict[str, str | int | float | None]] = []
        self._audit_sink = audit_sink

    def register(self, tool_name: ToolName, handler: BusinessToolHandler) -> None:
        """注册由服务端选择的白名单工具实现。"""

        self._handlers[tool_name] = handler

    def execute(
        self,
        request: BusinessToolRequest,
        *,
        route: str,
        has_verified_identity: bool = False,
        actor_role: str = "system",
        request_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> BusinessToolResult:
        """执行完整门禁并返回不泄露底层异常的统一结果。"""

        trace_request_id = request_id or f"req_{uuid4().hex}"
        trace_tool_call_id = tool_call_id or f"call_{uuid4().hex}"
        started_at = time.monotonic()

        def finish(
            result: BusinessToolResult,
            error_code: ToolErrorCode | None = None,
        ) -> BusinessToolResult:
            observed = _observe_result(
                result,
                request_id=trace_request_id,
                tool_call_id=trace_tool_call_id,
                route=route,
                started_at=started_at,
                error_code=error_code,
            )
            # 审计事件不记录请求参数、联系方式或第三方异常正文。
            event: dict[str, str | int | float | None] = {
                "request_id": observed.request_id,
                "tool_call_id": observed.tool_call_id,
                "tool_name": observed.tool_name,
                "route": route,
                "status": observed.status,
                "error_code": observed.error_code,
                "duration_ms": observed.duration_ms,
                "actor_role": actor_role,
                "outcome": "success" if observed.status == "success" else "failure",
            }
            self.audit_events.append(event)
            if self._audit_sink is not None:
                self._audit_sink(event)
            return observed

        policy = resolve_tool_policy(route)
        if policy is None or request.tool_name not in policy.allowed_tools:
            return finish(
                BusinessToolResult(
                    tool_name=request.tool_name,
                    status="denied",
                    message="当前业务场景不允许调用该工具",
                    handoff_required=True,
                ),
                "TOOL_ACCESS_DENIED",
            )
        if policy.requires_identity and not has_verified_identity:
            return finish(
                BusinessToolResult(
                    tool_name=request.tool_name,
                    status="denied",
                    message="该业务工具需要先完成身份核验",
                    handoff_required=True,
                ),
                "TOOL_ACCESS_DENIED",
            )
        error = validate_tool_request(request)
        if error:
            return finish(
                BusinessToolResult(
                    tool_name=request.tool_name, status="invalid", message=error
                ),
                "TOOL_INVALID_ARGUMENT",
            )
        handler = self._handlers.get(request.tool_name)
        if handler is None:
            return finish(
                BusinessToolResult(
                    tool_name=request.tool_name,
                    status="not_implemented",
                    message="当前业务系统尚未接入，暂时无法取得可信的动态结果",
                    handoff_required=True,
                ),
                "TOOL_NOT_IMPLEMENTED",
            )
        try:
            result = handler(request)
            if result.tool_name != request.tool_name:
                return finish(
                    BusinessToolResult(
                        tool_name=request.tool_name,
                        status="failed",
                        message="业务工具返回结果无法校验",
                        handoff_required=True,
                    ),
                    "TOOL_EXECUTION_FAILED",
                )
            return finish(result, result.error_code)
        except Exception:
            # SQL、地址、凭据和第三方响应都不能进入用户可见结果。
            return finish(
                BusinessToolResult(
                    tool_name=request.tool_name,
                    status="failed",
                    message="业务工具暂时不可用，请转人工客服处理",
                    handoff_required=True,
                ),
                "TOOL_EXECUTION_FAILED",
            )
