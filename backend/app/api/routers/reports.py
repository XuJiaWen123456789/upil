"""家长和教师报告生成、查询与安全下载路由。"""

from datetime import datetime
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.compat import main_symbol
from backend.app.api.dependencies import get_report_store, settings
from backend.app.api.presenters.reports import report_detail_response, report_summary_response
from backend.app.db import get_session
from backend.app.integrations.minio import MinioMediaStore
from backend.app.models import ReportTask
from backend.app.schemas import (
    ActorRole,
    ClassReportTaskListQuery,
    ReportArtifactResponse,
    ReportGenerationRequest,
    ReportTaskDetailResponse,
    ReportTaskListQuery,
    ReportTaskListResponse,
    ReportTaskSummaryResponse,
)
from backend.app.services.access_control import can_access_class
from backend.app.services.authentication import resolve_access_context
from backend.app.services.learning_reports import (
    build_learning_report_snapshot,
    can_access_parent_report_scope,
    list_bound_learner_references,
    ReportPeriodResolutionError,
    resolve_report_period,
)
from backend.app.services.report_execution import execute_class_report, execute_parent_report
from backend.app.services.report_pdf import ReportPdfError, inspect_report_pdf
from backend.app.services.reporting import (
    PARENT_LEARNING_REPORT,
    TEACHER_CLASS_LEARNING_REPORT,
    ReportArtifactIntegrityError,
    ReportArtifactNotReadyError,
    ReportTaskNotFoundError,
    get_downloadable_report_artifact,
    get_owned_report_artifacts,
    list_class_report_tasks,
    list_requester_report_tasks,
)
from backend.app.services.audit import write_audit_log
from backend.app.tools.class_learning_tools import query_class_learning_summary


logger = logging.getLogger(__name__)
router = APIRouter()
REPORT_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,63}$")


def task_type_for_role(role: str) -> str:
    """把可信角色映射为固定报告类型，拒绝客户端自行选择资源类型。"""

    if role == "parent":
        return PARENT_LEARNING_REPORT
    if role == "teacher":
        return TEACHER_CLASS_LEARNING_REPORT
    raise HTTPException(status_code=403, detail="当前账号无权访问学情报告")


def authorize_report_scope(session: Session, context, task: ReportTask) -> None:
    """每次读取报告时重新校验绑定或授课关系，不能只信创建者字段。"""

    scope = task.scope if isinstance(task.scope, dict) else {}
    if task.task_type == PARENT_LEARNING_REPORT:
        allowed = can_access_parent_report_scope(session, context, scope.get("learner_ref"))
    elif task.task_type == TEACHER_CLASS_LEARNING_REPORT:
        class_id = scope.get("class_id")
        access_check = main_symbol("can_access_class", can_access_class)
        allowed = isinstance(class_id, str) and access_check(session, context, class_id)
    else:
        allowed = False
    if not allowed:
        raise ReportTaskNotFoundError("报告任务不存在")


@router.post(
    "/api/v1/learners/{learner_id}/reports",
    response_model=ReportTaskSummaryResponse,
)
async def generate_parent_learning_report(
    learner_id: str,
    payload: ReportGenerationRequest,
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
    store: MinioMediaStore | None = Depends(get_report_store),
) -> ReportTaskSummaryResponse:
    """由家长按钮生成报告，并复用聊天意图入口使用的执行服务。"""

    if not learner_id or len(learner_id) > 64:
        raise HTTPException(status_code=422, detail="学员编号格式无效")
    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=actor_role, requested_user_id=actor_user_id,
    )
    if context.role != "parent":
        raise HTTPException(status_code=403, detail="当前账号无权生成家长学情报告")
    if store is None:
        # 在读取学情和创建任务前检查完整 PDF 运行时，避免缺少原生渲染库的
        # 开发实例不断写入必然失败的任务。完整部署环境恢复后可直接重试。
        raise HTTPException(status_code=503, detail="PDF 报告服务暂时不可用")
    try:
        snapshot = build_learning_report_snapshot(session, context, learner_id, payload.period)
    except ReportPeriodResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="学情数据服务暂时不可用") from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail="未找到可访问的学情数据")
    execution = execute_parent_report(
        session, requester_id=context.user_id, snapshot=snapshot,
        request_id=http_request.state.request_id, store=store, settings=settings,
    )
    return report_summary_response(execution.task)


@router.post(
    "/api/v1/classes/{class_id}/reports",
    response_model=ReportTaskSummaryResponse,
)
async def generate_class_learning_report(
    class_id: str,
    payload: ReportGenerationRequest,
    http_request: Request,
    actor_role: ActorRole = "teacher",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
    store: MinioMediaStore | None = Depends(get_report_store),
) -> ReportTaskSummaryResponse:
    """按自然语言周期生成教师班级报告，统计值仍由后端确定性计算。"""

    if not class_id or len(class_id) > 64:
        raise HTTPException(status_code=422, detail="班级编号格式无效")
    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=actor_role, requested_user_id=actor_user_id,
    )
    if context.role != "teacher":
        raise HTTPException(status_code=403, detail="当前账号无权生成班级学情报告")
    if store is None:
        raise HTTPException(status_code=503, detail="PDF 报告服务暂时不可用")
    try:
        period = resolve_report_period(payload.period)
        summary = query_class_learning_summary(
            session, context, class_id, period.period_start, period.period_end,
            low_balance_threshold=5,
        )
    except ReportPeriodResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="班级学情服务暂时不可用") from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="未找到可访问的班级学情数据")
    execution = execute_class_report(
        session, requester_id=context.user_id, snapshot=summary, period_type=period.period_type,
        request_id=http_request.state.request_id, store=store, settings=settings,
    )
    return report_summary_response(execution.task)


@router.get("/api/v1/classes/{class_id}/reports", response_model=ReportTaskListResponse)
async def list_class_learning_reports(
    class_id: str,
    http_request: Request,
    query: ClassReportTaskListQuery = Depends(),
    session: Session = Depends(get_session),
) -> ReportTaskListResponse:
    """列出教师为当前仍在授课的班级创建的报告任务。"""

    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=query.actor_role, requested_user_id=query.actor_user_id,
    )
    if context.role != "teacher":
        raise HTTPException(status_code=403, detail="当前账号无权访问班级学情报告")
    if not class_id or len(class_id) > 64:
        raise HTTPException(status_code=404, detail="未找到可访问的班级学情报告")
    try:
        access_check = main_symbol("can_access_class", can_access_class)
        if not access_check(session, context, class_id):
            raise HTTPException(status_code=404, detail="未找到可访问的班级学情报告")
        tasks, total = list_class_report_tasks(
            session, context.user_id, class_id, limit=query.limit, offset=query.offset,
        )
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="报告服务暂时不可用") from exc
    return ReportTaskListResponse(
        items=[report_summary_response(task) for task in tasks],
        total=total, limit=query.limit, offset=query.offset,
    )


@router.get("/api/v1/reports", response_model=ReportTaskListResponse)
async def list_learning_reports(
    http_request: Request,
    query: ReportTaskListQuery = Depends(),
    session: Session = Depends(get_session),
) -> ReportTaskListResponse:
    """分页返回当前家长创建且仍有权访问的报告任务。"""

    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=query.actor_role, requested_user_id=query.actor_user_id,
    )
    if context.role != "parent":
        raise HTTPException(status_code=403, detail="当前账号无权访问家长学情报告")
    try:
        query_tasks = main_symbol(
            "list_requester_report_tasks", list_requester_report_tasks
        )
        tasks, total = query_tasks(
            session, context.user_id, list_bound_learner_references(session, context),
            limit=query.limit, offset=query.offset,
        )
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="报告服务暂时不可用") from exc
    return ReportTaskListResponse(
        items=[report_summary_response(task) for task in tasks],
        total=total, limit=query.limit, offset=query.offset,
    )


@router.get("/api/v1/reports/{task_id}", response_model=ReportTaskDetailResponse)
async def get_learning_report(
    task_id: str,
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> ReportTaskDetailResponse:
    """返回当前身份可访问的报告任务和最小产物元数据。"""

    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=actor_role, requested_user_id=actor_user_id,
    )
    if not REPORT_TASK_ID_PATTERN.fullmatch(task_id):
        raise HTTPException(status_code=404, detail="未找到可访问的报告任务")
    try:
        task_type = task_type_for_role(context.role)
        task, artifacts = get_owned_report_artifacts(
            session, task_id=task_id, requester_id=context.user_id, task_type=task_type,
        )
        authorize_report_scope(session, context, task)
        downloadable_artifact_id: str | None = None
        if task.status == "completed":
            try:
                _, downloadable = get_downloadable_report_artifact(
                    session, task_id=task_id, requester_id=context.user_id,
                    task_type=task_type,
                )
                downloadable_artifact_id = downloadable.id
            except (ReportArtifactNotReadyError, ReportArtifactIntegrityError):
                # 终态任务可以展示，但不为脏产物提供下载入口。
                downloadable_artifact_id = None
    except ReportTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到可访问的报告任务") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="报告服务暂时不可用") from exc
    return report_detail_response(task, artifacts, downloadable_artifact_id)


@router.get("/api/v1/reports/{task_id}/download")
async def download_learning_report(
    task_id: str,
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
    store: MinioMediaStore | None = Depends(get_report_store),
) -> Response:
    """鉴权后代理下载 PDF，并兼容历史家长 Markdown 产物。"""

    context = await resolve_access_context(
        http_request, session, settings,
        requested_role=actor_role, requested_user_id=actor_user_id,
    )
    if not REPORT_TASK_ID_PATTERN.fullmatch(task_id):
        raise HTTPException(status_code=404, detail="未找到可访问的报告任务")
    try:
        task_type = task_type_for_role(context.role)
        task, artifact = get_downloadable_report_artifact(
            session, task_id=task_id, requester_id=context.user_id, task_type=task_type,
        )
        authorize_report_scope(session, context, task)
        if artifact.artifact_type == "pdf":
            if store is None:
                raise HTTPException(status_code=503, detail="报告存储服务暂时不可用")
            try:
                content = store.get_report_pdf(artifact.object_key or "")
            except Exception as exc:
                logger.error("report_download_failed reason=storage_unavailable")
                raise HTTPException(status_code=503, detail="报告存储服务暂时不可用") from exc
            if content is None:
                raise HTTPException(status_code=503, detail="报告存储服务暂时不可用")
            scope = task.scope if isinstance(task.scope, dict) else {}
            private_scope = (
                scope.get("learner_ref")
                if task.task_type == PARENT_LEARNING_REPORT
                else scope.get("class_id")
            )
            inspector = main_symbol("inspect_report_pdf", inspect_report_pdf)
            inspector(
                content,
                max_bytes=settings.report_pdf_max_bytes,
                max_pages=settings.report_pdf_max_pages,
                template_version=task.template_version or settings.report_pdf_template_version,
                expected_checksum=artifact.checksum,
                expected_size=artifact.size_bytes,
                expected_pages=artifact.page_count,
                required_title=(
                    "家长学情报告" if task.task_type == PARENT_LEARNING_REPORT else "班级学情运营报表"
                ),
                forbidden_values=(private_scope,) if isinstance(private_scope, str) else (),
            )
            media_type = "application/pdf"
            filename = artifact.filename or f"learning-report-{task_id}.pdf"
        else:
            # 历史 Markdown 只为家长报告保留兼容读取，教师报告仍必须是 PDF。
            if task.task_type != PARENT_LEARNING_REPORT:
                raise ReportArtifactNotReadyError("教师报告缺少 PDF 产物")
            content = (artifact.content or "").encode("utf-8")
            media_type = "text/markdown; charset=utf-8"
            filename = f"learning-report-{task_id}.md"
        write_audit_log(
            session, actor_user_id=context.user_id, action="report.download",
            resource_type="report_task", resource_id=task.id, outcome="success",
            metadata={"task_type": task.task_type, "artifact_type": artifact.artifact_type},
        )
        session.commit()
    except ReportTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到可访问的报告任务") from exc
    except ReportArtifactNotReadyError as exc:
        raise HTTPException(status_code=409, detail="报告尚未生成完成") from exc
    except ReportArtifactIntegrityError as exc:
        logger.warning("report_download_rejected reason=artifact_integrity")
        raise HTTPException(status_code=409, detail="报告文件暂时不可下载") from exc
    except ReportPdfError as exc:
        logger.warning("report_download_rejected reason=pdf_integrity")
        raise HTTPException(status_code=409, detail="报告文件暂时不可下载") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="报告服务暂时不可用") from exc
    return Response(
        content=content, media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
