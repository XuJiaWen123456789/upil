"""记忆层异常。"""


class MemoryPolicyError(ValueError):
    """候选记忆不满足隐私或业务准入策略。"""


class MemoryRepositoryError(RuntimeError):
    """记忆存储失败；不得阻断主聊天回答。"""
