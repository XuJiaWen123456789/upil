"""结构化学情快照和班级统计路由。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.api.dependencies import settings
from backend.app.db import get_session
from backend.app.schemas import (
    ActorRole,
    ClassLearningSummaryQuery,
    ClassLearningSummaryResponse,
    LearningSnapshotResponse,
)
from backend.app.services.access_control import AccessContext
from backend.app.services.authentication import resolve_access_context
from backend.app.services.learning import get_learning_snapshot
from backend.app.tools.class_learning_tools import query_class_learning_summary


router = APIRouter()


@router.get(
    "/api/v1/learners/{learner_id}/learning-snapshot",
    response_model=LearningSnapshotResponse,
)
async def learning_snapshot(
    learner_id: str,
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> LearningSnapshotResponse:
    """返回经过资源授权的结构化学情快照。"""

    context = await resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=actor_role,
        requested_user_id=actor_user_id,
    )
    snapshot = get_learning_snapshot(session, context, learner_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="未找到可访问的学情数据")
    return LearningSnapshotResponse.model_validate(snapshot)


@router.get(
    "/api/v1/classes/{class_id}/learning-summary",
    response_model=ClassLearningSummaryResponse,
)
async def class_learning_summary(
    class_id: str,
    http_request: Request,
    query: ClassLearningSummaryQuery = Depends(),
    session: Session = Depends(get_session),
) -> ClassLearningSummaryResponse:
    """返回由后端确定性计算的授权班级学情统计。"""

    if not class_id or len(class_id) > 64:
        raise HTTPException(status_code=422, detail="班级编号格式无效")
    context = await resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=query.actor_role,
        requested_user_id=query.actor_user_id,
    )
    try:
        summary = query_class_learning_summary(
            session,
            context,
            class_id,
            query.period_start,
            query.period_end,
            low_balance_threshold=query.low_balance_threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="未找到可访问的班级学情数据")
    return ClassLearningSummaryResponse.model_validate(summary.model_dump())
