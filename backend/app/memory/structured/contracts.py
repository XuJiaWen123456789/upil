"""结构化长期记忆的边界契约和安全投影。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


MemoryCommandStatus = Literal[
    "stored",
    "rejected",
    "disabled",
    "unauthorized",
    "failed",
]


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """长期记忆的完整隔离范围。"""

    tenant_id: str
    owner_user_id: str
    owner_role: str
    learner_id: str | None = None


@dataclass(frozen=True, slots=True)
class StoredStructuredMemory:
    """脱离 ORM 后的记忆记录；内部元数据不直接投影给 Agent。"""

    id: str
    scope: MemoryScope
    memory_type: str
    memory_key: str
    memory_value: dict[str, str]
    status: str
    version: int
    confidence: float
    source_conversation_id: str | None
    source_message_id: str | None
    created_at: datetime
    updated_at: datetime

    def to_projection(self) -> dict[str, str]:
        """仅返回 Agent 需要的键和值，不泄露主键、版本或作用域。"""

        return {"key": self.memory_key, "value": self.memory_value.get("value", "")}


@dataclass(frozen=True, slots=True)
class MemoryCommandResult:
    """显式记忆命令的安全结果。

    HTTP 层只需要依据 status 选择业务文案，不接触候选对象、数据库主键和
    异常正文。stored_memory 仅在服务内部用于生成不含敏感元数据的确认话术。
    """

    status: MemoryCommandStatus
    stored_memory: StoredStructuredMemory | None = None
