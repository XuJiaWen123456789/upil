"""外部业务适配器到工具注册表的显式装配。"""

from backend.app.integrations.business_adapters import BusinessSystemsAdapter
from backend.app.tools.class_availability import execute_class_availability
from backend.app.tools.human_ticket import execute_human_ticket
from backend.app.tools.order_status import execute_order_status
from backend.app.tools.registry import BusinessToolRegistry


def register_business_system_adapter(
    registry: BusinessToolRegistry, *, adapter: BusinessSystemsAdapter
) -> None:
    """注册已审核适配器；默认应用不会自行启用 Fake Adapter。"""

    registry.register(
        "class_availability",
        lambda request: execute_class_availability(request, adapter=adapter),
    )
    registry.register(
        "order_status", lambda request: execute_order_status(request, adapter=adapter)
    )
    registry.register(
        "create_human_ticket",
        lambda request: execute_human_ticket(request, adapter=adapter),
    )
