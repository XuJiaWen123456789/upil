"""结构化长期记忆的准入和确定性候选提取。"""

from __future__ import annotations

import re

from backend.app.conversation_understanding import COURSE_CATEGORIES, normalize_course_name
from backend.app.memory.exceptions import MemoryPolicyError
from backend.app.memory.policies import validate_candidate
from backend.app.memory.types import MemoryCandidate
from backend.app.services.preference_values import extract_class_time_preference


# 显式记忆命令必须出现在句首，并带有明确的祈使表达。不能只判断消息中是否
# 包含“记住”二字，否则“请根据以前记住的偏好推荐课程”会被错误路由为一次
# 新的写入命令。这里保留常见自然表达，同时排除“还记得吗”“以前记住的”等
# 对既有记忆的引用。
_EXPLICIT_MEMORY_COMMAND_PATTERN = re.compile(
    r"^\s*(?:(?:(?:请|麻烦)(?:你)?)?(?:帮我)?(?:记住|记一下|记着)|"
    r"(?:以后|今后)记得|(?:我)?希望你记住)"
)
_REJECT_MEMORY_MARKERS = ("不要记", "别记", "不用记", "无需记")
_DYNAMIC_MARKERS = (
    "剩余课时", "缺勤", "出勤", "名额", "报告", "学情", "密码", "手机号", "电话", "邮箱",
)
_SENSITIVE_PATTERN = re.compile(
    r"(?:1[3-9]\d{9}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|token|密钥|身份证|银行卡)",
    re.IGNORECASE,
)
_UNCERTAIN_MARKERS = (
    "可能", "也许", "大概", "好像", "不确定", "不知道", "考虑一下", "再看看",
)
_TRANSIENT_MARKERS = (
    "今天", "明天", "后天", "这周", "本周", "这一次", "这次", "暂时", "先看看", "最近考虑",
)
_NEGATIVE_PREFERENCE_PATTERN = re.compile(
    r"(?:不|不太|不怎么|并不|没有)(?:喜欢|感兴趣|想学)|(?:不考虑|不想学|排除)"
)
_CHILD_SUBJECT_PATTERN = re.compile(r"(?:孩子|小朋友|宝宝|他|她)")
_COURSE_INTEREST_MARKERS = ("喜欢", "感兴趣", "有兴趣", "想学", "偏爱", "兴趣是")
_NICKNAME_PATTERN = re.compile(
    r"(?:孩子|小朋友|宝宝)?(?:的)?(?:小名|昵称)(?:叫|是|为)\s*([^，。！？\n]{1,20})"
)


def _explicit_request(message: str) -> bool:
    return bool(_EXPLICIT_MEMORY_COMMAND_PATTERN.search(message))


def is_explicit_memory_request(message: str) -> bool:
    """判断消息是否应优先进入“记忆命令”分支。

    记忆请求不能交给 FAQ/RAGFlow 自由生成回复，否则知识库中的旧客服话术
    可能会否定当前已经启用的长期记忆能力。这里仅识别“请记住、以后记得、
    帮我记一下”等明确命令；“孩子喜欢编程”这类普通陈述仍由正常咨询链路
    回答，并在请求结束后按自主准入策略异步固化。
    """

    if any(marker in message for marker in _REJECT_MEMORY_MARKERS):
        return False
    return _explicit_request(message)


def _candidate(*, key: str, value: str, owner_user_id: str, tenant_id: str,
               owner_role: str, learner_id: str | None, conversation_id: str | None,
               message_id: str | None, explicit: bool, confidence: float) -> MemoryCandidate:
    """集中构造候选，避免不同字段漏传主体隔离信息。"""

    return MemoryCandidate(
        owner_user_id=owner_user_id, tenant_id=tenant_id, owner_role=owner_role,
        learner_id=learner_id, memory_type="structured_preference", memory_key=key,
        memory_value={"value": value.strip()}, source_conversation_id=conversation_id,
        source_message_id=message_id,
        write_basis=("explicit_user_request" if explicit else "high_confidence_statement"),
        confidence=(1.0 if explicit else confidence),
    )


def _known_course_value(message: str) -> str | None:
    """返回课程白名单中的标准名称或课程方向，拒绝保存任意自由文本。"""

    canonical = normalize_course_name(message)
    if canonical:
        return canonical
    return next((category for category in COURSE_CATEGORIES if category in message), None)


def _extract_nickname(message: str) -> str | None:
    # 昵称同样必须是已经确认的稳定事实。“可能叫”“暂时叫”等内容即使
    # 携带显式记忆指令也不入库，避免错误昵称跨会话传播。
    if any(marker in message for marker in (*_UNCERTAIN_MARKERS, *_TRANSIENT_MARKERS)):
        return None
    match = _NICKNAME_PATTERN.search(message)
    if not match:
        return None
    value = re.sub(r"(?:呢|呀|啊)$", "", match.group(1).strip())
    # 昵称不接受数字、占位符和明显的关系词，避免把后续句子误截为名字。
    if not value or re.search(r"\d|已脱敏|上课|课程|喜欢|感兴趣", value):
        return None
    return value


def _extract_course_interest(message: str, *, explicit: bool) -> str | None:
    # 课程兴趣字段只表达已经成立的稳定偏好，不能承载“可能喜欢”或
    # “最近暂时想学”。即使消息中带有“请记住”，也不能把不确定或
    # 短期状态错误升级成确定的跨会话事实。
    if any(marker in message for marker in (*_UNCERTAIN_MARKERS, *_TRANSIENT_MARKERS)):
        return None
    value = _known_course_value(message)
    if value is None or not any(marker in message for marker in _COURSE_INTEREST_MARKERS):
        return None
    # 自主判断必须明确说的是孩子；“我想了解编程课”只是当前咨询，不能
    # 自动变成孩子的长期偏好。显式“请记住”仍允许省略重复出现的主语。
    if not explicit and not _CHILD_SUBJECT_PATTERN.search(message):
        return None
    return value


def extract_candidate(message: str, *, owner_user_id: str, tenant_id: str,
                      owner_role: str, learner_id: str | None = None,
                      conversation_id: str | None = None,
                      message_id: str | None = None) -> MemoryCandidate | None:
    """从显式记忆请求或高置信度稳定陈述中抽取一个白名单偏好。

    当前采用保守的确定性规则，不额外调用模型。昵称事实优先，其次是
    上课时间偏好和课程兴趣；一条消息包含多个偏好时先保存最明确的一项，
    后续轮次仍可继续补充，避免引入复杂的批量冲突事务。
    """

    explicit = _explicit_request(message)
    if any(marker in message for marker in _REJECT_MEMORY_MARKERS):
        # “不要记住”包含字面上的“记住”，必须先识别拒绝意图，不能被
        # 显式标记的子串误判为授权写入。
        return None
    if any(marker in message for marker in _DYNAMIC_MARKERS):
        return None
    # 联系方式与密钥不进入候选，即使后续策略再次拦截，也不把原文继续传播。
    if _SENSITIVE_PATTERN.search(message):
        return None
    # 非显式陈述出现不确定、临时或否定信号时直接放弃。显式请求仍不能
    # 把“孩子不喜欢编程”保存成正向兴趣，但可以记录明确的新昵称或时段。
    if not explicit and any(marker in message for marker in (*_UNCERTAIN_MARKERS, *_TRANSIENT_MARKERS)):
        return None

    extracted = (
        ("child_nickname", _extract_nickname(message), 0.98),
        ("class_time_preference", extract_class_time_preference(message, explicit=explicit), 0.92),
        (
            "course_interest",
            None if _NEGATIVE_PREFERENCE_PATTERN.search(message) else _extract_course_interest(message, explicit=explicit),
            0.9,
        ),
    )
    for key, value, confidence in extracted:
        if value:
            return _candidate(
                key=key, value=value, owner_user_id=owner_user_id, tenant_id=tenant_id,
                owner_role=owner_role, learner_id=learner_id,
                conversation_id=conversation_id, message_id=message_id,
                explicit=explicit, confidence=confidence,
            )
    return None


def admit_candidate(candidate: MemoryCandidate) -> MemoryCandidate:
    """统一调用策略层，阻止动态事实、敏感值和非白名单字段入库。"""

    return validate_candidate(candidate)
