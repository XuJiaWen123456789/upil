"""会话状态、主体和存储协议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
import time
from typing import Callable, Protocol, TypeVar

from backend.app.conversation_understanding import EntityReference, IntentType


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ConversationSubject:
    """构成会话数据隔离边界的可信主体。"""

    tenant_id: str
    user_id: str
    role: str


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """经过脱敏和长度限制的单条短期对话。"""

    role: str
    content: str
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ConversationMemory:
    """单个会话允许保留的短期状态。

    这里不保存课时、出勤、报告状态、联系方式或知识库正文。业务动态事实
    每次都必须重新通过权限工具查询，不能由会话摘要替代。
    """

    active_entity: EntityReference | None = None
    child_age: int | None = None
    programming_foundation: str | None = None
    class_time_preference: str | None = None
    pending_intent: IntentType | None = None
    rolling_summary: str = ""
    recent_turns: list[ConversationTurn] = field(default_factory=list)
    version: int = 0
    updated_at: float = field(default_factory=time.monotonic)
    lock: RLock = field(default_factory=RLock, repr=False, compare=False)


class ConversationStore(Protocol):
    """聊天规划器依赖的最小会话存储协议。"""

    def process(
        self,
        conversation_id: str | None,
        processor: Callable[[ConversationMemory], T],
        *,
        subject: ConversationSubject | None = None,
    ) -> T:
        """在同一会话的原子边界内读取并更新状态。"""

    def read(
        self,
        conversation_id: str | None,
        *,
        subject: ConversationSubject | None = None,
    ) -> ConversationMemory:
        """读取会话快照，不增加版本号，也不改变过期时间。"""

    def restore(
        self,
        conversation_id: str,
        memory: ConversationMemory,
        *,
        subject: ConversationSubject | None = None,
        only_if_empty: bool = True,
    ) -> bool:
        """把持久快照恢复到短期存储。

        默认只允许写入空状态，避免 PostgreSQL 中较旧的快照覆盖另一请求
        已经写入 Redis 的新上下文。返回值表示本次是否真正执行了恢复。
        """

    def clear(
        self,
        conversation_id: str | None = None,
        *,
        subject: ConversationSubject | None = None,
    ) -> None:
        """清除全部状态或一个主体会话。"""
