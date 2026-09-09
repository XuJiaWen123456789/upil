"""客服业务工具契约与安全执行边界。

本模块不把业务工具实现成“让模型自由调用的函数集合”，而是先定义：

1. 哪些工具属于只读查询，哪些工具属于申请或人工处理；
2. 每个工具允许接收哪些参数；
3. 工具未接入或执行失败时，系统如何安全降级。

当前只有 learning_snapshot 已经连接本地演示数据库。班级名额、订单状态
和人工工单先保留严格契约，未接入时不得返回猜测数据。
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from backend.app.services.access_control import AccessContext
from backend.app.tools.learning_tools import query_learning_snapshot
from backend.app.integrations.business_adapters import (
    BusinessAdapterTimeout,
    BusinessAdapterUnavailable,
    BusinessSystemsAdapter,
    ClassAvailabilityData,
    ClassAvailabilityQuery,
    HumanTicketCommand,
    HumanTicketData,
    OrderStatusData,
    OrderStatusQuery,
)


# 工具名称采用白名单，防止模型输出任意 Python 函数名或系统命令。
ToolName = Literal[
    "learning_snapshot",
    "class_availability",
    "order_status",
    "create_human_ticket",
]

ToolStatus = Literal["success", "invalid", "denied", "not_implemented", "failed"]
# 对外只暴露稳定错误码，不把底层数据库、HTTP 客户端或第三方异常文本传出去。
ToolErrorCode = Literal[
    "TOOL_INVALID_ARGUMENT",
    "TOOL_ACCESS_DENIED",
    "TOOL_NOT_IMPLEMENTED",
    "TOOL_TIMEOUT",
    "TOOL_UNAVAILABLE",
    "TOOL_EXECUTION_FAILED",
]


class BusinessToolRequest(BaseModel):
    """所有业务工具共用的受控请求体。

    extra=forbid 是关键安全边界：即使用户通过 Prompt Injection 诱导模型
    添加 password、sql 或 command 字段，这些字段也不会进入工具执行层。
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: ToolName
    learner_id: str | None = Field(default=None, max_length=64)
    course_id: str | None = Field(default=None, max_length=64)
    course_name: str | None = Field(default=None, max_length=100)
    campus_id: str | None = Field(default=None, max_length=64)
    campus_name: str | None = Field(default=None, max_length=100)
    order_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class BusinessToolResult(BaseModel):
    """工具执行结果契约。

    data 只允许由服务端工具写入；模型不能通过请求体直接注入结果。
    handoff_required 用于强制上层工作流执行人工兜底，而不是继续生成答案。
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: ToolName
    status: ToolStatus
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    handoff_required: bool = False
    # request_id 贯穿一次上游请求，tool_call_id 标识其中一次具体工具调用。
    request_id: str = Field(default_factory=lambda: f"req_{uuid4().hex}")
    tool_call_id: str = Field(default_factory=lambda: f"call_{uuid4().hex}")
    # 接口级观测字段只描述执行情况，不保存原始用户问题或业务敏感数据。
    route: str | None = None
    duration_ms: float = Field(default=0.0, ge=0)
    error_code: ToolErrorCode | None = None


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """一个工作流场景允许使用的工具策略。"""

    route: str
    allowed_tools: tuple[ToolName, ...]
    requires_identity: bool
    write_operation: bool


# 路由到工具的映射是显式配置，不允许模型自行决定调用任意工具。
TOOL_POLICIES: dict[str, ToolPolicy] = {
    "learning_summary": ToolPolicy(
        route="learning_summary",
        allowed_tools=("learning_snapshot",),
        requires_identity=True,
        write_operation=False,
    ),
    "schedule_or_seat": ToolPolicy(
        route="schedule_or_seat",
        allowed_tools=("class_availability",),
        requires_identity=False,
        write_operation=False,
    ),
    "fee_refund": ToolPolicy(
        route="fee_refund",
        allowed_tools=("order_status", "create_human_ticket"),
        requires_identity=True,
        write_operation=False,
    ),
    "complaint": ToolPolicy(
        route="complaint",
        allowed_tools=("create_human_ticket",),
        requires_identity=True,
        write_operation=True,
    ),
    "human_handoff": ToolPolicy(
        route="human_handoff",
        allowed_tools=("create_human_ticket",),
        requires_identity=False,
        write_operation=True,
    ),
}


def resolve_tool_policy(route: str) -> ToolPolicy | None:
    """按受控路由返回工具策略；未知路由不允许调用业务工具。"""

    return TOOL_POLICIES.get(route)


def validate_tool_request(request: BusinessToolRequest) -> str | None:
    """执行工具级参数校验，返回用户可理解的错误原因。"""

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


class BusinessToolHandler(Protocol):
    """业务工具实现的最小协议，便于接入真实教务或订单 API。"""

    def __call__(self, request: BusinessToolRequest) -> BusinessToolResult:
        """执行一个已经通过白名单和参数校验的请求。"""


ToolAuditSink = Callable[[dict[str, str | int | float | None]], None]


def _new_request_id() -> str:
    """生成不含业务信息的请求追踪 ID。"""

    return f"req_{uuid4().hex}"


def _new_tool_call_id() -> str:
    """生成一次工具调用的唯一 ID，便于定位重试和重复调用。"""

    return f"call_{uuid4().hex}"


def _observe_result(
    result: BusinessToolResult,
    *,
    request_id: str,
    tool_call_id: str,
    route: str | None,
    started_at: float,
    error_code: ToolErrorCode | None = None,
) -> BusinessToolResult:
    """补齐统一观测字段；耗时采用单调时钟，避免系统时间回拨影响统计。"""

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
    """只执行已注册的业务工具，未注册工具统一安全降级。"""

    def __init__(self, audit_sink: ToolAuditSink | None = None) -> None:
        self._handlers: dict[ToolName, BusinessToolHandler] = {}
        # 默认保留进程内安全事件，便于本地测试；生产环境可注入结构化日志 sink。
        self.audit_events: list[dict[str, str | int | float | None]] = []
        self._audit_sink = audit_sink

    def register(self, tool_name: ToolName, handler: BusinessToolHandler) -> None:
        """注册服务端实现；调用方不能注册白名单外名称。"""

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
        """校验路由、身份、参数后执行工具。"""

        # ID 必须由服务端生成或由可信上游传入，不能由模型参数控制。
        trace_request_id = request_id or _new_request_id()
        trace_tool_call_id = tool_call_id or _new_tool_call_id()
        started_at = time.monotonic()

        def finish(
            result: BusinessToolResult,
            error_code: ToolErrorCode | None = None,
        ) -> BusinessToolResult:
            """统一写入结果字段并输出脱敏审计事件。"""

            observed = _observe_result(
                result,
                request_id=trace_request_id,
                tool_call_id=trace_tool_call_id,
                route=route,
                started_at=started_at,
                error_code=error_code,
            )
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
                    tool_name=request.tool_name,
                    status="invalid",
                    message=error,
                ),
                "TOOL_INVALID_ARGUMENT",
            )
        handler = self._handlers.get(request.tool_name)
        if handler is None:
            # 未接入真实系统时不能模拟动态数据，必须显式转人工。
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
            # 工具实现返回的名称也必须与请求一致，防止错误结果串到其他工具。
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
            # handler 可能已有自己的调用 ID，但注册表 ID 才是本次入口的权威追踪 ID。
            return finish(result, result.error_code)
        except Exception:
            # 不把 SQL、地址、凭据或第三方响应泄露给用户。
            return finish(
                BusinessToolResult(
                    tool_name=request.tool_name,
                    status="failed",
                    message="业务工具暂时不可用，请转人工客服处理",
                    handoff_required=True,
                ),
                "TOOL_EXECUTION_FAILED",
            )


def execute_learning_snapshot(
    request: BusinessToolRequest,
    *,
    session: Session,
    context: AccessContext,
) -> BusinessToolResult:
    """执行已接入的学情只读工具。

    身份和学员绑定关系仍由 learning_tools 内部再次校验，形成纵深防御。
    这里不把 ORM 对象直接返回给模型，只序列化已定义的结构化契约。
    """

    if request.tool_name != "learning_snapshot" or not request.learner_id:
        return BusinessToolResult(
            tool_name="learning_snapshot",
            status="invalid",
            message="学情工具请求参数无效",
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
        tool_name="learning_snapshot",
        status="success",
        message="学情查询成功",
        data=data,
    )


def build_demo_business_registry(
    *,
    session: Session,
    context: AccessContext,
) -> BusinessToolRegistry:
    """构建当前进程可用的业务工具注册表。

    注册表在请求范围内创建，避免把数据库会话、用户身份或请求状态放进
    全局单例。当前仅注册已经接入演示数据库的学情工具，其他工具继续保持
    未实现状态，便于未来替换成教务、订单或工单适配器。
    """

    registry = BusinessToolRegistry()
    registry.register(
        "learning_snapshot",
        lambda request: execute_learning_snapshot(
            request,
            session=session,
            context=context,
        ),
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
    """通过统一注册表执行一次学情查询，供 LangGraph 业务节点调用。

    这里的 has_verified_identity 在开发环境表示身份已经由入口解析为受控
    的演示角色；生产环境必须由 JWT、单点登录或网关注入真实核验结果。
    """

    request = BusinessToolRequest(
        tool_name="learning_snapshot",
        learner_id=learner_id,
    )
    registry = build_demo_business_registry(session=session, context=context)
    return registry.execute(
        request,
        route="learning_summary",
        has_verified_identity=True,
        actor_role=actor_role,
        request_id=request_id,
    )


def execute_class_availability(
    request: BusinessToolRequest,
    *,
    adapter: BusinessSystemsAdapter,
) -> BusinessToolResult:
    """通过适配器查询实时班级名额；适配器异常统一安全降级。"""

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


def execute_order_status(
    request: BusinessToolRequest,
    *,
    adapter: BusinessSystemsAdapter,
) -> BusinessToolResult:
    """通过适配器读取订单状态，不直接计算或承诺退款金额。"""

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


def execute_human_ticket(
    request: BusinessToolRequest,
    *,
    adapter: BusinessSystemsAdapter,
) -> BusinessToolResult:
    """通过适配器创建人工工单，并由幂等键控制重复提交。"""

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


def register_business_system_adapter(
    registry: BusinessToolRegistry,
    *,
    adapter: BusinessSystemsAdapter,
) -> None:
    """把外部业务适配器显式注册到请求范围注册表。

    默认注册表不会调用此函数，因此本地应用不会意外启用 Fake Adapter；只有
    测试或明确配置的演示环境才注入适配器，生产环境则注入真实适配器。
    """

    registry.register(
        "class_availability",
        lambda request: execute_class_availability(request, adapter=adapter),
    )
    registry.register(
        "order_status",
        lambda request: execute_order_status(request, adapter=adapter),
    )
    registry.register(
        "create_human_ticket",
        lambda request: execute_human_ticket(request, adapter=adapter),
    )


def parse_tool_request(payload: Any) -> BusinessToolRequest | None:
    """解析模型或上游服务的工具请求，非法结构直接拒绝。"""

    try:
        return BusinessToolRequest.model_validate(payload)
    except ValidationError:
        return None
