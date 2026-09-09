"""真实模型的可选冒烟测试。

默认跳过，只有显式设置 UPIL_RUN_REAL_LLM_TESTS=true 时才访问网络，避免
日常回归测试产生费用、受 429 限流影响或依赖外部服务稳定性。
"""

from __future__ import annotations

import os

import pytest

from backend.app.config import get_settings
from backend.app.conversation_understanding import IntentType
from backend.app.integrations.llm import build_langchain_llm
from backend.app.services.intent_recognition import RecognitionSource, recognize_intent_detailed


RUN_REAL_LLM = os.getenv("UPIL_RUN_REAL_LLM_TESTS", "false").lower() == "true"


@pytest.mark.skipif(not RUN_REAL_LLM, reason="未显式启用真实模型测试")
def test_real_model_returns_valid_course_intent() -> None:
    """真实模型应能按项目契约返回课程详情意图。"""

    settings = get_settings()
    model = build_langchain_llm(settings)
    if model is None:
        pytest.fail("已请求真实模型测试，但 LLM_* 配置或 langchain-openai 不完整")

    outcome = recognize_intent_detailed(
        "编程项目实践班适合多大孩子？需要什么基础？一节课多长时间？",
        model=model,
    )
    result = outcome.result
    # 避免模型请求失败后由确定性回退“恰好答对”而产生假阳性。
    assert outcome.source == RecognitionSource.MODEL
    assert result.intent == IntentType.COURSE_DETAIL
    assert result.mentioned_entity is not None
    assert result.mentioned_entity.entity_name == "编程项目实践班"
    assert {"age_range", "duration", "prerequisite"}.issubset(
        result.requested_attributes
    )
