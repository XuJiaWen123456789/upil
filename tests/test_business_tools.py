"""阶段 12-H-8：客服业务工具白名单、权限和失败兜底测试。"""

from backend.app.services.access_control import AccessContext
from backend.app.integrations.business_adapters import (
    BusinessAdapterTimeout,
    ClassAvailabilityData,
    FakeBusinessSystemsAdapter,
    OrderStatusData,
)
from backend.app.tools.business_tools import (
    BusinessToolRegistry,
    BusinessToolRequest,
    build_demo_business_registry,
    execute_learning_snapshot,
    execute_learning_snapshot_via_registry,
    execute_class_availability,
    execute_human_ticket,
    execute_order_status,
    parse_tool_request,
    register_business_system_adapter,
    validate_tool_request,
)
from tests.test_database import make_session, seed_session


def test_valid_learning_request_passes_contract_validation() -> None:
    """合法的学情查询请求应能通过 Pydantic 契约和业务参数校验。"""

    request = parse_tool_request(
        {"tool_name": "learning_snapshot", "learner_id": "L1001"}
    )

    assert request is not None
    assert validate_tool_request(request) is None


def test_unknown_fields_are_rejected() -> None:
    """工具请求禁止携带任意字段，避免 Prompt Injection 注入命令或敏感参数。"""

    request = parse_tool_request(
        {
            "tool_name": "learning_snapshot",
            "learner_id": "L1001",
            "command": "select * from users",
        }
    )

    assert request is None


def test_unknown_tool_name_is_rejected() -> None:
    """不在白名单中的函数名不能进入工具执行层。"""

    request = parse_tool_request({"tool_name": "run_shell", "reason": "test"})

    assert request is None


def test_required_business_parameters_are_checked() -> None:
    """不同业务工具的关键参数缺失时，应返回明确的校验结果。"""

    learning = BusinessToolRequest(tool_name="learning_snapshot")
    availability = BusinessToolRequest(tool_name="class_availability")
    order = BusinessToolRequest(tool_name="order_status")
    ticket = BusinessToolRequest(tool_name="create_human_ticket", reason="需要人工核验")

    assert validate_tool_request(learning) == "查询学情快照必须提供学员编号"
    assert validate_tool_request(availability) == "查询班级名额必须提供课程信息"
    assert validate_tool_request(order) == "查询订单状态必须提供订单编号"
    assert validate_tool_request(ticket) == "创建人工工单必须提供幂等键"


def test_unimplemented_dynamic_tool_never_returns_fake_data() -> None:
    """未接入真实教务系统时，名额工具必须转人工而不能伪造剩余名额。"""

    registry = BusinessToolRegistry()
    request = BusinessToolRequest(
        tool_name="class_availability",
        course_name="中国舞基础班",
        campus_name="星河中心校区",
    )

    result = registry.execute(request, route="schedule_or_seat")

    assert result.status == "not_implemented"
    assert result.handoff_required is True
    assert result.data == {}
    assert "尚未接入" in result.message


def test_tool_observation_fields_and_audit_event_are_safe() -> None:
    """工具结果和审计事件应有追踪字段，且不能记录原始业务参数或密钥。"""

    registry = BusinessToolRegistry()
    request = BusinessToolRequest(
        tool_name="class_availability",
        course_name="中国舞基础班",
        campus_name="星河中心校区",
    )

    result = registry.execute(
        request,
        route="schedule_or_seat",
        actor_role="parent",
        request_id="req_demo_001",
        tool_call_id="call_demo_001",
    )

    assert result.request_id == "req_demo_001"
    assert result.tool_call_id == "call_demo_001"
    assert result.route == "schedule_or_seat"
    assert result.duration_ms >= 0
    assert result.error_code == "TOOL_NOT_IMPLEMENTED"
    assert len(registry.audit_events) == 1
    event = registry.audit_events[0]
    assert event["request_id"] == "req_demo_001"
    assert event["tool_call_id"] == "call_demo_001"
    assert "中国舞基础班" not in str(event)
    assert "password" not in str(event).lower()


def test_tool_observation_ids_are_unique_when_not_provided() -> None:
    """未指定追踪 ID 时，两个工具调用不能共享同一组 ID。"""

    registry = BusinessToolRegistry()
    request = BusinessToolRequest(
        tool_name="class_availability",
        course_name="中国舞基础班",
        campus_name="星河中心校区",
    )

    first = registry.execute(request, route="schedule_or_seat")
    second = registry.execute(request, route="schedule_or_seat")

    assert first.request_id != second.request_id
    assert first.tool_call_id != second.tool_call_id


def test_adapter_timeout_has_standard_error_code() -> None:
    """外部适配器超时时，结果必须携带稳定错误码。"""

    adapter = FakeBusinessSystemsAdapter(timeout_operations={"class_availability"})
    request = BusinessToolRequest(
        tool_name="class_availability",
        course_name="中国舞基础班",
        campus_name="星河中心校区",
    )

    result = execute_class_availability(request, adapter=adapter)

    assert result.status == "failed"
    assert result.error_code == "TOOL_TIMEOUT"


def test_identity_is_required_before_learning_query() -> None:
    """学情工具在身份未核验时不得执行，即使请求参数完整也要拒绝。"""

    registry = BusinessToolRegistry()
    request = BusinessToolRequest(tool_name="learning_snapshot", learner_id="L1001")

    result = registry.execute(
        request,
        route="learning_summary",
        has_verified_identity=False,
    )

    assert result.status == "denied"
    assert result.handoff_required is True
    assert "身份核验" in result.message


def test_tool_cannot_cross_route_boundary() -> None:
    """即使工具属于全局白名单，也不能被不匹配的路由跨场景调用。"""

    registry = BusinessToolRegistry()
    request = BusinessToolRequest(tool_name="learning_snapshot", learner_id="L1001")

    result = registry.execute(
        request,
        route="schedule_or_seat",
        has_verified_identity=True,
    )

    assert result.status == "denied"
    assert result.handoff_required is True


def test_learning_snapshot_returns_serializable_data_after_authorization() -> None:
    """已绑定家长完成核验后，学情工具应返回结构化、可序列化的数据。"""

    with make_session() as session:
        seed_session(session)
        context = AccessContext("P1001", "parent")
        registry = BusinessToolRegistry()
        registry.register(
            "learning_snapshot",
            lambda request: execute_learning_snapshot(
                request,
                session=session,
                context=context,
            ),
        )
        request = BusinessToolRequest(
            tool_name="learning_snapshot", learner_id="L1001"
        )

        result = registry.execute(
            request,
            route="learning_summary",
            has_verified_identity=True,
        )

    assert result.status == "success"
    assert result.handoff_required is False
    assert result.data["profile"]["learner_id"] == "L1001"
    assert result.data["balance"]["remaining_hours"] == 12
    assert result.data["attendance"]["attendance_rate"] == 0.5


def test_registry_factory_registers_only_connected_demo_tool() -> None:
    """请求范围注册表只暴露当前已接入的学情工具。"""

    with make_session() as session:
        seed_session(session)
        registry = build_demo_business_registry(
            session=session,
            context=AccessContext("P1001", "parent"),
        )
        learning_request = BusinessToolRequest(
            tool_name="learning_snapshot", learner_id="L1001"
        )
        seat_request = BusinessToolRequest(
            tool_name="class_availability",
            course_name="中国舞基础班",
            campus_name="星河中心校区",
        )

        learning_result = registry.execute(
            learning_request,
            route="learning_summary",
            has_verified_identity=True,
        )
        seat_result = registry.execute(
            seat_request,
            route="schedule_or_seat",
        )

    assert learning_result.status == "success"
    assert seat_result.status == "not_implemented"
    assert seat_result.handoff_required is True


def test_learning_graph_facade_uses_structured_tool_result() -> None:
    """LangGraph 使用统一注册表时仍应得到稳定的结构化学情结果。"""

    with make_session() as session:
        seed_session(session)
        result = execute_learning_snapshot_via_registry(
            session=session,
            context=AccessContext("P1001", "parent"),
            learner_id="L1001",
        )

    assert result.status == "success"
    assert result.data["profile"]["learner_name"] == "演示学员"
    assert result.data["balance"]["consumed_hours"] == 8
    assert result.data["attendance"]["absent_lessons"] == 1


def test_tool_exception_is_sanitized_and_requires_handoff() -> None:
    """第三方异常中的 SQL、URL 和凭据不得泄露给用户。"""

    def broken_handler(request: BusinessToolRequest):
        raise RuntimeError(
            "postgres://admin:secret@example.invalid/db; SELECT * FROM users"
        )

    registry = BusinessToolRegistry()
    registry.register("create_human_ticket", broken_handler)
    request = BusinessToolRequest(
        tool_name="create_human_ticket",
        reason="退费争议需要人工处理",
        idempotency_key="ticket-test-001",
    )

    result = registry.execute(request, route="human_handoff")

    assert result.status == "failed"
    assert result.handoff_required is True
    assert "secret" not in result.message
    assert "postgres" not in result.message
    assert "SELECT" not in result.message


def test_fake_adapter_supports_explicit_demo_availability() -> None:
    """只有显式注入的 Fake Adapter 才能返回演示名额，避免默认伪造动态数据。"""

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
    request = BusinessToolRequest(
        tool_name="class_availability",
        course_name="中国舞基础班",
        campus_name="星河中心校区",
    )

    result = execute_class_availability(request, adapter=adapter)

    assert result.status == "success"
    assert result.data["available_seats"] == 3
    assert result.handoff_required is False
    assert adapter.audit_events[-1]["outcome"] == "success"


def test_dynamic_adapter_timeout_is_safe() -> None:
    """教务系统超时时不能返回旧值或猜测名额。"""

    adapter = FakeBusinessSystemsAdapter(
        timeout_operations={"class_availability"}
    )
    request = BusinessToolRequest(
        tool_name="class_availability",
        course_name="中国舞基础班",
        campus_name="星河中心校区",
    )

    result = execute_class_availability(request, adapter=adapter)

    assert result.status == "failed"
    assert result.handoff_required is True
    assert result.data == {}
    assert "超时" in result.message


def test_order_status_does_not_return_refund_amount() -> None:
    """订单适配器只返回受控状态，不暴露或计算退款金额。"""

    adapter = FakeBusinessSystemsAdapter(
        orders={
            "ORD-001": OrderStatusData(
                order_id="ORD-001",
                status="partially_used",
                course_name="少儿编程基础班",
                message="订单存在已使用课次，退费需按订单条款人工核算。",
                checked_at="2026-09-07T12:00:00+08:00",
            )
        }
    )
    request = BusinessToolRequest(tool_name="order_status", order_id="ORD-001")

    result = execute_order_status(request, adapter=adapter)

    assert result.status == "success"
    assert result.data["status"] == "partially_used"
    assert "refund_amount" not in result.data
    assert "退款金额" not in result.data


def test_human_ticket_is_idempotent() -> None:
    """相同幂等键重复调用只生成一个演示工单。"""

    adapter = FakeBusinessSystemsAdapter()
    request = BusinessToolRequest(
        tool_name="create_human_ticket",
        reason="退费争议需要人工核验",
        idempotency_key="ticket-idempotent-001",
    )

    first = execute_human_ticket(request, adapter=adapter)
    second = execute_human_ticket(request, adapter=adapter)

    assert first.status == "success"
    assert second.status == "success"
    assert first.data["ticket_id"] == second.data["ticket_id"]
    assert first.data["status"] == "created"
    assert second.data["status"] == "existing"
    assert len(adapter.audit_events) == 2


def test_adapter_can_be_registered_without_changing_route_contract() -> None:
    """接入适配器只增加已审核工具，不改变路由白名单。"""

    adapter = FakeBusinessSystemsAdapter()
    registry = BusinessToolRegistry()
    register_business_system_adapter(registry, adapter=adapter)
    request = BusinessToolRequest(
        tool_name="create_human_ticket",
        reason="需要工作人员联系",
        idempotency_key="ticket-register-001",
    )

    result = registry.execute(request, route="human_handoff")

    assert result.status == "success"
    assert result.data["ticket_id"].startswith("DEMO-TICKET-")
