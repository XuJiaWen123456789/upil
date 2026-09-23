"""uPil Agent 上下文边界。

上下文包只负责定义请求级共享数据、可信来源和 Agent 投影，不负责调用
模型、查询数据库或保存联系方式。这样可以把“共享上下文”和“共享可写状态”
明确分开，避免多个 Agent 互相覆盖数据。
"""

from backend.app.context.assembler import assemble_context
from backend.app.context.contracts import (
    ContextEnvelope,
    ContextField,
    ContextSource,
    ContextTrust,
)

__all__ = [
    "ContextEnvelope",
    "ContextField",
    "ContextSource",
    "ContextTrust",
    "assemble_context",
]
