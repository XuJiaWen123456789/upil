"""带 TTL、容量和主体隔离的进程内会话存储。"""

from __future__ import annotations

from threading import RLock
import time
from typing import Callable, TypeVar

from backend.app.memory.conversation.contracts import ConversationMemory, ConversationSubject
from backend.app.memory.conversation.key_builder import build_conversation_key
from backend.app.memory.conversation.serialization import (
    memory_from_payload,
    memory_is_empty,
    memory_to_payload,
)


T = TypeVar("T")


class InMemoryConversationStore:
    """本地开发和自动化测试使用的会话实现。"""

    def __init__(self, *, ttl_seconds: float = 1800, max_entries: int = 10000) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("会话 TTL 和容量必须为正数")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, ConversationMemory] = {}
        self._lock = RLock()

    def _prune_locked(self, now: float) -> None:
        expired = [
            key
            for key, value in self._entries.items()
            if now - value.updated_at >= self.ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)
        while len(self._entries) >= self.max_entries:
            oldest = min(self._entries, key=lambda key: self._entries[key].updated_at)
            self._entries.pop(oldest, None)

    def _entry(self, key: str) -> ConversationMemory:
        now = time.monotonic()
        with self._lock:
            current = self._entries.get(key)
            if current is not None and now - current.updated_at < self.ttl_seconds:
                return current
            if current is not None:
                self._entries.pop(key, None)
            self._prune_locked(now)
            current = ConversationMemory(updated_at=now)
            self._entries[key] = current
            return current

    def process(
        self,
        conversation_id: str | None,
        processor: Callable[[ConversationMemory], T],
        *,
        subject: ConversationSubject | None = None,
    ) -> T:
        """同一主体会话串行更新；无会话 ID 时保持无状态。"""

        if conversation_id is None:
            return processor(ConversationMemory())
        entry = self._entry(build_conversation_key(conversation_id, subject))
        with entry.lock:
            result = processor(entry)
            entry.version += 1
            entry.updated_at = time.monotonic()
            return result

    def read(
        self,
        conversation_id: str | None,
        *,
        subject: ConversationSubject | None = None,
    ) -> ConversationMemory:
        """在锁内复制只读快照，避免读取操作伪造一次写入版本。"""

        if conversation_id is None:
            return ConversationMemory()
        entry = self._entry(build_conversation_key(conversation_id, subject))
        with entry.lock:
            return ConversationMemory(
                active_entity=entry.active_entity,
                child_age=entry.child_age,
                programming_foundation=entry.programming_foundation,
                class_time_preference=entry.class_time_preference,
                pending_intent=entry.pending_intent,
                rolling_summary=entry.rolling_summary,
                recent_turns=list(entry.recent_turns),
                version=entry.version,
                updated_at=entry.updated_at,
            )

    def restore(
        self,
        conversation_id: str,
        memory: ConversationMemory,
        *,
        subject: ConversationSubject | None = None,
        only_if_empty: bool = True,
    ) -> bool:
        """原子恢复一份独立副本，不能与调用方共享可变列表或锁。"""

        key = build_conversation_key(conversation_id, subject)
        now = time.monotonic()
        with self._lock:
            current = self._entries.get(key)
            if current is not None and now - current.updated_at >= self.ttl_seconds:
                self._entries.pop(key, None)
                current = None
            if current is not None and only_if_empty and not memory_is_empty(current):
                return False
            # 经过白名单序列化再还原，既复制嵌套轮次，也排除未来误加到
            # ConversationMemory 上但尚未获准持久化的字段。
            restored = memory_from_payload(memory_to_payload(memory))
            restored.updated_at = now
            self._entries[key] = restored
            return True

    def clear(
        self,
        conversation_id: str | None = None,
        *,
        subject: ConversationSubject | None = None,
    ) -> None:
        """清除全部状态，或只删除一个主体会话。"""

        with self._lock:
            if conversation_id is None:
                self._entries.clear()
            else:
                self._entries.pop(build_conversation_key(conversation_id, subject), None)
