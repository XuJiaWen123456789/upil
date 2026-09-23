"""受控业务工具的请求、结果和处理器契约。"""

from typing import Any, Callable, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# 工具名使用闭集，模型不能把任意函数名或系统命令带入执行层。
ToolName = Literal[
    "learning_snapshot",
    "class_availability",
    "order_status",
    "create_human_ticket",
]
ToolStatus = Literal["success", "invalid", "denied", "not_implemented", "failed"]
ToolErrorCode = Literal[
    "TOOL_INVALID_ARGUMENT",
    "TOOL_ACCESS_DENIED",
    "TOOL_NOT_IMPLEMENTED",
    "TOOL_TIMEOUT",
    "TOOL_UNAVAILABLE",
    "TOOL_EXECUTION_FAILED",
]


class BusinessToolRequest(BaseModel):
    """所有工具共用的严格请求体，拒绝未声明字段。"""

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
    """业务工具的稳定结果和脱敏观测字段。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: ToolName
    status: ToolStatus
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    handoff_required: bool = False
    request_id: str = Field(default_factory=lambda: f"req_{uuid4().hex}")
    tool_call_id: str = Field(default_factory=lambda: f"call_{uuid4().hex}")
    route: str | None = None
    duration_ms: float = Field(default=0.0, ge=0)
    error_code: ToolErrorCode | None = None


class BusinessToolHandler(Protocol):
    """单个工具执行器需要实现的最小协议。"""

    def __call__(self, request: BusinessToolRequest) -> BusinessToolResult:
        """执行已完成路由和参数门禁的请求。"""


ToolAuditSink = Callable[[dict[str, str | int | float | None]], None]


def parse_tool_request(payload: Any) -> BusinessToolRequest | None:
    """解析模型或上游传入的结构；非法字段直接拒绝。"""

    try:
        return BusinessToolRequest.model_validate(payload)
    except ValidationError:
        return None
