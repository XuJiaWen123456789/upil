"""持久聊天会话模型。

PostgreSQL 只保存会话目录、受控上下文快照和脱敏后的可见消息。模型不保存
Token、模型思维链、Prompt、工具原始结果、联系方式明文或内部服务地址。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class ChatConversation(Base):
    """一个可信主体拥有的持久会话目录。"""

    __tablename__ = "chat_conversations"
    __table_args__ = (
        CheckConstraint(
            "owner_role IN ('parent', 'teacher')",
            name="ck_chat_conversation_owner_role",
        ),
        CheckConstraint(
            "status IN ('active')",
            name="ck_chat_conversation_status",
        ),
        Index(
            "ix_chat_conversation_owner_recent",
            "tenant_id",
            "owner_user_id",
            "owner_role",
            "last_message_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False, default="新会话")
    # 用户手动命名后，第一条消息和后续消息都不能再次覆盖标题。
    title_is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # 只允许保存 ConversationMemory 的白名单字段，不接受任意业务对象。
    context_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(Base):
    """会话中的单条脱敏文本消息。"""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "sequence_no",
            name="uq_chat_message_conversation_sequence",
        ),
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_chat_message_role",
        ),
        CheckConstraint(
            "message_type IN ('text')",
            name="ck_chat_message_type",
        ),
        Index("ix_chat_message_conversation_sequence", "conversation_id", "sequence_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    # 预留白名单展示元数据；当前 MVP 不持久化任意 Agent 或工具返回对象。
    safe_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
