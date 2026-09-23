"""HTTP 请求、智能体结果和响应模型。

Pydantic 模型负责校验接口输入格式；身份认证由 HTTP 边界的认证服务完成，
业务授权由 AccessContext 和资源权限规则完成。请求中的身份字段仅供 Demo 模式使用。
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.contracts import UtcResponseModel
from backend.app.class_learning_contracts import ClassLearningSummary
from backend.app.learning_contracts import LearningSummary


# uPil 的业务角色刻意收敛为家长和教师。运维人员通过部署平台、数据库迁移
# 和受控脚本管理系统，不在客服业务 API 中拥有一个可被客户端选择的管理员角色。
ActorRole = Literal["parent", "teacher"]
AgentProvider = Literal[
    "ragflow",
    "langchain",
    "offline",
    "database",
    "local_report",
    "report_cache",
    "handoff",
    "workflow",
]
class SourceReference(BaseModel):
    """知识库来源的脱敏引用，只保留前端展示和审计所需的字段。"""

    # source_id 由 RAGFlow 返回时保留，便于后续定位原始文档或切片。
    source_id: str | None = None
    # 文档名称和片段摘要用于前端展示，不能把整份内部文档返回给用户。
    title: str | None = None
    snippet: str | None = None
    # RAGFlow 来源可以携带外部素材资产 ID；uPil 不负责该素材的上传与审核。
    media_asset_id: str | None = None
    # 检索分数不是所有版本的 RAGFlow 都会返回，因此允许为空。
    score: float | None = Field(default=None, ge=0, le=1)


class AgentResponse(BaseModel):
    """业务智能体统一输出结构，供同步工作流和 SSE 完成事件共同使用。"""

    answer: str
    provider: AgentProvider
    sources: list[SourceReference] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """SSE 对话接口的请求体。"""

    # 消息长度限制用于防止异常大的输入占用模型和工作流资源。
    message: str = Field(min_length=1, max_length=2000)
    # 同一 conversation_id 才会共享最近确认的课程实体；不提供时保持单轮无状态。
    # 仅允许 URL/日志友好的字符，避免把任意长文本写入内存状态键。
    conversation_id: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )

    # 两个身份字段只在 AUTH_MODE=demo 时生效；可信 Header 和 OIDC 模式均忽略它们。
    actor_role: ActorRole = "parent"
    actor_user_id: str | None = Field(default=None, max_length=64)
    learner_id: str | None = Field(default=None, max_length=64)


class ClassLearningSummaryQuery(BaseModel):
    """班级学情统计接口的查询参数。

    该模型把时间范围、低课时阈值和 Demo 模拟身份集中在一个输入契约中，
    避免接口函数里散落未校验的字符串和数字。可信 Header 模式仍可接收这些
    兼容字段，但认证服务会忽略它们并生成数据库校验后的 AccessContext。
    """

    model_config = ConfigDict(extra="forbid")

    period_start: date
    period_end: date
    low_balance_threshold: int = Field(default=5, ge=0, le=10000)
    # 本地身份模式默认使用授课教师；可信模式的身份只能来自认证代理和身份库。
    actor_role: ActorRole = "teacher"
    actor_user_id: str | None = Field(default=None, max_length=64)


class ReportTaskListQuery(BaseModel):
    """家长报告列表的分页与本地身份参数。

    正式认证模式会忽略客户端传入的身份字段；它们仅用于本地 Demo 联调。
    分页参数设置较小上限，避免一次读取大量任务造成数据库和响应压力。
    """

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    actor_role: ActorRole = "parent"
    actor_user_id: str | None = Field(default=None, max_length=64)


class ReportGenerationRequest(BaseModel):
    """显式报告入口允许提交的受限自然语言周期。

    ``period`` 只描述时间，例如“上个月”“最近30天”或一个明确日期范围。
    登录身份、学员和班级仍分别来自认证上下文与受控路径参数；请求体不能
    覆盖这些资源范围，也不能直接提交起止日期或统计阈值。
    """

    model_config = ConfigDict(extra="forbid")

    period: str = Field(
        min_length=1,
        max_length=100,
        description="报告周期自然语言表达，例如：上个月、2026年8月",
    )


class ClassReportTaskListQuery(BaseModel):
    """教师指定班级报告列表的分页和本地身份参数。"""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    actor_role: ActorRole = "teacher"
    actor_user_id: str | None = Field(default=None, max_length=64)


class ReportArtifactResponse(UtcResponseModel):
    """报告详情中的产物元数据，不包含正文、校验和或内部对象地址。"""

    artifact_id: str
    artifact_type: str
    created_at: datetime
    download_available: bool


class ReportTaskSummaryResponse(UtcResponseModel):
    """家长可见的报告任务摘要。

    requester_id、scope、metrics、内部异常和私有存储地址均不属于公开契约。
    """

    task_id: str
    task_type: Literal[
        "parent_learning_report",
        "teacher_class_learning_report",
    ]
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    period_start: date | None = None
    period_end: date | None = None
    period_type: Literal[
        "current_month",
        "previous_month",
        "recent_30_days",
        "custom",
    ] | None = None
    template_version: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    download_available: bool
    message: str


class ReportTaskDetailResponse(ReportTaskSummaryResponse):
    """单个报告任务详情，只追加安全的产物描述。"""

    artifacts: list[ReportArtifactResponse] = Field(default_factory=list)


class ReportTaskListResponse(UtcResponseModel):
    """分页报告列表响应。"""

    items: list[ReportTaskSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class DemoClassAvailabilityRequest(BaseModel):
    """开发环境班级名额查询接口的固定请求契约。

    请求体不接收 tool_name、route、身份核验状态或任意执行参数，防止调用方
    绕过服务端路由白名单，把固定查询接口变成通用工具执行入口。
    """

    model_config = ConfigDict(extra="forbid")

    course_name: str = Field(min_length=1, max_length=100)
    campus_name: str = Field(min_length=1, max_length=100)


class HealthResponse(BaseModel):
    """健康检查接口的稳定响应结构。"""

    status: Literal["ok"]
    service: str
    environment: str


class DependencyHealthResponse(BaseModel):
    """依赖健康检查响应；只返回状态，不返回地址、凭据和第三方正文。"""

    # degraded 表示主 API 仍可响应，但至少一个可选依赖不可用。
    status: Literal["ok", "degraded"]
    service: str
    environment: str
    # 使用简单状态字符串便于监控系统采集，也避免暴露内部异常详情。
    dependencies: dict[str, str]


class FrontendBootstrapResponse(BaseModel):
    """前端启动所需的公开配置。

    该模型故意只包含界面名称、环境标识和功能开关。数据库 DSN、OIDC
    配置、MinIO 地址、对象桶和任何密钥都不能通过这个接口下发给浏览器。
    """

    app_name: str
    environment: str
    demo_mode: bool
    features: dict[str, bool]


class SessionResponse(BaseModel):
    """当前请求经过认证后的最小前端会话描述。

    ``permissions`` 是后端从本地授权表计算出的受支持权限，
    ``capabilities`` 是前端路由和按钮使用的稳定能力名。两者都不是
    客户端提交的声明，前端不能通过修改它们获得服务端权限。
    """

    role: ActorRole
    permissions: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    # 只有本地身份模式返回用户编号，方便开发联调切换身份；
    # trusted_headers/OIDC 模式不向浏览器暴露内部 user_id。
    demo_user_id: str | None = None


class LeadChatCardResponse(BaseModel):
    """聊天 SSE 中的家长线索卡，不暴露意向等级等内部销售字段。"""

    lead_id: str
    interest_type: Literal["trial", "enrollment", "unknown"]
    status: Literal[
        "awaiting_contact_consent",
        "ready_for_followup",
        "contacted",
        "trial_scheduled",
        "enrolled",
        "withdrawn",
    ]
    course_name: str
    contact_masked: str | None = None
    prompt: str | None = None


class LeadListQuery(BaseModel):
    """销售顾问老师线索列表的受限分页条件。"""

    model_config = ConfigDict(extra="forbid")

    destination: Literal["lead_pool", "advisor_queue"] | None = None
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    actor_role: ActorRole = "teacher"
    actor_user_id: str | None = Field(default=None, max_length=64)


class LeadSummaryResponse(UtcResponseModel):
    """顾问列表所需最小字段；联系方式始终只返回脱敏值。"""

    lead_id: str
    learner_name: str | None = None
    course_name: str
    interest_type: Literal["trial", "enrollment", "unknown"]
    strength: Literal["low", "medium", "high"]
    destination: Literal["lead_pool", "advisor_queue"]
    status: Literal[
        "open",
        "awaiting_contact_consent",
        "ready_for_followup",
        "contacted",
        "trial_scheduled",
        "enrolled",
        "closed_won",
        "closed_lost",
    ]
    contact_available: bool
    contact_masked: str | None = None
    assigned_to_me: bool
    created_at: datetime
    updated_at: datetime


class LeadListResponse(UtcResponseModel):
    items: list[LeadSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class LeadFollowUpResponse(UtcResponseModel):
    follow_up_id: int
    action: str
    result: str
    note: str | None = None
    next_follow_up_at: datetime | None = None
    created_at: datetime


class LeadDetailResponse(LeadSummaryResponse):
    """顾问详情仍不包含家长内部 ID、证据原文或联系方式明文。"""

    follow_ups: list[LeadFollowUpResponse] = Field(default_factory=list)


class LeadContactResponse(BaseModel):
    """专用联系方式揭示响应，HTTP 层必须附加 no-store。"""

    lead_id: str
    contact_type: Literal["phone", "email"]
    contact_value: str


class LeadFollowUpRequest(BaseModel):
    """销售顾问老师的有限跟进动作，不接受任意状态字符串。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["claim", "contact", "schedule_trial", "confirm_enrollment", "close"]
    result: Literal[
        "claimed",
        "reached",
        "unreachable",
        "declined",
        "scheduled",
        "cancelled",
        "enrolled",
        "won",
        "lost",
    ]
    note: str | None = Field(default=None, max_length=500)
    next_follow_up_at: datetime | None = None


class LearningSnapshotResponse(LearningSummary):
    """结构化学情接口的响应模型，复用学情分析契约。"""

    pass


class ClassLearningSummaryResponse(ClassLearningSummary):
    """班级统计接口响应，复用确定性统计契约。"""

    pass
