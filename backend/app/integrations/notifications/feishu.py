"""飞书自定义机器人 Webhook 适配器。"""

from __future__ import annotations

import httpx

from backend.app.integrations.notifications.contracts import DeliveryResult, NotificationMessage


class FeishuWebhookSender:
    """只发送纯文本低敏摘要，不上传附件或联系方式。"""

    def __init__(self, webhook_url: str, *, timeout_seconds: float) -> None:
        self._webhook_url = webhook_url
        self._timeout_seconds = timeout_seconds

    def send(self, message: NotificationMessage) -> DeliveryResult:
        text = "\n".join((message.title, *message.lines, f"处理入口：{message.detail_url}"))
        try:
            response = httpx.post(
                self._webhook_url,
                json={"msg_type": "text", "content": {"text": text}},
                timeout=self._timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            return DeliveryResult(False, "timeout")
        except httpx.HTTPError:
            return DeliveryResult(False, "network_error")

        if response.status_code >= 500:
            return DeliveryResult(False, "provider_unavailable")
        if response.status_code >= 400:
            return DeliveryResult(False, "provider_rejected")
        try:
            body = response.json()
        except ValueError:
            return DeliveryResult(False, "invalid_response")
        # 飞书成功响应通常使用 StatusCode=0 或 code=0；兼容两种字段，
        # 但绝不把响应中的 msg、请求 ID 或其他正文写入数据库和日志。
        code = body.get("StatusCode", body.get("code")) if isinstance(body, dict) else None
        return (
            DeliveryResult(True)
            if code == 0
            else DeliveryResult(False, "provider_rejected")
        )
