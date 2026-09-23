"""持久会话的最终脱敏边界。"""

import re

from backend.app.services.lead_contacts import extract_contacts


_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:bearer\s+)?(?:sk-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9._-]+)"
)
_INTERNAL_URL_PATTERN = re.compile(
    r"(?i)(?<![a-z0-9.-])(?:https?://)?(?:localhost|127\.0\.0\.1|"
    r"[a-z0-9.-]+:(?:5432|6379|9000|9380|16380|18000|19000|19380|29000|29380))"
    r"(?::(?:5432|6379|9000|9380|16380|18000|19000|19380|29000|29380))?(?:/[^\s]*)?"
)


def redact_persistent_text(value: str, *, max_length: int) -> str:
    """再次移除联系方式、Token 与内部地址，并施加数据库长度上限。

    聊天入口已经先脱敏一次；这里仍做纵深防御，避免未来节点把敏感值拼入
    助手回答后进入 PostgreSQL。
    """

    redacted = extract_contacts(str(value or "")).redacted_text
    redacted = _TOKEN_PATTERN.sub("[凭据已隐藏]", redacted)
    redacted = _INTERNAL_URL_PATTERN.sub("[内部地址已隐藏]", redacted)
    return redacted[:max_length]
