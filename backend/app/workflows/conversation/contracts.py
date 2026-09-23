"""LangGraph 对话状态与路由类型契约。

状态 Schema 独立于图构建器和节点实现，避免节点通过隐式字段耦合。这里
只声明工作流允许传播的最小上下文，不保存完整聊天记录或认证凭据。
"""

from datetime import date
from typing import Literal, TypedDict

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.context import ContextEnvelope
from backend.app.conversation_understanding import EntityReference, IntentResult
from backend.app.dialogue import TurnDecision
from backend.app.integrations.minio import MinioMediaStore
from backend.app.schemas import SourceReference
from backend.app.services.access_control import AccessContext


RouteName = Literal[
    "faq",
    "service_rules",
    "learning_summary",
    "class_learning_summary",
    "learning_report",
    "report_history",
    "human_handoff",
    "clarification",
    "small_talk",
    "out_of_scope",
]


class ConversationState(TypedDict, total=False):
    """节点之间传播的最小、显式且可校验的对话状态。"""

    message: str
    access_context: AccessContext
    learner_id: str | None
    session: Session
    conversation_id: str | None
    intent_result: IntentResult
    decision: TurnDecision
    active_entity: EntityReference | None
    rewritten_query: str
    recognition_source: str
    request_id: str
    report_pdf_enabled: bool
    report_pdf_settings: Settings | None
    report_store: MinioMediaStore | None
    report_task_id: str
    report_status: str
    navigation_path: str
    navigation_label: str
    # 家长学情请求在进入图之前完成绑定解析。失败时只传递安全提示，节点
    # 不再自行猜测孩子，也不把其他孩子的内部编号传播到回答层。
    learner_resolution_answer: str
    class_id: str | None
    class_name: str | None
    period_start: date | None
    period_end: date | None
    low_balance_threshold: int
    route: RouteName
    answer: str
    provider: str
    sources: list[SourceReference]
    # 一次请求内的只读共享上下文，不能替代数据库事实，也不能携带联系方式。
    context_envelope: ContextEnvelope
