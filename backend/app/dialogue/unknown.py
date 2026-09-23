"""UNKNOWN 消息分类与固定回答边界。"""

from __future__ import annotations

import re

from backend.app.conversation_understanding import (
    EntityReference,
    IntentResult,
    IntentType,
    has_course_reference,
)
from backend.app.dialogue.contracts import UnknownKind


_GREETING_PATTERNS = ("你好", "您好", "嗨", "哈喽", "在吗")
_COURTESY_PATTERNS = ("谢谢", "感谢", "好的", "好嘞", "明白了", "知道了")
_OUT_OF_SCOPE_PATTERNS = (
    "股票", "股市", "基金走势", "比特币", "数字货币", "天气预报",
    "彩票", "做饭", "菜谱", "旅游攻略", "写一篇论文", "代写作业",
)
_IN_DOMAIN_PATTERNS = (
    "课程", "班型", "上课", "校区", "老师", "教师", "请假", "补课",
    "调课", "退费", "试听", "报名", "学情", "学习报告", "课时",
    "活动", "装备", "舞蹈", "美术", "音乐", "编程",
)


def _compact_text(message: str) -> str:
    return re.sub(r"[\s，。！？!?、；;~～]+", "", message).casefold()


def is_greeting(message: str) -> bool:
    """只把纯问候识别为寒暄，避免截断“你好，都有什么课程”。"""

    normalized = _compact_text(message)
    return normalized in _GREETING_PATTERNS or normalized in {f"{item}呀" for item in _GREETING_PATTERNS}


def is_courtesy(message: str) -> bool:
    """识别不会改变业务流程的礼貌回应。"""

    normalized = _compact_text(message)
    return normalized in _COURTESY_PATTERNS or normalized in {f"{item}你" for item in _COURTESY_PATTERNS}


def is_out_of_scope(message: str) -> bool:
    """识别明确超出教培咨询范围的高精度样本。"""

    return any(pattern in message for pattern in _OUT_OF_SCOPE_PATTERNS)


def classify_unknown_kind(
    message: str,
    *,
    result: IntentResult,
    active_entity: EntityReference | None,
) -> UnknownKind | None:
    """为低置信度、缺信息和域外消息选择互斥类型。"""

    if is_greeting(message) or is_courtesy(message):
        return UnknownKind.SMALL_TALK
    if (
        result.clarification_needed
        or (has_course_reference(message) and active_entity is None)
    ):
        return UnknownKind.NEEDS_CLARIFICATION
    if result.needs_live_data and result.intent in {
        IntentType.SCHEDULE_OR_SEAT,
        IntentType.FEE_REFUND,
        IntentType.CLASS_TRANSFER,
    }:
        return UnknownKind.UNSUPPORTED_IN_DOMAIN
    if is_out_of_scope(message):
        return UnknownKind.OUT_OF_SCOPE
    if result.intent != IntentType.UNKNOWN:
        return None
    if any(pattern in message for pattern in _IN_DOMAIN_PATTERNS):
        return UnknownKind.IN_DOMAIN_GENERAL
    return UnknownKind.UNKNOWN
