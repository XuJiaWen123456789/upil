"""Supervisor 意图识别编排服务。

编排顺序固定为：确定性守卫 → 可选结构化模型 → 结构与业务校验 →
确定性回退。模型超时、非法输出和供应商异常都不会让客服链路失败。
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from backend.app.conversation_understanding import (
    EntityReference,
    IntentResult,
    resolve_turn,
)

from .contracts import IntentRecognitionOutcome, RecognitionSource, StructuredIntentModel
from .parsing import parse_model_output
from .prompt import build_intent_prompt
from .rules import deterministic_fallback, high_risk_result
from .validation import validate_business_result


def recognize_intent(
    message: str,
    *,
    active_entity: EntityReference | None = None,
    model: StructuredIntentModel | None = None,
) -> IntentResult:
    """识别本轮意图，并在任意模型异常下返回安全结果。"""

    return recognize_intent_detailed(
        message, active_entity=active_entity, model=model
    ).result


def recognize_intent_detailed(
    message: str,
    *,
    active_entity: EntityReference | None = None,
    model: StructuredIntentModel | None = None,
) -> IntentRecognitionOutcome:
    """返回业务结果和有限来源诊断，供监控与真实模型评估使用。"""

    turn = resolve_turn(message, active_entity)
    guarded = high_risk_result(message, turn)
    if guarded is not None:
        return IntentRecognitionOutcome(guarded, RecognitionSource.DETERMINISTIC_GUARD)
    if model is None:
        return IntentRecognitionOutcome(
            deterministic_fallback(message, active_entity=active_entity, turn=turn),
            RecognitionSource.DETERMINISTIC_FALLBACK,
            "model_not_configured",
        )

    prompt = build_intent_prompt(
        message,
        active_entity=active_entity,
        rewritten_query=turn.rewritten_query,
    )
    try:
        parsed = parse_model_output(model.invoke(prompt))
        return IntentRecognitionOutcome(
            validate_business_result(parsed, message=message, turn=turn),
            RecognitionSource.MODEL,
        )
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError, TimeoutError):
        return IntentRecognitionOutcome(
            deterministic_fallback(message, active_entity=active_entity, turn=turn),
            RecognitionSource.DETERMINISTIC_FALLBACK,
            "invalid_or_timed_out_model_output",
        )
    except Exception:
        # 供应商连接、限流等内部异常不回传给用户，也不写入可见事件。
        return IntentRecognitionOutcome(
            deterministic_fallback(message, active_entity=active_entity, turn=turn),
            RecognitionSource.DETERMINISTIC_FALLBACK,
            "model_provider_error",
        )
