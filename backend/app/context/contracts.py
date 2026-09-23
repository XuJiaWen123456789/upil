"""请求级共享上下文的稳定数据契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.app.conversation_understanding import EntityReference
from backend.app.dialogue import TurnDecision
from backend.app.services.access_control import AccessContext


class ContextSource:
    """上下文字段的来源标签，供审计和投影策略使用。"""

    USER = "user"
    DETERMINISTIC = "deterministic"
    SESSION = "session"
    DATABASE = "database"
    RAG = "rag"
    MODEL = "model"


class ContextTrust:
    """上下文字段的可信等级。数值越大表示越适合直接驱动业务。"""

    UNTRUSTED = 0
    INFERRED = 1
    CONFIRMED = 2
    AUTHORITATIVE = 3


@dataclass(frozen=True, slots=True)
class ContextField:
    """带有来源、可信度和持久化边界的单个上下文值。"""

    value: Any
    source: str
    trust: int
    scope: str = "request"
    persistable: bool = False
    sensitive: bool = False


@dataclass(frozen=True, slots=True)
class ContextEnvelope:
    """一次请求内所有 Agent 可读取的最小共享上下文。

    Envelope 是不可变对象。Agent 可以根据自己的职责读取投影，但不能把
    自己的推断直接写回共享对象；结果必须经过统一 reducer 才能进入工作流。
    联系方式原文、Token、数据库密码和未授权的业务明细不允许进入此契约。
    """

    access_context: AccessContext
    request_id: str | None
    conversation_id: str | None
    message: str
    rewritten_query: str
    route: str
    # 已由状态机和 Supervisor 仲裁完成的不可变决策。多个 Agent 读取同一
    # 对象的职责投影，避免主回答、学情工具和报课意向旁路各自重新猜意图。
    decision: TurnDecision | None = None
    active_entity: EntityReference | None = None
    child_age: ContextField | None = None
    programming_foundation: ContextField | None = None
    class_time_preference: ContextField | None = None
    pending_intent: ContextField | None = None
    rolling_summary: str = ""
    recent_turns: tuple[Mapping[str, str], ...] = ()
    # 这里只放已经过结构化记忆权限过滤的偏好投影，不放数据库主键、版本
    # 管理字段或任何动态学情事实。具体 Agent 是否需要读取由 projector 决定。
    structured_memories: tuple[Mapping[str, str], ...] = ()
    business_facts: Mapping[str, ContextField] = field(default_factory=dict)
    rag_context: tuple[Mapping[str, str], ...] = ()
    trace: Mapping[str, str] = field(default_factory=dict)

    @property
    def tenant_id(self) -> str:
        """返回租户边界，未接入多租户时使用默认租户。"""

        return self.access_context.tenant_id

    @property
    def subject_key(self) -> str:
        """返回可用于会话隔离的主体键，不包含联系方式。"""

        return ":".join((self.tenant_id, self.access_context.user_id, self.access_context.role))

    def with_business_fact(self, name: str, field_value: ContextField) -> "ContextEnvelope":
        """返回增加业务事实引用的新 Envelope，不修改当前请求对象。"""

        facts = dict(self.business_facts)
        facts[name] = field_value
        return self.__class__(
            access_context=self.access_context,
            request_id=self.request_id,
            conversation_id=self.conversation_id,
            message=self.message,
            rewritten_query=self.rewritten_query,
            route=self.route,
            decision=self.decision,
            active_entity=self.active_entity,
            child_age=self.child_age,
            programming_foundation=self.programming_foundation,
            class_time_preference=self.class_time_preference,
            pending_intent=self.pending_intent,
            rolling_summary=self.rolling_summary,
            recent_turns=self.recent_turns,
            structured_memories=self.structured_memories,
            business_facts=facts,
            rag_context=self.rag_context,
            trace=self.trace,
        )
