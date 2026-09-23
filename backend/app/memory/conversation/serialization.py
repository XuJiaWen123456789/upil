"""ConversationMemory 的受控序列化与恢复。"""

from __future__ import annotations

import time
from typing import Any

from backend.app.conversation_understanding import EntityReference, IntentType
from backend.app.memory.conversation.contracts import ConversationMemory, ConversationTurn
from backend.app.memory.exceptions import MemoryRepositoryError


def memory_to_payload(memory: ConversationMemory, *, include_turns: bool = True) -> dict:
    """只导出协议白名单字段，供 Redis 和 PostgreSQL 快照共同使用。"""

    payload = {
        "active_entity": (
            memory.active_entity.model_dump(mode="json")
            if memory.active_entity else None
        ),
        "child_age": memory.child_age,
        "programming_foundation": memory.programming_foundation,
        "class_time_preference": memory.class_time_preference,
        "pending_intent": (
            memory.pending_intent.value
            if isinstance(memory.pending_intent, IntentType)
            else memory.pending_intent
        ),
        "rolling_summary": str(memory.rolling_summary or "")[:4000],
        "version": max(0, int(memory.version)),
    }
    payload["recent_turns"] = (
        [
            {
                "role": turn.role[:16],
                "content": turn.content[:4000],
                "created_at": float(turn.created_at),
            }
            for turn in memory.recent_turns[-60:]
            if turn.role in {"user", "assistant"} and turn.content
        ]
        if include_turns else []
    )
    return payload


def memory_from_payload(payload: dict[str, Any] | None) -> ConversationMemory:
    """从可信数据库快照或 Redis JSON 还原受控状态。"""

    if not payload:
        return ConversationMemory()
    try:
        entity_data = payload.get("active_entity")
        active_entity = EntityReference.model_validate(entity_data) if entity_data else None
        pending_raw = payload.get("pending_intent")
        pending_intent = IntentType(pending_raw) if pending_raw else None
        recent_turns = [
            ConversationTurn(
                role=str(item["role"]),
                content=str(item.get("content", ""))[:4000],
                created_at=float(item.get("created_at", time.time())),
            )
            for item in payload.get("recent_turns", [])[-60:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        return ConversationMemory(
            active_entity=active_entity,
            child_age=payload.get("child_age"),
            programming_foundation=payload.get("programming_foundation"),
            class_time_preference=payload.get("class_time_preference"),
            pending_intent=pending_intent,
            rolling_summary=str(payload.get("rolling_summary", ""))[:4000],
            recent_turns=recent_turns,
            version=max(0, int(payload.get("version", 0))),
            updated_at=time.monotonic(),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MemoryRepositoryError("会话状态格式无效") from exc


def memory_is_empty(memory: ConversationMemory) -> bool:
    """判断 Redis/内存状态是否确实没有可用上下文。"""

    return not any((
        memory.active_entity,
        memory.child_age is not None,
        memory.programming_foundation,
        memory.class_time_preference,
        memory.pending_intent,
        memory.rolling_summary,
        memory.recent_turns,
        memory.version,
    ))
