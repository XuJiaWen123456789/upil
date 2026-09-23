"""情景记忆召回门面。"""

from __future__ import annotations

from backend.app.memory.episodic.contracts import EpisodicMemorySnippet, EpisodicMemoryStore
from backend.app.memory.structured.contracts import MemoryScope


def recall_episodic_memory(
    store: EpisodicMemoryStore,
    scope: MemoryScope,
    query: str,
    *,
    limit: int = 5,
) -> tuple[EpisodicMemorySnippet, ...]:
    """对召回数量和查询长度做最后一道预算限制。"""

    if not query.strip() or limit <= 0:
        return ()
    return store.recall(scope, query[:1000], limit=min(limit, 10))
