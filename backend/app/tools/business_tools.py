"""历史业务工具导入路径的兼容门面。

实际实现已按契约、策略、注册表和单工具文件拆分。调用方可以渐进迁移，
现有 LangGraph 节点、API 路由和测试不需要在同一次重构中整体改名。
"""

from backend.app.tools.adapter_registry import register_business_system_adapter
from backend.app.tools.class_availability import execute_class_availability
from backend.app.tools.contracts import (
    BusinessToolHandler,
    BusinessToolRequest,
    BusinessToolResult,
    ToolAuditSink,
    ToolErrorCode,
    ToolName,
    ToolStatus,
    parse_tool_request,
)
from backend.app.tools.human_ticket import execute_human_ticket
from backend.app.tools.learning_snapshot import (
    build_demo_business_registry,
    execute_learning_snapshot,
    execute_learning_snapshot_via_registry,
)
from backend.app.tools.order_status import execute_order_status
from backend.app.tools.policies import (
    TOOL_POLICIES,
    ToolPolicy,
    resolve_tool_policy,
    validate_tool_request,
)
from backend.app.tools.registry import BusinessToolRegistry


__all__ = [
    "BusinessToolHandler",
    "BusinessToolRegistry",
    "BusinessToolRequest",
    "BusinessToolResult",
    "TOOL_POLICIES",
    "ToolAuditSink",
    "ToolErrorCode",
    "ToolName",
    "ToolPolicy",
    "ToolStatus",
    "build_demo_business_registry",
    "execute_class_availability",
    "execute_human_ticket",
    "execute_learning_snapshot",
    "execute_learning_snapshot_via_registry",
    "execute_order_status",
    "parse_tool_request",
    "register_business_system_adapter",
    "resolve_tool_policy",
    "validate_tool_request",
]
