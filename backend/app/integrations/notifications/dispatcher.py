"""招生线索通知派发与后台补偿循环。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings
from backend.app.db import SessionLocal
from backend.app.integrations.notifications.contracts import NotificationMessage, NotificationSender
from backend.app.integrations.notifications.feishu import FeishuWebhookSender
from backend.app.integrations.notifications.models import LeadNotificationOutbox
from backend.app.integrations.notifications.outbox import (
    EVENT_CONTACT_AUTHORIZED,
    EVENT_HIGH_WAITING_CONTACT,
    EVENT_MEDIUM_CREATED,
    claim_due_notification,
    mark_delivery_result,
)


logger = logging.getLogger(__name__)
SenderFactory = Callable[[Settings], NotificationSender]


def _sender(settings: Settings) -> NotificationSender:
    return FeishuWebhookSender(
        settings.feishu_webhook_url,
        timeout_seconds=settings.lead_notification_timeout_seconds,
    )


def _message(event: LeadNotificationOutbox, settings: Settings) -> NotificationMessage:
    payload = event.payload_json if isinstance(event.payload_json, dict) else {}
    labels = {
        EVENT_MEDIUM_CREATED: "新增中意向招生线索",
        EVENT_HIGH_WAITING_CONTACT: "新增高意向线索（待联系方式授权）",
        EVENT_CONTACT_AUTHORIZED: "高意向线索已授权联系方式",
    }
    interest_labels = {"trial": "试听", "enrollment": "报名", "unknown": "待确认"}
    return NotificationMessage(
        title=f"【uPil】{labels.get(event.event_type, '招生线索更新')}",
        lines=(
            f"课程：{str(payload.get('course_name') or '待确认课程')[:100]}",
            f"意向：{interest_labels.get(str(payload.get('interest_type')), '待确认')}",
            "联系方式：已授权，请登录系统查看"
            if payload.get("contact_authorized")
            else "联系方式：尚未授权",
        ),
        detail_url=settings.lead_notification_detail_base_url.rstrip("/") + "/teacher/leads",
    )


def dispatch_due_notifications(
    settings: Settings,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    sender_factory: SenderFactory = _sender,
    limit: int = 20,
) -> int:
    """派发一批到期事件，返回本轮处理数量。

    先提交 sending 状态再访问网络，因此 Webhook 慢或失败时不会占用创建
    线索的事务。崩溃恢复可能产生重复提醒，顾问操作仍由系统幂等约束。
    """

    if not settings.lead_notification_enabled or not settings.feishu_webhook_url.strip():
        return 0
    sender = sender_factory(settings)
    processed = 0
    for _ in range(max(1, limit)):
        with session_factory() as session:
            event = claim_due_notification(session)
            if event is None:
                break
            event_id = event.id
            message = _message(event, settings)
        result = sender.send(message)
        with session_factory() as session:
            mark_delivery_result(
                session,
                event_id,
                delivered=result.delivered,
                error_code=result.error_code,
                max_retries=settings.lead_notification_max_retries,
                retry_seconds=settings.lead_notification_retry_seconds,
            )
        processed += 1
    return processed


async def notification_dispatch_loop(settings: Settings) -> None:
    """应用生命周期内运行的轻量补偿循环。"""

    while True:
        try:
            processed = await asyncio.to_thread(dispatch_due_notifications, settings)
            if processed:
                logger.info("lead_notification_dispatch processed=%d", processed)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 日志只保留稳定事件名，不输出 Webhook、载荷或第三方异常。
            logger.warning("lead_notification_dispatch_failed")
        await asyncio.sleep(settings.lead_notification_poll_seconds)
