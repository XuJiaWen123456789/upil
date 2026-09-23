"""可选情景记忆协议；当前默认关闭。"""

from __future__ import annotations

from typing import Protocol

from backend.app.memory.episodic.contracts import (
    EpisodicMemoryEvent,
    EpisodicMemorySnippet,
    EpisodicMemoryStore,
)
from backend.app.memory.episodic.recall import recall_episodic_memory
from backend.app.memory.episodic.repository import NoopEpisodicMemoryStore
from backend.app.memory.episodic.writer import write_episodic_memory


class EpisodicMemorySettings(Protocol):
    """构建情景记忆存储所需的最小配置。"""

    episodic_memory_enabled: bool
    episodic_embedding_model: str


def build_episodic_memory_store(settings: EpisodicMemorySettings) -> EpisodicMemoryStore:
    """按配置创建情景记忆后端。

    本阶段只提供协议和空实现。即使打开开关但没有嵌入模型，也明确返回空
    存储；不会偷偷切换到未经评测的词法检索，更不会和 RAGFlow 形成第二套
    知识库。
    """

    if not settings.episodic_memory_enabled:
        return NoopEpisodicMemoryStore(reason="disabled")
    if not settings.episodic_embedding_model.strip():
        return NoopEpisodicMemoryStore(reason="embedding_model_missing")
    return NoopEpisodicMemoryStore(reason="backend_not_configured")


__all__ = [
    "EpisodicMemoryEvent",
    "EpisodicMemorySnippet",
    "EpisodicMemoryStore",
    "NoopEpisodicMemoryStore",
    "build_episodic_memory_store",
    "recall_episodic_memory",
    "write_episodic_memory",
]
