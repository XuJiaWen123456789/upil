"""Supervisor 意图识别的历史兼容门面。

实现已拆到 ``backend.app.agents.supervisor``：协议、规则、Prompt、解析、
业务校验和编排分别维护。本模块只重导出旧路径曾提供的公开符号，避免现有
对话状态服务、评估脚本和外部集成因目录优化失效。
"""

from backend.app.agents.supervisor.constants import (
    ALLOWED_REQUESTED_ATTRIBUTES,
    CLASS_LEARNING_CUES,
    CLASS_LEARNING_METRIC_KEYWORDS,
    CLASS_LEARNING_PERIOD_PATTERNS,
    COMPLAINT_KEYWORDS,
    COURSE_CATEGORY_MENTIONS,
    HUMAN_HANDOFF_KEYWORDS,
    LEARNING_DATA_KEYWORDS,
    LEARNING_REPORT_KEYWORDS,
    LEARNING_REPORT_PERIOD_KEYWORDS,
    REPORT_HISTORY_KEYWORDS,
    LOW_CONFIDENCE_THRESHOLD,
    REFUND_LIVE_DATA_KEYWORDS,
    SCHEDULE_DATA_KEYWORDS,
    STATIC_SERVICE_RULES_KEYWORDS,
)
from backend.app.agents.supervisor.contracts import (
    IntentRecognitionOutcome,
    RecognitionSource,
    StructuredIntentModel,
)
from backend.app.agents.supervisor.prompt import build_intent_prompt
from backend.app.agents.supervisor.rules import deterministic_fallback
from backend.app.agents.supervisor.service import (
    recognize_intent,
    recognize_intent_detailed,
)

__all__ = [
    "ALLOWED_REQUESTED_ATTRIBUTES",
    "CLASS_LEARNING_CUES",
    "CLASS_LEARNING_METRIC_KEYWORDS",
    "CLASS_LEARNING_PERIOD_PATTERNS",
    "COMPLAINT_KEYWORDS",
    "COURSE_CATEGORY_MENTIONS",
    "HUMAN_HANDOFF_KEYWORDS",
    "IntentRecognitionOutcome",
    "LEARNING_DATA_KEYWORDS",
    "LEARNING_REPORT_KEYWORDS",
    "LEARNING_REPORT_PERIOD_KEYWORDS",
    "REPORT_HISTORY_KEYWORDS",
    "LOW_CONFIDENCE_THRESHOLD",
    "REFUND_LIVE_DATA_KEYWORDS",
    "RecognitionSource",
    "SCHEDULE_DATA_KEYWORDS",
    "STATIC_SERVICE_RULES_KEYWORDS",
    "StructuredIntentModel",
    "build_intent_prompt",
    "deterministic_fallback",
    "recognize_intent",
    "recognize_intent_detailed",
]
