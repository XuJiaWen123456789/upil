"""会话历史 HTTP 契约。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.api.contracts import UtcResponseModel
from backend.app.schemas import ActorRole


class ConversationCreateRequest(BaseModel):
    """创建会话不接收所有者信息，所有者只能来自认证上下文。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class ConversationUpdateRequest(BaseModel):
    """MVP 只允许修改显示标题。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("会话标题不能为空")
        return normalized


class ConversationListQuery(BaseModel):
    """会话列表分页参数和 Demo 身份兼容参数。"""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    actor_role: ActorRole = "parent"
    actor_user_id: str | None = Field(default=None, max_length=64)


class ConversationSummaryResponse(UtcResponseModel):
    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None


class ConversationListResponse(UtcResponseModel):
    items: list[ConversationSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ConversationMessageResponse(UtcResponseModel):
    message_id: int
    sequence_no: int
    role: str
    content: str
    created_at: datetime


class ConversationMessagesResponse(UtcResponseModel):
    conversation_id: str
    items: list[ConversationMessageResponse]
    has_more: bool
