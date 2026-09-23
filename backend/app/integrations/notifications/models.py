"""招生线索通知 Outbox 数据模型。"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class LeadNotificationOutbox(Base):
    """与线索同事务保存的待投递通知事件。

    payload_json 只允许保存课程、意向和授权状态等低敏摘要。联系方式、
    家长原话、用户标识和聊天记录不得进入该字段。
    """

    __tablename__ = "lead_notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('medium_intent_created', 'high_intent_waiting_contact', "
            "'contact_authorized')",
            name="ck_lead_notification_event_type",
        ),
        CheckConstraint(
            "channel IN ('feishu')",
            name="ck_lead_notification_channel",
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'retry', 'sent', 'failed')",
            name="ck_lead_notification_status",
        ),
        UniqueConstraint(
            "lead_id",
            "event_type",
            "channel",
            "intent_version",
            name="uq_lead_notification_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("enrollment_leads.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    channel: Mapped[str] = mapped_column(String(24), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # 只保存自定义稳定错误码，不保存 URL、第三方响应正文或异常字符串。
    last_error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    intent_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
