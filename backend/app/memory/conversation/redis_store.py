"""基于 Redis 的主体隔离短期会话存储。

Redis 版本只负责保存已经脱敏的 ConversationMemory。它不理解课程业务，
也不保存认证 Token、联系方式或数据库查询结果。所有状态更新都在同一主体
同一会话的分布式锁内完成，保证多进程部署时不会互相覆盖最近对话。
"""

from __future__ import annotations

import math
import json
import time
from collections.abc import Callable
from typing import Any, TypeVar

from backend.app.memory.conversation.contracts import ConversationMemory, ConversationSubject
from backend.app.memory.conversation.key_builder import build_conversation_key
from backend.app.memory.conversation.serialization import (
    memory_from_payload,
    memory_is_empty,
    memory_to_payload,
)
from backend.app.memory.exceptions import MemoryRepositoryError

T = TypeVar("T")


class RedisConversationStore:
    """使用外部 Redis 共享短期会话，Redis 客户端通过工厂延迟注入。"""

    _KEY_PREFIX = "upil:conversation:v1:"
    _LOCK_SUFFIX = ":lock"

    def __init__(self, client: Any, *, ttl_seconds: float = 1800, lock_timeout_seconds: float = 5) -> None:
        if ttl_seconds <= 0 or lock_timeout_seconds <= 0:
            raise ValueError("会话 TTL 和 Redis 锁超时必须为正数")
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.lock_timeout_seconds = lock_timeout_seconds

    def _key(self, conversation_id: str, subject: ConversationSubject | None) -> str:
        """统一复用主体隔离键，避免不同入口各自拼接 Redis Key。"""

        return f"{self._KEY_PREFIX}{build_conversation_key(conversation_id, subject)}"

    @staticmethod
    def _serialize(memory: ConversationMemory) -> str:
        """只序列化受控会话字段，不把 dataclass 锁或任意对象写入 Redis。"""
        return json.dumps(
            memory_to_payload(memory), ensure_ascii=False, separators=(",", ":")
        )

    @staticmethod
    def _deserialize(raw: Any) -> ConversationMemory:
        """把 Redis 内容恢复为协议对象；损坏状态直接失败而不是猜测修复。"""

        if raw is None:
            return ConversationMemory()
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return memory_from_payload(json.loads(raw))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryRepositoryError("Redis 会话状态格式无效") from exc

    def _load(self, key: str) -> ConversationMemory:
        try:
            return self._deserialize(self.client.get(key))
        except MemoryRepositoryError:
            raise
        except Exception as exc:
            raise MemoryRepositoryError("读取 Redis 会话状态失败") from exc

    def _save(self, key: str, memory: ConversationMemory) -> None:
        try:
            self.client.set(key, self._serialize(memory), ex=max(1, math.ceil(self.ttl_seconds)))
        except Exception as exc:
            raise MemoryRepositoryError("写入 Redis 会话状态失败") from exc

    def process(self, conversation_id: str | None, processor: Callable[[ConversationMemory], T], *, subject: ConversationSubject | None = None) -> T:
        """在分布式锁内读取、执行处理器并写回状态。"""

        if conversation_id is None:
            return processor(ConversationMemory())
        key = self._key(conversation_id, subject)
        try:
            lock = self.client.lock(
                f"{key}{self._LOCK_SUFFIX}",
                # 锁租约要覆盖一次模型路由的正常耗时，但不能与会话 30 分钟
                # TTL 绑定；进程崩溃后最多约 30 秒即可重新处理该会话。
                timeout=max(30, math.ceil(self.lock_timeout_seconds * 4)),
                blocking_timeout=self.lock_timeout_seconds,
            )
            if not lock.acquire():
                raise MemoryRepositoryError("Redis 会话锁获取超时")
        except MemoryRepositoryError:
            raise
        except Exception as exc:
            raise MemoryRepositoryError("创建 Redis 会话锁失败") from exc
        try:
            memory = self._load(key)
            result = processor(memory)
            memory.version += 1
            memory.updated_at = time.monotonic()
            self._save(key, memory)
            return result
        except MemoryRepositoryError:
            raise
        except Exception as exc:
            raise MemoryRepositoryError("Redis 会话处理失败") from exc
        finally:
            try:
                lock.release()
            except Exception as exc:
                raise MemoryRepositoryError("释放 Redis 会话锁失败") from exc

    def read(self, conversation_id: str | None, *, subject: ConversationSubject | None = None) -> ConversationMemory:
        """读取快照，不刷新 TTL，不增加版本号。"""

        if conversation_id is None:
            return ConversationMemory()
        return self._load(self._key(conversation_id, subject))

    def restore(
        self, conversation_id: str, memory: ConversationMemory, *,
        subject: ConversationSubject | None = None, only_if_empty: bool = True,
    ) -> bool:
        """在同一分布式锁内检查并恢复，防止并发请求覆盖新状态。"""

        key = self._key(conversation_id, subject)
        try:
            lock = self.client.lock(
                f"{key}{self._LOCK_SUFFIX}",
                timeout=max(30, math.ceil(self.lock_timeout_seconds * 4)),
                blocking_timeout=self.lock_timeout_seconds,
            )
            if not lock.acquire():
                raise MemoryRepositoryError("Redis 会话锁获取超时")
        except MemoryRepositoryError:
            raise
        except Exception as exc:
            raise MemoryRepositoryError("创建 Redis 会话锁失败") from exc
        try:
            current = self._load(key)
            if only_if_empty and not memory_is_empty(current):
                return False
            restored = memory_from_payload(memory_to_payload(memory))
            restored.updated_at = time.monotonic()
            self._save(key, restored)
            return True
        finally:
            try:
                lock.release()
            except Exception as exc:
                raise MemoryRepositoryError("释放 Redis 会话锁失败") from exc

    @classmethod
    def _is_lock_key(cls, key: Any) -> bool:
        """识别扫描结果中的锁键，避免清理会话时误删正在使用的锁。"""

        if isinstance(key, bytes):
            key = key.decode("utf-8", errors="ignore")
        return str(key).endswith(cls._LOCK_SUFFIX)

    def clear(self, conversation_id: str | None = None, *, subject: ConversationSubject | None = None) -> None:
        """删除单个主体会话或当前应用命名空间下的全部会话。"""

        try:
            if conversation_id is not None:
                self.client.delete(self._key(conversation_id, subject))
                return
            # Redis 的 scan 匹配会同时返回会话数据键和 :lock 键；清理
            # 数据时不能删除分布式锁，否则并发请求可能在同一会话上失去互斥。
            keys = [
                key
                for key in self.client.scan_iter(match=f"{self._KEY_PREFIX}*")
                if not self._is_lock_key(key)
            ]
            if keys:
                self.client.delete(*keys)
        except Exception as exc:
            raise MemoryRepositoryError("清理 Redis 会话状态失败") from exc
