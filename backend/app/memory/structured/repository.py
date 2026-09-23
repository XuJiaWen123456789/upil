"""结构化长期记忆的数据库读写和版本治理。"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.memory.exceptions import MemoryRepositoryError
from backend.app.memory.structured.contracts import MemoryScope, StoredStructuredMemory
from backend.app.memory.structured.models import StructuredMemoryRecord
from backend.app.memory.types import MemoryCandidate


def make_scope_key(candidate: MemoryCandidate) -> str:
    """为主体和记忆字段生成不可读但稳定的唯一作用域键。"""

    raw = "".join((
        candidate.tenant_id, candidate.owner_user_id, candidate.owner_role,
        candidate.learner_id or "", candidate.memory_type, candidate.memory_key,
    ))
    return sha256(raw.encode("utf-8")).hexdigest()


def _stored(record: StructuredMemoryRecord) -> StoredStructuredMemory:
    return StoredStructuredMemory(
        id=record.id,
        scope=MemoryScope(record.tenant_id, record.owner_user_id, record.owner_role, record.learner_id),
        memory_type=record.memory_type,
        memory_key=record.memory_key,
        memory_value=dict(record.memory_value or {}),
        status=record.status,
        version=record.version,
        confidence=record.confidence,
        source_conversation_id=record.source_conversation_id,
        source_message_id=record.source_message_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _learner_scope_condition(scope: MemoryScope):
    """生成带有 NULL 语义的学员作用域条件。

    SQL 中 NULL == NULL 不会得到 True。删除和恢复操作如果直接使用
    == scope.learner_id，用户级记忆（learner_id 为 NULL）就会无法按
    完整作用域命中；反过来如果省略该条件，又可能把同一用户下其他学员的
    记忆暴露给当前操作。
    """

    if scope.learner_id is None:
        return StructuredMemoryRecord.learner_id.is_(None)
    return StructuredMemoryRecord.learner_id == scope.learner_id


class StructuredMemoryRepository:
    """只处理 ORM 和版本，不负责识别消息或决定准入。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active(self, scope: MemoryScope) -> list[StoredStructuredMemory]:
        """按完整主体范围读取有效偏好。"""

        try:
            rows = self.session.scalars(
                select(StructuredMemoryRecord)
                .where(
                    StructuredMemoryRecord.tenant_id == scope.tenant_id,
                    StructuredMemoryRecord.owner_user_id == scope.owner_user_id,
                    StructuredMemoryRecord.owner_role == scope.owner_role,
                    or_(StructuredMemoryRecord.learner_id == scope.learner_id, StructuredMemoryRecord.learner_id.is_(None)),
                    StructuredMemoryRecord.status == "active",
                )
                .order_by(StructuredMemoryRecord.updated_at.desc())
            ).all()
            return [_stored(row) for row in rows]
        except Exception as exc:
            raise MemoryRepositoryError("读取结构化长期记忆失败") from exc

    def save(
        self,
        candidate: MemoryCandidate,
        *,
        replace_existing: bool = True,
    ) -> StoredStructuredMemory | None:
        """保存候选；可禁止自主判断覆盖已有的不同值。

        显式“请记住”允许版本更新；自主判断只填补空白或命中同值。
        冲突时返回 None，由服务层视为安全跳过，不修改当前 active 记录。
        """

        scope_key = make_scope_key(candidate)
        now = datetime.utcnow()
        try:
            current = self.session.scalar(
                select(StructuredMemoryRecord)
                .where(StructuredMemoryRecord.scope_key == scope_key, StructuredMemoryRecord.status == "active")
                .with_for_update()
            )
            if current is not None and current.memory_value == candidate.memory_value:
                return _stored(current)
            if current is not None and not replace_existing:
                return None
            version = 1
            if current is not None:
                current.status = "invalidated"
                current.invalidated_at = now
                version = current.version + 1
            record = StructuredMemoryRecord(
                id=f"mem_{uuid4().hex}", tenant_id=candidate.tenant_id,
                owner_user_id=candidate.owner_user_id, owner_role=candidate.owner_role,
                learner_id=candidate.learner_id, scope_key=scope_key,
                memory_type=candidate.memory_type, memory_key=candidate.memory_key,
                memory_value=dict(candidate.memory_value), status="active", version=version,
                confidence=candidate.confidence, source_conversation_id=candidate.source_conversation_id,
                source_message_id=candidate.source_message_id, created_at=now, updated_at=now,
            )
            self.session.add(record)
            self.session.flush()
            return _stored(record)
        except MemoryRepositoryError:
            raise
        except Exception as exc:
            raise MemoryRepositoryError("写入结构化长期记忆失败") from exc

    def delete(self, memory_id: str, scope: MemoryScope) -> bool:
        """只允许主体所有者删除自己的记忆。"""

        try:
            record = self.session.scalar(
                select(StructuredMemoryRecord).where(
                    StructuredMemoryRecord.id == memory_id,
                    StructuredMemoryRecord.tenant_id == scope.tenant_id,
                    StructuredMemoryRecord.owner_user_id == scope.owner_user_id,
                    StructuredMemoryRecord.owner_role == scope.owner_role,
                    _learner_scope_condition(scope),
                    StructuredMemoryRecord.status == "active",
                )
            )
            if record is None:
                return False
            record.status = "deleted"
            record.deleted_at = datetime.utcnow()
            self.session.flush()
            return True
        except Exception as exc:
            raise MemoryRepositoryError("删除结构化长期记忆失败") from exc

    def restore(self, memory_id: str, scope: MemoryScope) -> bool:
        """恢复历史版本，并使当前 active 版本失效。"""

        try:
            target = self.session.scalar(
                select(StructuredMemoryRecord).where(
                    StructuredMemoryRecord.id == memory_id,
                    StructuredMemoryRecord.tenant_id == scope.tenant_id,
                    StructuredMemoryRecord.owner_user_id == scope.owner_user_id,
                    StructuredMemoryRecord.owner_role == scope.owner_role,
                    _learner_scope_condition(scope),
                    # 用户删除的记忆仍保留历史版本，允许在同一完整作用域
                    # 内恢复；这不是跨学员或跨用户的重新授权。
                    StructuredMemoryRecord.status.in_(["deleted", "invalidated", "expired"]),
                )
            )
            if target is None:
                return False
            current = self.session.scalar(
                select(StructuredMemoryRecord).where(
                    StructuredMemoryRecord.scope_key == target.scope_key,
                    StructuredMemoryRecord.status == "active",
                )
            )
            now = datetime.utcnow()
            if current is not None:
                current.status = "invalidated"
                current.invalidated_at = now
            target.status = "active"
            target.deleted_at = None
            target.invalidated_at = None
            target.updated_at = now
            self.session.flush()
            return True
        except Exception as exc:
            raise MemoryRepositoryError("恢复结构化长期记忆失败") from exc
