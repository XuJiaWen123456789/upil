"""长期记忆的确定性准入策略。"""

from __future__ import annotations

import re

from backend.app.memory.exceptions import MemoryPolicyError
from backend.app.memory.types import MemoryCandidate


_SENSITIVE_PATTERN = re.compile(
    # 手机号必须使用真正的数字匹配；双反斜杠会把 \\d 当成字面量，
    # 导致最重要的联系方式拦截规则在运行时失效。
    r"(?:1[3-9]\d{9}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|身份证|银行卡|密码|token|密钥)",
    re.IGNORECASE,
)
_ALLOWED_KEYS = frozenset({"course_interest", "class_time_preference", "child_nickname"})
_ALLOWED_WRITE_BASES = frozenset({"explicit_user_request", "high_confidence_statement"})


def validate_candidate(candidate: MemoryCandidate) -> MemoryCandidate:
    """阻止敏感信息、推测标签和动态业务事实进入通用记忆。"""

    if candidate.memory_type != "structured_preference":
        raise MemoryPolicyError("当前长期记忆只允许保存结构化偏好")
    if candidate.memory_key not in _ALLOWED_KEYS:
        raise MemoryPolicyError("记忆字段不在允许的非敏感范围内")
    if not candidate.memory_value or any(
        not isinstance(value, str) or not value.strip()
        for value in candidate.memory_value.values()
    ):
        raise MemoryPolicyError("记忆值不能为空，且必须是文本")
    serialized = " ".join(candidate.memory_value.values())
    if _SENSITIVE_PATTERN.search(serialized):
        raise MemoryPolicyError("记忆候选包含敏感信息")
    if candidate.write_basis not in _ALLOWED_WRITE_BASES:
        raise MemoryPolicyError("长期记忆写入依据不受支持")
    if candidate.write_basis == "high_confidence_statement" and candidate.confidence < 0.85:
        # 自主判断只接受确定性规则给出的高置信度候选。低置信度内容宁可不记，
        # 也不能把一次试探、代问或模型猜测升级为跨会话长期事实。
        raise MemoryPolicyError("自主判断的长期记忆置信度不足")
    if not 0 <= candidate.confidence <= 1:
        raise MemoryPolicyError("记忆置信度必须在 0 至 1 之间")
    if any(len(value.strip()) > 100 for value in candidate.memory_value.values()):
        raise MemoryPolicyError("结构化长期记忆值过长")
    return candidate
