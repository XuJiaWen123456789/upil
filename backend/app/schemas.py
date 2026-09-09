"""HTTP 请求、智能体结果和响应模型。

Pydantic 模型负责校验接口输入格式；真正的身份认证和授权仍应由服务端
登录态、JWT 或网关注入，不能把客户端传入的角色字段当作生产鉴权依据。
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.class_learning_contracts import ClassLearningSummary
from backend.app.learning_contracts import LearningSummary


ActorRole = Literal["parent", "teacher", "admin"]
AgentProvider = Literal[
    "ragflow", "langchain", "offline", "database", "a2a_mock", "a2a_http", "handoff", "workflow"
]
MediaVisibility = Literal["public_faq", "internal_staff", "private"]


class SourceReference(BaseModel):
    """知识库来源的脱敏引用，只保留前端展示和审计所需的字段。"""

    # source_id 由 RAGFlow 返回时保留，便于后续定位原始文档或切片。
    source_id: str | None = None
    # 文档名称和片段摘要用于前端展示，不能把整份内部文档返回给用户。
    title: str | None = None
    snippet: str | None = None
    # 图片来源只携带资产 ID，不把 MinIO 二进制内容放进 SSE。
    media_asset_id: str | None = None
    # 检索分数不是所有版本的 RAGFlow 都会返回，因此允许为空。
    score: float | None = Field(default=None, ge=0, le=1)


class MediaAssetSummary(BaseModel):
    """图片资产的可审计元数据，不包含图片二进制内容。"""

    asset_id: str
    # 对象键供服务端生成预签名 URL；前端不应自行拼接公开地址。
    object_key: str
    filename: str
    media_type: str
    title: str
    alt_text: str
    source_document: str
    visibility: MediaVisibility = "public_faq"
    sha256: str
    size_bytes: int = Field(ge=0)
    review_status: Literal["pending", "approved", "rejected"] = "pending"


class MediaAssetResponse(BaseModel):
    """媒体接口对外返回的安全元数据，不暴露 MinIO 内部对象键。"""

    asset_id: str
    filename: str
    media_type: str
    title: str
    alt_text: str
    source_document: str
    visibility: MediaVisibility = "public_faq"
    sha256: str
    size_bytes: int = Field(ge=0)
    review_status: Literal["pending", "approved", "rejected"] = "pending"


class MediaAssetUrlResponse(MediaAssetResponse):
    """媒体预签名地址响应；地址具有短时效，不能作为永久资源 URL。"""

    url: str
    expires_seconds: int = Field(gt=0)


class MediaReviewRequest(BaseModel):
    """管理员审核媒体资产时使用的状态变更请求。"""

    review_status: Literal["approved", "rejected"]


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

    # 当前字段仅用于演示和测试；正式环境应从认证上下文获得角色。
    actor_role: ActorRole = "parent"
    # 当前字段用于本地验证数据权限；正式版本应由 JWT/登录态注入，不能信任客户端。
    actor_user_id: str | None = Field(default=None, max_length=64)
    learner_id: str | None = Field(default=None, max_length=64)


class ClassLearningSummaryQuery(BaseModel):
    """班级学情统计接口的查询参数。

    该模型把时间范围、低课时阈值和开发期模拟身份集中在一个输入契约中，
    避免接口函数里散落未校验的字符串和数字。生产环境应移除身份字段，
    改为从登录态、JWT 或网关注入已认证的 AccessContext。
    """

    model_config = ConfigDict(extra="forbid")

    period_start: date
    period_end: date
    low_balance_threshold: int = Field(default=5, ge=0, le=10000)
    # 班级统计属于教师/管理员内部能力，演示接口默认使用演示教师身份。
    actor_role: ActorRole = "teacher"
    actor_user_id: str | None = Field(default=None, max_length=64)


class DemoClassAvailabilityRequest(BaseModel):
    """开发环境班级名额演示接口的固定请求契约。

    请求体不接收 tool_name、route、身份核验状态或任意执行参数，防止调用方
    绕过服务端路由白名单，把固定演示接口变成通用工具执行入口。
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


class LearningSnapshotResponse(LearningSummary):
    """结构化学情接口的响应模型，复用学情分析契约。"""

    pass


class ClassLearningSummaryResponse(ClassLearningSummary):
    """班级统计接口响应，复用确定性统计契约。"""

    pass
