"""销售顾问老师的招生线索查询、联系方式揭示和跟进路由。"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import settings
from backend.app.api.presenters.leads import lead_follow_up_response, lead_summary_response
from backend.app.db import get_session
from backend.app.schemas import (
    ActorRole,
    LeadContactResponse,
    LeadDetailResponse,
    LeadFollowUpRequest,
    LeadFollowUpResponse,
    LeadListQuery,
    LeadListResponse,
)
from backend.app.services.access_control import can_manage_leads
from backend.app.services.authentication import resolve_access_context
from backend.app.services.audit import write_audit_log
from backend.app.services.enrollment_leads import (
    LeadConflictError,
    LeadNotFoundError,
    add_lead_follow_up,
    follow_ups_for_lead,
    get_advisor_lead,
    list_advisor_leads,
    reveal_lead_contact,
)
from backend.app.services.lead_contacts import ContactProtectionError, ContactProtector


logger = logging.getLogger(__name__)
router = APIRouter()
LEAD_ID_PATTERN = re.compile(r"^lead_[a-f0-9]{32}$")


@router.get("/api/v1/leads", response_model=LeadListResponse)
async def list_enrollment_leads(
    http_request: Request,
    query: LeadListQuery = Depends(),
    session: Session = Depends(get_session),
) -> LeadListResponse:
    """返回销售顾问老师可领取或已经归属本人的线索。"""

    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=query.actor_role, requested_user_id=query.actor_user_id,
    )
    if not can_manage_leads(context):
        raise HTTPException(status_code=403, detail="当前账号无权访问销售线索")
    try:
        page = list_advisor_leads(
            session, context, destination=query.destination,
            limit=query.limit, offset=query.offset,
        )
        items = [lead_summary_response(session, context, lead) for lead in page.items]
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("lead_list_failed reason=database_unavailable")
        raise HTTPException(status_code=503, detail="销售线索服务暂时不可用") from exc
    return LeadListResponse(items=items, total=page.total, limit=query.limit, offset=query.offset)


@router.get("/api/v1/leads/{lead_id}", response_model=LeadDetailResponse)
async def get_enrollment_lead(
    lead_id: str,
    http_request: Request,
    actor_role: ActorRole = "teacher",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> LeadDetailResponse:
    """返回单份线索及只追加跟进历史，越权与不存在统一为 404。"""

    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=actor_role, requested_user_id=actor_user_id,
    )
    if not LEAD_ID_PATTERN.fullmatch(lead_id):
        raise HTTPException(status_code=404, detail="未找到可访问的销售线索")
    try:
        lead = get_advisor_lead(session, context, lead_id)
        summary = lead_summary_response(session, context, lead)
        follow_ups = [
            lead_follow_up_response(record)
            for record in follow_ups_for_lead(session, lead.id)
        ]
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到可访问的销售线索") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("lead_detail_failed reason=database_unavailable")
        raise HTTPException(status_code=503, detail="销售线索服务暂时不可用") from exc
    return LeadDetailResponse(**summary.model_dump(), follow_ups=follow_ups)


@router.get("/api/v1/leads/{lead_id}/contact", response_model=LeadContactResponse)
async def get_enrollment_lead_contact(
    lead_id: str,
    http_request: Request,
    response: Response,
    actor_role: ActorRole = "teacher",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> LeadContactResponse:
    """重新鉴权后短暂揭示联系方式，并禁止 HTTP 缓存。"""

    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=actor_role, requested_user_id=actor_user_id,
    )
    if not LEAD_ID_PATTERN.fullmatch(lead_id):
        raise HTTPException(status_code=404, detail="未找到可访问的销售线索")
    try:
        lead, contact_value = reveal_lead_contact(
            session, context, lead_id, ContactProtector.from_settings(settings)
        )
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到可访问的销售线索") from exc
    except LeadConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContactProtectionError as exc:
        session.rollback()
        try:
            write_audit_log(
                session, actor_user_id=context.user_id, action="lead.contact.reveal",
                resource_type="enrollment_lead", resource_id=lead_id, outcome="failure",
                metadata={"reason": "contact_integrity"},
            )
            session.commit()
        except SQLAlchemyError:
            session.rollback()
        logger.warning("lead_contact_reveal_rejected reason=contact_integrity")
        raise HTTPException(status_code=409, detail="联系方式暂时无法查看") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("lead_contact_reveal_failed reason=database_unavailable")
        raise HTTPException(status_code=503, detail="销售线索服务暂时不可用") from exc
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return LeadContactResponse(
        lead_id=lead.id, contact_type=lead.contact_type, contact_value=contact_value
    )


@router.post(
    "/api/v1/leads/{lead_id}/follow-ups",
    response_model=LeadFollowUpResponse,
    status_code=201,
)
async def create_enrollment_lead_follow_up(
    lead_id: str,
    payload: LeadFollowUpRequest,
    http_request: Request,
    actor_role: ActorRole = "teacher",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> LeadFollowUpResponse:
    """原子领取线索或追加有限跟进动作，不接受客户端直接写状态。"""

    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=actor_role, requested_user_id=actor_user_id,
    )
    if not LEAD_ID_PATTERN.fullmatch(lead_id):
        raise HTTPException(status_code=404, detail="未找到可访问的销售线索")
    try:
        _, record = add_lead_follow_up(
            session, context, lead_id, action=payload.action, result=payload.result,
            note=payload.note, next_follow_up_at=payload.next_follow_up_at,
        )
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到可访问的销售线索") from exc
    except LeadConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("lead_follow_up_failed reason=database_unavailable")
        raise HTTPException(status_code=503, detail="销售线索服务暂时不可用") from exc
    return lead_follow_up_response(record)
