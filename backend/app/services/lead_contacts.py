"""招生联系方式的提取、脱敏、加密和受控解密。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken


PHONE_PATTERN = re.compile(r"(?<!\d)(?:(?:\+?86)[ -]?)?1[3-9]\d(?:[ -]?\d){8}(?!\d)")
PHONE_CANDIDATE_PATTERN = re.compile(r"(?<!\d)1(?:[ -]?\d){8,14}(?!\d)")
# 这里只按 ASCII 邮箱字符判断边界，不能使用 Unicode ``\w``。中文里的
# “或”“是”等字符也会被 ``\w`` 识别为单词字符，导致
# “手机号或parent@example.com”中的邮箱漏脱敏。
EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9_.-])"
)
REDACTED_CONTACT = "[联系方式已脱敏]"


class ContactProtectionSettings(Protocol):
    app_env: str
    lead_contact_encryption_key: str
    lead_contact_fingerprint_key: str


class ContactProtectionError(RuntimeError):
    """联系方式配置缺失、密文损坏或输入不合法。"""


@dataclass(frozen=True)
class ExtractedContact:
    contact_type: str
    normalized: str
    masked: str


@dataclass(frozen=True)
class ContactExtraction:
    redacted_text: str
    contacts: tuple[ExtractedContact, ...]
    # 疑似手机号但长度或号段不合法；它不进入 contacts，也不应进入任何模型
    # 或记忆存储，只用于向已有线索返回明确的格式提示。
    has_invalid_contact_candidate: bool = False


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits


def _mask_email(value: str) -> str:
    local, domain = value.split("@", 1)
    visible = local[0] if local else "*"
    return f"{visible}{'*' * max(3, len(local) - 1)}@{domain}"


def extract_contacts(message: str) -> ContactExtraction:
    """在任何模型或 FAQ 调用前移除联系方式和疑似错误号码。

    合法手机号/邮箱返回给线索服务做加密保存；疑似错误手机号只返回布尔
    标记，并同样替换成统一占位符，防止它进入 Supervisor、旁路 Agent、
    短期摘要或长期记忆。
    """

    matches: list[tuple[int, int, ExtractedContact]] = []
    invalid_spans: list[tuple[int, int]] = []
    for found in PHONE_CANDIDATE_PATTERN.finditer(message):
        normalized = _normalize_phone(found.group(0))
        if re.fullmatch(r"1[3-9]\d{9}", normalized):
            matches.append((
                found.start(),
                found.end(),
                ExtractedContact("phone", normalized, f"{normalized[:3]}****{normalized[-4:]}"),
            ))
        else:
            invalid_spans.append((found.start(), found.end()))
    for found in EMAIL_PATTERN.finditer(message):
        normalized = found.group(0).lower()
        matches.append((
            found.start(), found.end(), ExtractedContact("email", normalized, _mask_email(normalized))
        ))
    matches.sort(key=lambda item: item[0])

    replacement_spans = [(start, end) for start, end, _ in matches] + invalid_spans
    replacement_spans.sort()
    redacted = message
    for start, end in reversed(replacement_spans):
        redacted = redacted[:start] + REDACTED_CONTACT + redacted[end:]
    return ContactExtraction(
        redacted_text=redacted,
        contacts=tuple(item[2] for item in matches),
        has_invalid_contact_candidate=bool(invalid_spans),
    )


class ContactProtector:
    """Fernet 提供保密与完整性，HMAC 指纹只用于确定性去重。"""

    def __init__(self, encryption_key: bytes, fingerprint_key: bytes) -> None:
        if len(fingerprint_key) < 32:
            raise ContactProtectionError("联系方式指纹密钥长度不足")
        try:
            self._fernet = Fernet(encryption_key)
        except (TypeError, ValueError) as exc:
            raise ContactProtectionError("联系方式加密密钥不合法") from exc
        self._fingerprint_key = fingerprint_key

    @classmethod
    def from_settings(cls, settings: ContactProtectionSettings) -> "ContactProtector":
        encryption = settings.lead_contact_encryption_key.strip()
        fingerprint = settings.lead_contact_fingerprint_key.strip()
        if not encryption or not fingerprint:
            if settings.app_env.strip().lower() == "production":
                raise ContactProtectionError("生产环境未配置招生联系方式密钥")
            # 固定派生值只供 Demo/测试数据库使用，不能用于真实联系方式。
            encryption = base64.urlsafe_b64encode(
                hashlib.sha256(b"upil-demo-contact-encryption-only").digest()
            ).decode("ascii")
            fingerprint = hashlib.sha256(b"upil-demo-contact-hmac-only").hexdigest()
        return cls(encryption.encode("ascii"), fingerprint.encode("utf-8"))

    def encrypt(self, contact: ExtractedContact) -> str:
        payload = f"{contact.contact_type}:{contact.normalized}".encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def fingerprint(self, contact: ExtractedContact) -> str:
        payload = f"{contact.contact_type}:{contact.normalized}".encode("utf-8")
        return hmac.new(self._fingerprint_key, payload, hashlib.sha256).hexdigest()

    def decrypt(self, ciphertext: str, expected_type: str) -> str:
        try:
            payload = self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ContactProtectionError("联系方式密文无法验证") from exc
        prefix = f"{expected_type}:"
        if not payload.startswith(prefix):
            raise ContactProtectionError("联系方式类型与密文不一致")
        return payload[len(prefix):]
