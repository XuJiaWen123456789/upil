"""不同记忆类型的公共类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


MemoryType = Literal["structured_preference", "episodic_event"]
MemoryStatus = Literal["active", "invalidated", "deleted", "expired"]


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """候选记忆；候选不等于已生效的长期记忆。"""

    owner_user_id: str
    tenant_id: str
    memory_type: MemoryType
    memory_key: str
    memory_value: dict[str, str]
    source_conversation_id: str | None
    source_message_id: str | None = None
    write_basis: str = "explicit_user_request"
    confidence: float = 1.0
    expires_at: datetime | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    # 角色和学员范围是长期记忆的第二层隔离边界。旧调用方不传时，
    # 仍可保存为用户级记忆；新聊天入口会始终注入可信角色和学员范围。
    owner_role: str = "parent"
    learner_id: str | None = None
