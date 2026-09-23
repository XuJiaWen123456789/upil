"""家长与教师报告共用的任务执行和单 PDF 持久化服务。

显式按钮和聊天意图都调用本模块，因此不会形成两套报告业务。主系统负责
权限、周期和确定性统计，本地固定模板只产生受控 Markdown；Markdown 经业务
校验后立即转 PDF，整个过程中不落库。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import logging
from typing import Callable

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.class_learning_contracts import ClassLearningSummary
from backend.app.config import Settings
from backend.app.integrations.minio import MinioMediaStore
from backend.app.learning_contracts import LearningReportSnapshot
from backend.app.models import ReportTask
from backend.app.services.class_report_pdf import generate_class_report_pdf
from backend.app.services.markdown_pdf import ReportPdfDocument
from backend.app.services.report_pdf import generate_report_pdf
from backend.app.services.report_narrative import (
    build_class_report_markdown,
    build_parent_report_markdown,
)
from backend.app.services.reporting import (
    PARENT_LEARNING_REPORT,
    TEACHER_CLASS_LEARNING_REPORT,
    ReportTaskError,
    claim_pending_report_task,
    complete_report_task_with_pdf,
    create_report_task,
    fail_report_task,
    list_report_artifacts,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportExecutionResult:
    """供聊天和 HTTP 入口共同消费的最小执行结果。"""

    task: ReportTask
    status: str
    message: str
    provider: str
    markdown: str | None = None


def execute_parent_report(
    session: Session,
    *,
    requester_id: str,
    snapshot: LearningReportSnapshot,
    request_id: str,
    store: MinioMediaStore | None,
    settings: Settings | None,
) -> ReportExecutionResult:
    """执行家长报告，最终数据库只增加一个 PDF Artifact。"""

    scope = {
        "report_scope": snapshot.report_scope,
        "learner_ref": snapshot.learner_ref,
        "period_start": snapshot.period.period_start.isoformat(),
        "period_end": snapshot.period.period_end.isoformat(),
        "period_type": snapshot.period.period_type,
    }
    return _execute_report(
        session,
        requester_id=requester_id,
        task_type=PARENT_LEARNING_REPORT,
        subject_key=snapshot.learner_ref,
        scope=scope,
        metrics=[
            "attendance_rate", "attendance_breakdown", "lesson_balance",
            "published_progress",
        ],
        request_id=request_id,
        store=store,
        settings=settings,
        build_markdown=lambda: build_parent_report_markdown(snapshot),
        render=lambda markdown, task, config: generate_report_pdf(
            markdown, snapshot, config, generated_at=task.created_at,
            filename=f"learning-report-{task.id}.pdf",
        ),
    )


def execute_class_report(
    session: Session,
    *,
    requester_id: str,
    snapshot: ClassLearningSummary,
    period_type: str,
    request_id: str,
    store: MinioMediaStore | None,
    settings: Settings | None,
) -> ReportExecutionResult:
    """执行教师班级报告，复用同一本地模板、PDF、MinIO 和补偿链路。"""

    scope = {
        # class_id 用于每次查询和下载时重新校验授课关系，绝不会写入 PDF。
        "class_id": snapshot.class_id,
        "period_start": snapshot.period_start.isoformat(),
        "period_end": snapshot.period_end.isoformat(),
        "period_type": period_type,
    }
    return _execute_report(
        session,
        requester_id=requester_id,
        task_type=TEACHER_CLASS_LEARNING_REPORT,
        subject_key=snapshot.class_id,
        scope=scope,
        metrics=[
            "completion_rate", "attendance_rate", "absence_top5",
            "low_balance_learners", "unmarked_records",
            "missing_hour_accounts",
        ],
        request_id=request_id,
        store=store,
        settings=settings,
        build_markdown=lambda: build_class_report_markdown(snapshot),
        render=lambda markdown, task, config: generate_class_report_pdf(
            markdown, snapshot, config, generated_at=task.created_at,
            filename=f"class-learning-report-{task.id}.pdf",
        ),
    )


def _execute_report(
    session: Session,
    *,
    requester_id: str,
    task_type: str,
    subject_key: str,
    scope: dict,
    metrics: list[str],
    request_id: str,
    store: MinioMediaStore | None,
    settings: Settings | None,
    build_markdown: Callable[[], str],
    render: Callable[[str, ReportTask, Settings], ReportPdfDocument],
) -> ReportExecutionResult:
    """执行报告状态机；失败终态重试使用新任务，不复活旧记录。"""

    # request_id 只属于单次 HTTP/SSE 链路；报告幂等键由用户、对象、周期和
    # 模板版本组成，故同一范围从按钮或聊天重复发起都不会重复生成。
    _ = request_id
    template_version = settings.report_pdf_template_version if settings else "report-pdf-v2"
    task = _get_or_create_attempt(
        session, requester_id=requester_id, task_type=task_type, subject_key=subject_key,
        scope=scope, metrics=metrics, template_version=template_version,
    )
    if task.status == "completed":
        return ReportExecutionResult(
            task=task, status="completed", message="报告已生成，可直接下载。",
            provider="report_cache",
        )
    if task.status == "running":
        return ReportExecutionResult(
            task=task, status="working", message="报告正在生成，请稍后查看。",
            provider="workflow",
        )

    if store is None or settings is None:
        return _fail_execution(session, task, "报告生成或私有存储服务未启用")
    try:
        claimed = claim_pending_report_task(session, task.id)
        session.commit()
        # 条件 UPDATE 绕过了 ORM identity map；显式刷新后再向调用方返回状态。
        session.refresh(task)
    except (SQLAlchemyError, ReportTaskError):
        session.rollback()
        return ReportExecutionResult(
            task=task, status="failed", message="报告任务暂时无法执行。",
            provider="database",
        )
    if not claimed:
        if task.status == "completed" and _has_single_pdf(session, task.id):
            return ReportExecutionResult(
                task=task, status="completed", message="报告已生成，可直接下载。",
                provider="report_cache",
            )
        return ReportExecutionResult(
            task=task, status="working", message="报告正在生成，请稍后查看。",
            provider="workflow",
        )

    uploaded_object_key: str | None = None
    failure_stage = "build_markdown"
    try:
        markdown = build_markdown()
        failure_stage = "render_pdf"
        document = render(markdown, task, settings)
        failure_stage = "upload_pdf"
        uploaded_object_key = store.put_report_pdf(
            document.content, task_id=task.id, filename=document.filename,
            checksum=document.checksum,
        )
        failure_stage = "persist_artifact"
        complete_report_task_with_pdf(
            session, task.id, pdf_artifact_id=f"pdf_{sha256(task.id.encode('utf-8')).hexdigest()[:32]}",
            pdf_object_key=uploaded_object_key, pdf_checksum=document.checksum,
            pdf_filename=document.filename, pdf_size_bytes=document.size_bytes,
            pdf_page_count=document.page_count,
        )
        session.commit()
        return ReportExecutionResult(
            task=task, status="completed", message="报告已生成，可直接下载。",
            provider="local_report", markdown=markdown,
        )
    except Exception as exc:
        # 日志只记录任务类型、执行阶段和异常类型，不记录报告正文、学员标识、
        # 对象键或存储凭据。traceback 仅写入服务端日志，前端和数据库继续
        # 使用固定文案，兼顾故障定位与隐私保护。
        logger.exception(
            "report_execution_failed task_type=%s stage=%s exception_type=%s",
            task_type,
            failure_stage,
            type(exc).__name__,
        )
        session.rollback()
        if uploaded_object_key:
            try:
                store.delete_report_pdf(uploaded_object_key)
            except Exception:
                # 补偿失败由存储对账任务处理，绝不覆盖原始安全失败结果。
                pass
        return _fail_execution(session, task, "报告构建、校验、转换或持久化失败")


def _get_or_create_attempt(
    session: Session,
    *,
    requester_id: str,
    task_type: str,
    subject_key: str,
    scope: dict,
    metrics: list[str],
    template_version: str,
) -> ReportTask:
    """按稳定业务键命中任务；失败任务之后创建 ``_a2`` 等新尝试。"""

    material = "|".join(
        (
            requester_id, task_type, subject_key, str(scope.get("period_start")),
            str(scope.get("period_end")), template_version,
        )
    )
    base_id = f"report_{sha256(material.encode('utf-8')).hexdigest()[:32]}"
    for attempt in range(1, 100):
        task_id = base_id if attempt == 1 else f"{base_id}_a{attempt}"
        existing = session.get(ReportTask, task_id)
        if existing is not None:
            if existing.status in {"failed", "cancelled"}:
                continue
            # completed 但唯一 PDF 元数据已损坏时不能复活终态；新建下一次尝试。
            if existing.status == "completed" and not _has_single_pdf(session, task_id):
                continue
            if _matches_idempotent_request(
                existing,
                requester_id=requester_id,
                task_type=task_type,
                scope=scope,
                metrics=metrics,
                template_version=template_version,
            ):
                # “上个月”和同一自然月的显式日期只是不同表达方式。报告业务
                # 幂等性按请求人、对象、起止日期和模板判断，不应因为
                # period_type 这样的展示元数据不同而重复生成或产生主键冲突。
                return existing
            return create_report_task(
                session, task_id=task_id, requester_id=requester_id,
                task_type=task_type, scope=scope, metrics=metrics,
                template_version=template_version,
            )
        try:
            task = create_report_task(
                session, task_id=task_id, requester_id=requester_id,
                task_type=task_type, scope=scope, metrics=metrics,
                template_version=template_version,
            )
            session.commit()
            return task
        except IntegrityError:
            # 两个并发请求可能同时未读到任务；回滚后重读唯一键胜者，
            # 下一轮会复用 pending/running/completed 任务而不会重复创建。
            session.rollback()
            concurrent = session.get(ReportTask, task_id)
            if concurrent is None:
                raise
            if concurrent.status in {"failed", "cancelled"}:
                continue
            if concurrent.status == "completed" and not _has_single_pdf(session, task_id):
                continue
            if _matches_idempotent_request(
                concurrent,
                requester_id=requester_id,
                task_type=task_type,
                scope=scope,
                metrics=metrics,
                template_version=template_version,
            ):
                return concurrent
            return create_report_task(
                session, task_id=task_id, requester_id=requester_id,
                task_type=task_type, scope=scope, metrics=metrics,
                template_version=template_version,
            )
    raise ReportTaskError("同一报告范围的失败尝试次数超过上限")


def _matches_idempotent_request(
    task: ReportTask,
    *,
    requester_id: str,
    task_type: str,
    scope: dict,
    metrics: list[str],
    template_version: str,
) -> bool:
    """判断稳定业务范围是否一致，忽略周期的自然语言展示类型。"""

    stored_scope = dict(task.scope or {})
    requested_scope = dict(scope)
    stored_scope.pop("period_type", None)
    requested_scope.pop("period_type", None)
    return (
        task.requester_id == requester_id
        and task.task_type == task_type
        and stored_scope == requested_scope
        and task.metrics == metrics
        and task.template_version == template_version
    )


def _has_single_pdf(session: Session, task_id: str) -> bool:
    """完成态缓存只有在恰好存在一个 PDF 元数据时才可复用。"""

    artifacts = list_report_artifacts(session, task_id)
    return len(artifacts) == 1 and artifacts[0].artifact_type == "pdf"


def _fail_execution(
    session: Session,
    task: ReportTask,
    reason: str,
    *,
    provider: str = "local_report",
) -> ReportExecutionResult:
    """尽力保存脱敏失败终态，并返回固定用户文案。"""

    try:
        fail_report_task(session, task.id, reason)
        session.commit()
    except (SQLAlchemyError, ReportTaskError):
        session.rollback()
    return ReportExecutionResult(
        task=task, status="failed", message="报告生成失败，请稍后重新发起。",
        provider=provider,
    )
