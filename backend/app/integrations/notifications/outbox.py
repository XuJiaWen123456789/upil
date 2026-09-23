"""招生线索通知 Outbox 的创建、领取和状态更新。"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.integrations.notifications.models import LeadNotificationOutbox
from backend.app.models import EnrollmentLead


EVENT_MEDIUM_CREATED = "medium_intent_created"
EVENT_HIGH_WAITING_CONTACT = "high_intent_waiting_contact"
EVENT_CONTACT_AUTHORIZED = "contact_authorized"


def enqueue_lead_notification(
    session: Session,
    settings: Settings,
    lead: EnrollmentLead,
    *,
    event_type: str,
    intent_version: int = 1,
) -> LeadNotificationOutbox | None:
    """在当前线索事务中加入幂等通知事件。

    配置关闭时直接跳过。载荷刻意不包含 parent_id、learner_id、手机号、
    邮箱、会话引用和证据原文，外部通知只能提示顾问回系统查看。
    """

    if not settings.lead_notification_enabled:
        return None
    if settings.lead_notification_channel != "feishu":
        return None
    if event_type == EVENT_MEDIUM_CREATED and settings.lead_notification_min_level != "medium":
        return None

    existing = session.scalar(
        select(LeadNotificationOutbox).where(
            LeadNotificationOutbox.lead_id == lead.id,
            LeadNotificationOutbox.event_type == event_type,
            LeadNotificationOutbox.channel == settings.lead_notification_channel,
            LeadNotificationOutbox.intent_version == intent_version,
        )
    )
    if existing is not None:
        return existing

    event = LeadNotificationOutbox(
        id=f"notification_{uuid4().hex}",
        lead_id=lead.id,
        event_type=event_type,
        channel=settings.lead_notification_channel,
        payload_json={
            "course_name": lead.course_name,
            "interest_type": lead.interest_type,
            "strength": lead.strength,
            "status": lead.status,
            "contact_authorized": lead.contact_ciphertext is not None,
        },
        status="pending",
        retry_count=0,
        intent_version=intent_version,
    )
    # 查询后的并发窗口仍可能有另一个实例写入同一事件。保存点只回滚
    # Outbox 插入，不得让非关键通知破坏已经计算完成的业务线索事务。
    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
        return event
    except IntegrityError:
        return session.scalar(
            select(LeadNotificationOutbox).where(
                LeadNotificationOutbox.lead_id == lead.id,
                LeadNotificationOutbox.event_type == event_type,
                LeadNotificationOutbox.channel == settings.lead_notification_channel,
                LeadNotificationOutbox.intent_version == intent_version,
            )
        )


def choose_transition_event(
    *,
    created: bool,
    previous_strength: str | None,
    previous_contact_authorized: bool,
    lead: EnrollmentLead,
) -> str | None:
    """只为有业务意义的状态变化生成一次通知。"""

    contact_became_authorized = (
        lead.contact_ciphertext is not None and not previous_contact_authorized
    )
    if contact_became_authorized:
        return EVENT_CONTACT_AUTHORIZED
    if lead.strength == "high" and lead.contact_ciphertext is None and (
        created or previous_strength != "high"
    ):
        return EVENT_HIGH_WAITING_CONTACT
    if lead.strength == "medium" and created:
        return EVENT_MEDIUM_CREATED
    return None


def claim_due_notification(
    session: Session, *, now: datetime | None = None
) -> LeadNotificationOutbox | None:
    """领取一条到期事件；多实例 PostgreSQL 使用 SKIP LOCKED 避免争抢。"""

    current = now or datetime.utcnow()
    stale_sending = current - timedelta(minutes=5)
    statement = (
        select(LeadNotificationOutbox)
        .where(
            or_(
                LeadNotificationOutbox.status == "pending",
                (
                    (LeadNotificationOutbox.status == "retry")
                    & (
                        (LeadNotificationOutbox.next_retry_at.is_(None))
                        | (LeadNotificationOutbox.next_retry_at <= current)
                    )
                ),
                (
                    (LeadNotificationOutbox.status == "sending")
                    & (LeadNotificationOutbox.updated_at <= stale_sending)
                ),
            )
        )
        .order_by(LeadNotificationOutbox.created_at, LeadNotificationOutbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    event = session.scalar(statement)
    if event is None:
        return None
    event.status = "sending"
    event.updated_at = current
    event.next_retry_at = None
    session.commit()
    return event


def mark_delivery_result(
    session: Session,
    event_id: str,
    *,
    delivered: bool,
    error_code: str | None,
    max_retries: int,
    retry_seconds: int,
    now: datetime | None = None,
) -> None:
    """记录投递结果；失败重试不会修改或回滚业务线索。"""

    current = now or datetime.utcnow()
    event = session.get(LeadNotificationOutbox, event_id)
    if event is None:
        return
    if delivered:
        event.status = "sent"
        event.sent_at = current
        event.last_error_code = None
        event.next_retry_at = None
    else:
        event.retry_count += 1
        event.last_error_code = error_code or "delivery_failed"
        if event.retry_count >= max_retries:
            event.status = "failed"
            event.next_retry_at = None
        else:
            event.status = "retry"
            # 线性退避足够覆盖个人项目的轻量 Webhook；上限避免异常配置
            # 让数据库时间溢出，重试次数本身也受 Settings 约束。
            delay = retry_seconds * event.retry_count
            event.next_retry_at = current + timedelta(seconds=delay)
    event.updated_at = current
    session.commit()
