"""结构化长期记忆 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Index, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class StructuredMemoryRecord(Base):
    """用户主动确认的非敏感偏好及其历史版本。"""

    __tablename__ = "agent_structured_memories"
    __table_args__ = (
        CheckConstraint("memory_type IN ('structured_preference')", name="ck_agent_memory_type"),
        CheckConstraint("status IN ('active', 'invalidated', 'deleted', 'expired')", name="ck_agent_memory_status"),
        CheckConstraint("version >= 1", name="ck_agent_memory_version"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_agent_memory_confidence"),
        # scope_key 已经包含租户、用户、角色、学员和记忆字段，解决 NULL
        # learner_id 在不同数据库唯一索引中语义不一致的问题。
        Index(
            "uq_agent_memory_active_scope_key",
            "scope_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_agent_memory_owner_scope", "tenant_id", "owner_user_id", "owner_role"),
        Index("ix_agent_memory_learner_scope", "tenant_id", "learner_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False)
    learner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_key: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
