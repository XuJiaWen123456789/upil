"""聊天会话目录与脱敏历史消息 API。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_conversation_store, settings
from backend.app.conversations.contracts import (
    ConversationCreateRequest,
    ConversationListQuery,
    ConversationListResponse,
    ConversationMessageResponse,
    ConversationMessagesResponse,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
)
from backend.app.conversations.repository import ConversationNotFoundError
from backend.app.conversations.service import ConversationHistoryService
from backend.app.db import get_session
from backend.app.memory.conversation import ConversationStore
from backend.app.schemas import ActorRole
from backend.app.services.authentication import resolve_access_context


logger = logging.getLogger(__name__)
router = APIRouter()


def _summary(conversation) -> ConversationSummaryResponse:
    """只投影页面需要的目录字段，不暴露所有者和上下文快照。"""

    return ConversationSummaryResponse(
        conversation_id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
    )


async def _access(
    request: Request, session: Session, actor_role: ActorRole, actor_user_id: str | None
):
    return await resolve_access_context(
        request, session, settings,
        requested_role=actor_role, requested_user_id=actor_user_id,
    )


@router.post(
    "/api/v1/conversations",
    response_model=ConversationSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreateRequest,
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> ConversationSummaryResponse:
    """为当前认证主体创建全新的空会话。"""

    context = await _access(
        http_request, session, actor_role, actor_user_id
    )
    try:
        conversation = ConversationHistoryService(session).create(
            context, title=payload.title
        )
    except SQLAlchemyError as exc:
        session.rollback()
        logger.warning("conversation_create_failed reason=database")
        raise HTTPException(status_code=503, detail="会话服务暂时不可用") from exc
    return _summary(conversation)


@router.get(
    "/api/v1/conversations", response_model=ConversationListResponse
)
async def list_conversations(
    http_request: Request,
    query: ConversationListQuery = Depends(),
    session: Session = Depends(get_session),
) -> ConversationListResponse:
    """按最近活动时间返回当前主体自己的会话。"""

    context = await _access(
        http_request, session, query.actor_role, query.actor_user_id
    )
    try:
        items, total = ConversationHistoryService(session).list(
            context, limit=query.limit, offset=query.offset
        )
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="会话服务暂时不可用") from exc
    return ConversationListResponse(
        items=[_summary(item) for item in items],
        total=total, limit=query.limit, offset=query.offset,
    )


@router.get(
    "/api/v1/conversations/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
async def list_conversation_messages(
    conversation_id: str,
    http_request: Request,
    limit: int = Query(default=100, ge=1, le=200),
    before_sequence: int | None = Query(default=None, ge=1),
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> ConversationMessagesResponse:
    """读取一页脱敏消息；不存在和越权统一返回 404。"""

    context = await _access(
        http_request, session, actor_role, actor_user_id
    )
    try:
        items, has_more = ConversationHistoryService(session).messages(
            conversation_id, context,
            limit=limit, before_sequence=before_sequence,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="会话服务暂时不可用") from exc
    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        items=[
            ConversationMessageResponse(
                message_id=item.id, sequence_no=item.sequence_no, role=item.role,
                content=item.content, created_at=item.created_at,
            )
            for item in items
        ],
        has_more=has_more,
    )


@router.patch(
    "/api/v1/conversations/{conversation_id}",
    response_model=ConversationSummaryResponse,
)
async def rename_conversation(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> ConversationSummaryResponse:
    """重命名当前主体自己的会话。"""

    context = await _access(
        http_request, session, actor_role, actor_user_id
    )
    try:
        conversation = ConversationHistoryService(session).rename(
            conversation_id, context, payload.title
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="会话服务暂时不可用") from exc
    return _summary(conversation)


@router.delete(
    "/api/v1/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: str,
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> Response:
    """删除会话目录和消息；线索、报告、长期偏好保持独立。"""

    context = await _access(
        http_request, session, actor_role, actor_user_id
    )
    try:
        ConversationHistoryService(session).delete(
            conversation_id, context, store
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="会话服务暂时不可用") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
