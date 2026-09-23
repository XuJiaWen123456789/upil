"""把对话规划结果装配为统一上下文 Envelope。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from backend.app.context.contracts import (
    ContextEnvelope,
    ContextField,
    ContextSource,
    ContextTrust,
)
from backend.app.services.access_control import AccessContext
from backend.app.dialogue import TurnDecision


def _field(value: object, *, source: str, trust: int, persistable: bool = False) -> ContextField | None:
    """只为存在的值创建带边界的上下文字段。"""

    if value is None:
        return None
    return ContextField(value=value, source=source, trust=trust, persistable=persistable)


def _safe_turns(turns: Sequence[Mapping[str, str]] | None) -> tuple[Mapping[str, str], ...]:
    """裁剪历史轮次，防止不受控文本绕过短期上下文预算。"""

    if not turns:
        return ()
    result: list[Mapping[str, str]] = []
    for turn in turns[-10:]:
        role = str(turn.get("role", ""))[:16]
        content = str(turn.get("content", ""))[:2000]
        if role in {"user", "assistant"} and content:
            result.append({"role": role, "content": content})
    return tuple(result)


def _safe_structured_memories(
    memories: Sequence[Mapping[str, str]] | None,
) -> tuple[Mapping[str, str], ...]:
    """只接受长期记忆服务输出的键和值，不把内部元数据传播给 Agent。"""

    if not memories:
        return ()
    result: list[Mapping[str, str]] = []
    for memory in memories[:10]:
        key = str(memory.get("key", ""))[:64]
        value = str(memory.get("value", ""))[:500]
        if key and value:
            result.append({"key": key, "value": value})
    return tuple(result)


def assemble_context(
    *,
    access_context: AccessContext,
    request_id: str | None,
    conversation_id: str | None,
    message: str,
    rewritten_query: str,
    route: str,
    decision: TurnDecision | None = None,
    active_entity=None,
    child_age: int | None = None,
    programming_foundation: str | None = None,
    class_time_preference: str | None = None,
    pending_intent: str | None = None,
    rolling_summary: str = "",
    recent_turns: Sequence[Mapping[str, str]] | None = None,
    structured_memories: Sequence[Mapping[str, str]] | None = None,
) -> ContextEnvelope:
    """创建请求级 Envelope。

    入口文本必须已经完成联系方式脱敏；本函数不尝试从原文提取手机号、
    邮箱或其他敏感字段，也不把 learner_id/class_id 当作通用长期记忆。
    """

    return ContextEnvelope(
        access_context=access_context,
        request_id=request_id,
        conversation_id=conversation_id,
        message=message[:2000],
        rewritten_query=rewritten_query[:2000],
        route=route,
        decision=decision,
        active_entity=active_entity,
        child_age=_field(child_age, source=ContextSource.SESSION, trust=ContextTrust.CONFIRMED),
        programming_foundation=_field(
            programming_foundation,
            source=ContextSource.SESSION,
            trust=ContextTrust.CONFIRMED,
        ),
        class_time_preference=_field(
            class_time_preference,
            source=ContextSource.SESSION,
            trust=ContextTrust.CONFIRMED,
        ),
        pending_intent=_field(
            pending_intent,
            source=ContextSource.SESSION,
            trust=ContextTrust.CONFIRMED,
        ),
        rolling_summary=rolling_summary[:4000],
        recent_turns=_safe_turns(recent_turns),
        structured_memories=_safe_structured_memories(structured_memories),
        trace={"request_id": request_id or ""},
    )
