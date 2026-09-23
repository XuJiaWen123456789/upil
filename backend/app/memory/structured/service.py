"""结构化长期记忆服务门面。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.memory.structured.admission import admit_candidate, extract_candidate
from backend.app.memory.structured.contracts import MemoryScope, StoredStructuredMemory
from backend.app.memory.structured.repository import StructuredMemoryRepository


class StructuredMemoryService:
    """连接消息准入、仓储版本治理和 Agent 安全投影。"""

    def __init__(self, session: Session) -> None:
        self.repository = StructuredMemoryRepository(session)

    def remember_message(self, message: str, *, scope: MemoryScope,
                         conversation_id: str | None = None,
                         message_id: str | None = None) -> StoredStructuredMemory | None:
        """从一条消息中提取并保存显式或高置信度稳定偏好。"""

        candidate = extract_candidate(
            message, owner_user_id=scope.owner_user_id, tenant_id=scope.tenant_id,
            owner_role=scope.owner_role, learner_id=scope.learner_id,
            conversation_id=conversation_id, message_id=message_id,
        )
        if candidate is None:
            return None
        admitted = admit_candidate(candidate)
        # 自主判断不能静默覆盖已有的不同值；只有用户明确要求记住时，
        # 才通过仓储的版本治理使旧值失效并建立新 active 版本。
        return self.repository.save(
            admitted,
            replace_existing=admitted.write_basis == "explicit_user_request",
        )

    def projections(self, scope: MemoryScope) -> tuple[dict[str, str], ...]:
        """读取当前主体可用偏好，并隐藏内部 ORM 字段。"""

        records = self.repository.list_active(scope)
        # 查询具体学员时同时继承用户级偏好，但相同字段优先采用学员级值。
        # 排序是稳定的，组内继续沿用仓储的更新时间倒序。
        if scope.learner_id is not None:
            records = sorted(
                records,
                key=lambda item: item.scope.learner_id != scope.learner_id,
            )
        projections: list[dict[str, str]] = []
        seen_keys: set[str] = set()
        for item in records:
            if item.memory_key in seen_keys:
                continue
            projections.append(item.to_projection())
            seen_keys.add(item.memory_key)
        return tuple(projections)
