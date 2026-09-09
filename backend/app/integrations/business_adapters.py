"""教务、订单和客服工单系统的可替换适配器契约。

本模块只定义系统边界和本地 Fake Adapter，不连接外部生产系统。真实系统接入
时，可以在不修改 LangGraph 路由和业务工具契约的前提下替换适配器实现。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class BusinessAdapterTimeout(Exception):
    """业务系统在规定时间内没有返回结果。"""


class BusinessAdapterUnavailable(Exception):
    """业务系统当前不可用或连接未建立。"""


class ClassAvailabilityQuery(BaseModel):
    """班级名额查询的最小参数契约。"""

    model_config = ConfigDict(extra="forbid")

    course_id: str | None = Field(default=None, max_length=64)
    course_name: str | None = Field(default=None, max_length=100)
    campus_id: str | None = Field(default=None, max_length=64)
    campus_name: str | None = Field(default=None, max_length=100)


class ClassAvailabilityData(BaseModel):
    """班级名额查询的脱敏结果，不包含学员个人信息。"""

    model_config = ConfigDict(extra="forbid")

    course_name: str
    campus_name: str
    available_seats: int = Field(ge=0)
    schedule_options: list[str] = Field(default_factory=list, max_length=20)
    checked_at: str


class OrderStatusQuery(BaseModel):
    """订单状态查询的最小参数契约。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=64)


class OrderStatusData(BaseModel):
    """订单查询的安全结果，只返回状态和必要的业务提示。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str
    status: Literal["pending", "paid", "partially_used", "completed", "refund_review"]
    course_name: str | None = None
    message: str
    checked_at: str


class HumanTicketCommand(BaseModel):
    """人工工单创建命令；幂等键用于防止 SSE 重试重复建单。"""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    learner_id: str | None = Field(default=None, max_length=64)
    order_id: str | None = Field(default=None, max_length=64)


class HumanTicketData(BaseModel):
    """工单创建结果，不向前端返回内部队列或数据库信息。"""

    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    status: Literal["created", "existing"]
    message: str


class BusinessSystemsAdapter(Protocol):
    """真实教务、订单和工单系统需要实现的最小适配器协议。"""

    def query_class_availability(
        self, query: ClassAvailabilityQuery
    ) -> ClassAvailabilityData:
        """查询实时班级名额和可选时段。"""

    def query_order_status(self, query: OrderStatusQuery) -> OrderStatusData:
        """查询订单状态，不负责直接变更订单或计算最终退款金额。"""

    def create_human_ticket(self, command: HumanTicketCommand) -> HumanTicketData:
        """创建人工工单，必须保证相同幂等键只创建一次。"""


class FakeBusinessSystemsAdapter:
    """用于本地测试的确定性业务系统适配器。

    Fake Adapter 的返回数据明确标记为演示结果，不能用于生产。它支持人为
    注入超时和不可用状态，用来验证工作流在第三方故障时不会编造业务事实。
    """

    def __init__(
        self,
        *,
        availability: Mapping[tuple[str, str], ClassAvailabilityData] | None = None,
        orders: Mapping[str, OrderStatusData] | None = None,
        timeout_operations: set[str] | None = None,
        unavailable_operations: set[str] | None = None,
    ) -> None:
        # 默认数据只服务于自动化测试和本地演示，不代表任何真实机构信息。
        self._availability = dict(availability or {})
        self._orders = dict(orders or {})
        self._timeout_operations = set(timeout_operations or set())
        self._unavailable_operations = set(unavailable_operations or set())
        self._tickets: dict[str, HumanTicketData] = {}
        # 审计事件只记录操作类型和安全摘要，不保存完整问题描述或密钥。
        self.audit_events: list[dict[str, str | int]] = []
        self._ticket_sequence = 0

    def _check_operation(self, operation: str) -> None:
        """按测试配置模拟超时或不可用，不通过 sleep 制造不稳定测试。"""

        if operation in self._timeout_operations:
            raise BusinessAdapterTimeout(operation)
        if operation in self._unavailable_operations:
            raise BusinessAdapterUnavailable(operation)

    def _audit(self, operation: str, *, outcome: str, **safe_fields: str | int) -> None:
        """写入脱敏的适配器审计事件，禁止保存原始 reason。"""

        self.audit_events.append(
            {"operation": operation, "outcome": outcome, **safe_fields}
        )

    def query_class_availability(
        self, query: ClassAvailabilityQuery
    ) -> ClassAvailabilityData:
        """返回显式配置的演示班级名额；未配置时认为没有可信结果。"""

        self._check_operation("class_availability")
        course_key = query.course_id or query.course_name or ""
        campus_key = query.campus_id or query.campus_name or ""
        result = self._availability.get((course_key, campus_key))
        if result is None:
            self._audit("class_availability", outcome="not_found")
            raise BusinessAdapterUnavailable("availability_record_missing")
        self._audit(
            "class_availability",
            outcome="success",
            available_seats=result.available_seats,
        )
        return result

    def query_order_status(self, query: OrderStatusQuery) -> OrderStatusData:
        """返回显式配置的演示订单状态，不生成退款金额。"""

        self._check_operation("order_status")
        result = self._orders.get(query.order_id)
        if result is None:
            self._audit("order_status", outcome="not_found")
            raise BusinessAdapterUnavailable("order_record_missing")
        self._audit("order_status", outcome="success", status=result.status)
        return result

    def create_human_ticket(self, command: HumanTicketCommand) -> HumanTicketData:
        """创建幂等人工工单；重复请求返回原工单而不增加新记录。"""

        self._check_operation("create_human_ticket")
        existing = self._tickets.get(command.idempotency_key)
        if existing is not None:
            self._audit("create_human_ticket", outcome="existing")
            return existing.model_copy(update={"status": "existing"})

        self._ticket_sequence += 1
        ticket = HumanTicketData(
            ticket_id=f"DEMO-TICKET-{self._ticket_sequence:04d}",
            status="created",
            message="人工工单已创建，后续由工作人员处理。",
        )
        self._tickets[command.idempotency_key] = ticket
        self._audit(
            "create_human_ticket",
            outcome="created",
            reason_length=len(command.reason),
        )
        return ticket
