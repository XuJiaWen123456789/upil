"""短期会话存储工厂。

Redis 依赖只在显式选择 redis 后端时导入。离线开发和测试不需要安装 Redis
客户端；一旦选择 Redis，依赖缺失或服务不可用会明确失败，不能悄悄退回内存。
"""

from __future__ import annotations

from typing import Protocol

from backend.app.memory.conversation.contracts import ConversationStore
from backend.app.memory.conversation.in_memory_store import InMemoryConversationStore
from backend.app.memory.conversation.redis_store import RedisConversationStore
from backend.app.memory.exceptions import MemoryRepositoryError


class ConversationStoreSettings(Protocol):
    conversation_store_backend: str
    conversation_ttl_seconds: int
    conversation_max_entries: int
    redis_url: str
    redis_timeout_seconds: float


def build_conversation_store(settings: ConversationStoreSettings) -> ConversationStore:
    """按配置创建唯一会话后端，并在 Redis 模式启动时验证连通性。"""

    if settings.conversation_store_backend == "memory":
        return InMemoryConversationStore(
            ttl_seconds=settings.conversation_ttl_seconds,
            max_entries=settings.conversation_max_entries,
        )
    if settings.conversation_store_backend != "redis":
        raise ValueError("不支持的会话存储后端")
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("已选择 Redis 会话后端，但未安装 redis 依赖，请安装 upil-api[memory]") from exc
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_timeout=settings.redis_timeout_seconds,
            socket_connect_timeout=settings.redis_timeout_seconds,
            decode_responses=True,
        )
        client.ping()
    except Exception as exc:
        raise MemoryRepositoryError("Redis 会话后端初始化失败，请检查地址和服务状态") from exc
    return RedisConversationStore(
        client,
        ttl_seconds=settings.conversation_ttl_seconds,
        lock_timeout_seconds=settings.redis_timeout_seconds,
    )
