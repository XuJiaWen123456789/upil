"""通知渠道共享契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    """已经脱敏、可以发送到外部渠道的通知。"""

    title: str
    lines: tuple[str, ...]
    detail_url: str


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """稳定的投递结果，不向业务层传播第三方响应正文。"""

    delivered: bool
    error_code: str | None = None


class NotificationSender(Protocol):
    """飞书、钉钉和邮件适配器共同遵循的最小接口。"""

    def send(self, message: NotificationMessage) -> DeliveryResult:
        """发送一条通知，并返回经过归一化的结果。"""
