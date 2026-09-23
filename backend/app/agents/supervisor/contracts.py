"""Supervisor 的稳定协议和识别结果契约。

本模块不包含关键词和业务路由规则，只定义模型适配器与上层工作流之间的
最小接口，避免供应商 SDK 类型渗透到对话状态。
"""

from enum import Enum
from typing import Any, Protocol

from backend.app.conversation_understanding import IntentResult


class StructuredIntentModel(Protocol):
    """结构化意图模型的最小协议。"""

    def invoke(self, prompt: str) -> Any:
        """接收提示词并返回 JSON 字符串、字典或消息对象。"""


class RecognitionSource(str, Enum):
    """本轮结果的实际来源，用于评估和有限度的可观测性。"""

    DETERMINISTIC_GUARD = "deterministic_guard"
    MODEL = "model"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class IntentRecognitionOutcome:
    """业务结果和安全来源诊断。

    不保存 Prompt、模型原文或底层异常，避免诊断对象成为敏感数据泄漏通道。
    """

    def __init__(
        self,
        result: IntentResult,
        source: RecognitionSource,
        fallback_reason: str | None = None,
    ) -> None:
        self.result = result
        self.source = source
        self.fallback_reason = fallback_reason
