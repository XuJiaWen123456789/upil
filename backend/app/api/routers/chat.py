"""对话 SSE HTTP 路由。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.api.compat import main_symbol
from backend.app.api.dependencies import (
    get_conversation_store,
    get_intent_model,
    get_lead_intent_model,
    get_report_store,
    settings,
)
from backend.app.db import get_session
from backend.app.integrations.minio import MinioMediaStore
from backend.app.schemas import ActorRole, ChatRequest
from backend.app.conversations.repository import ConversationNotFoundError
from backend.app.conversations.service import ConversationHistoryService
from backend.app.services.authentication import resolve_access_context
from backend.app.memory.conversation import ConversationStore
from backend.app.services.conversation_state import plan_conversation
from backend.app.services.faq import stream_faq_answer
from backend.app.services.service_rules import stream_service_rules_answer
from backend.app.workflows.chat_stream import stream_answer as run_stream_answer


router = APIRouter()


@router.post("/api/v1/chat/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    actor_role: ActorRole | None = None,
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
    store: ConversationStore = Depends(get_conversation_store),
    intent_model=Depends(get_intent_model),
    lead_intent_model=Depends(get_lead_intent_model),
    report_store: MinioMediaStore | None = Depends(get_report_store),
) -> StreamingResponse:
    """认证请求后返回禁缓存、禁代理缓冲的 SSE 响应。"""

    # 页面上的 Demo 身份切换器通过查询参数统一附加身份；早期客户端和部分
    # API 测试则仍可能把身份放在 JSON 请求体中。查询参数优先、请求体回退，
    # 可以让聊天接口与会话目录、报告和学情接口保持一致，同时保留向后兼容。
    # trusted_headers/OIDC 模式会在认证服务中完全忽略这两类客户端字段。
    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=actor_role or request.actor_role,
        requested_user_id=(
            actor_user_id if actor_user_id is not None else request.actor_user_id
        ),
    )
    # 所有权校验和 Redis 恢复必须发生在 StreamingResponse 建立之前。否则
    # SSE 响应头已经发送后，即使发现越权也无法再返回正确的 HTTP 404。
    try:
        ConversationHistoryService(session).prepare_for_chat(
            request.conversation_id, context, store,
            recent_turn_limit=settings.conversation_recent_turns,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="会话服务暂时不可用") from exc
    except Exception as exc:
        # 恢复后端不可用时不能悄悄用空上下文继续回答，否则会造成明显失忆。
        session.rollback()
        raise HTTPException(status_code=503, detail="会话上下文暂时不可用") from exc
    stream = run_stream_answer(
        request, context, session, store, intent_model, lead_intent_model,
        request_id=http_request.state.request_id,
        report_store=report_store,
        # 兼容旧测试覆盖点；新代码应直接测试 workflows.chat_stream。
        planner=main_symbol("plan_conversation", plan_conversation),
        faq_stream=main_symbol("stream_faq_answer", stream_faq_answer),
        service_rules_stream=main_symbol(
            "stream_service_rules_answer", stream_service_rules_answer
        ),
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
