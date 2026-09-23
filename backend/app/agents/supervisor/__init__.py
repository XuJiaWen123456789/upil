"""Supervisor 意图识别智能体。

Supervisor 只负责把自然语言映射到受控的业务意图，不直接生成客服话术，
也不直接执行数据库或外部系统工具。
"""

from .contracts import IntentRecognitionOutcome, RecognitionSource, StructuredIntentModel
from .prompt import build_intent_prompt
from .rules import deterministic_fallback
from .service import recognize_intent, recognize_intent_detailed

__all__ = [
    "IntentRecognitionOutcome",
    "RecognitionSource",
    "StructuredIntentModel",
    "build_intent_prompt",
    "deterministic_fallback",
    "recognize_intent",
    "recognize_intent_detailed",
]
