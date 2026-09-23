"""会话存储键构造。"""

from __future__ import annotations

from hashlib import sha256

from backend.app.memory.conversation.contracts import ConversationSubject


def build_conversation_key(
    conversation_id: str,
    subject: ConversationSubject | None = None,
) -> str:
    """生成不直接暴露用户标识的稳定会话键。

    旧的内部调用没有认证主体时仍按 conversation_id 工作；HTTP 入口必须
    传入可信主体，从而阻止两个用户使用相同前端 ID 时共享会话状态。
    """

    if subject is None:
        return f"legacy:{conversation_id}"
    raw = "\x1f".join(
        (subject.tenant_id, subject.user_id, subject.role, conversation_id)
    ).encode("utf-8")
    return f"subject:{sha256(raw).hexdigest()}"
