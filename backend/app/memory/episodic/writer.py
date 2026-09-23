"""情景记忆写入门面。"""

from __future__ import annotations

from backend.app.memory.episodic.contracts import EpisodicMemoryEvent, EpisodicMemoryStore


def write_episodic_memory(store: EpisodicMemoryStore, event: EpisodicMemoryEvent) -> None:
    """统一写入入口，要求调用方已完成脱敏和准入判断。"""

    if not event.content.strip():
        return
    store.remember(
        EpisodicMemoryEvent(
            scope=event.scope,
            content=event.content[:2000],
            occurred_at=event.occurred_at,
            tags=tuple(event.tags[:10]),
        )
    )
