"""报告任务和产物的查询、所有权限定与下载选择。

资源关系仍由 HTTP 层在每次访问时重新确认；这里负责把请求人、任务类型
和业务范围下推到 SQL，避免先读取越权数据再在 Python 中过滤。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import ReportArtifact, ReportTask

from .constants import (
    PARENT_LEARNING_REPORT,
    REPORT_TASK_TYPES,
    TEACHER_CLASS_LEARNING_REPORT,
)
from .exceptions import (
    ReportArtifactIntegrityError,
    ReportArtifactNotReadyError,
    ReportTaskNotFoundError,
)
from .integrity import validate_downloadable_markdown, validate_downloadable_pdf


def get_report_task(session: Session, task_id: str) -> ReportTask:
    """按任务 ID 获取记录，不存在时统一抛出业务异常。"""

    task = session.get(ReportTask, task_id)
    if task is None:
        raise ReportTaskNotFoundError("报告任务不存在")
    return task


def list_report_artifacts(session: Session, task_id: str) -> list[ReportArtifact]:
    """返回任务产物；先验证任务存在以免通过查询差异泄露信息。"""

    get_report_task(session, task_id)
    return list(
        session.query(ReportArtifact)
        .filter(ReportArtifact.report_task_id == task_id)
        .order_by(ReportArtifact.created_at.asc(), ReportArtifact.id.asc())
        .all()
    )


def list_requester_report_tasks(
    session: Session,
    requester_id: str,
    learner_refs: frozenset[str],
    *,
    limit: int,
    offset: int,
) -> tuple[list[ReportTask], int]:
    """分页返回家长本人且属于当前绑定学员的报告任务。"""

    if not learner_refs:
        return [], 0
    conditions = (
        ReportTask.requester_id == requester_id,
        ReportTask.task_type == PARENT_LEARNING_REPORT,
        ReportTask.scope["learner_ref"].as_string().in_(sorted(learner_refs)),
    )
    total = session.scalar(
        select(func.count()).select_from(ReportTask).where(*conditions)
    )
    tasks = session.scalars(
        select(ReportTask)
        .where(*conditions)
        .order_by(ReportTask.created_at.desc(), ReportTask.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(tasks), int(total or 0)


def list_class_report_tasks(
    session: Session,
    requester_id: str,
    class_id: str,
    *,
    limit: int,
    offset: int,
) -> tuple[list[ReportTask], int]:
    """分页返回教师本人为指定授课班级创建的报告任务。"""

    conditions = (
        ReportTask.requester_id == requester_id,
        ReportTask.task_type == TEACHER_CLASS_LEARNING_REPORT,
        ReportTask.scope["class_id"].as_string() == class_id,
    )
    total = session.scalar(
        select(func.count()).select_from(ReportTask).where(*conditions)
    )
    tasks = session.scalars(
        select(ReportTask)
        .where(*conditions)
        .order_by(ReportTask.created_at.desc(), ReportTask.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(tasks), int(total or 0)


def get_requester_report_task(
    session: Session, *, task_id: str, requester_id: str
) -> ReportTask:
    """联合任务 ID 和请求人查询家长报告，越权与不存在统一为 404。"""

    task = session.scalar(
        select(ReportTask).where(
            ReportTask.id == task_id,
            ReportTask.requester_id == requester_id,
            ReportTask.task_type == PARENT_LEARNING_REPORT,
        )
    )
    if task is None:
        raise ReportTaskNotFoundError("报告任务不存在")
    return task


def get_owned_report_task(
    session: Session,
    *,
    task_id: str,
    requester_id: str,
    task_type: str,
) -> ReportTask:
    """按请求人和受支持任务类型读取一条报告。"""

    if task_type not in REPORT_TASK_TYPES:
        raise ReportTaskNotFoundError("报告任务不存在")
    task = session.scalar(
        select(ReportTask).where(
            ReportTask.id == task_id,
            ReportTask.requester_id == requester_id,
            ReportTask.task_type == task_type,
        )
    )
    if task is None:
        raise ReportTaskNotFoundError("报告任务不存在")
    return task


def get_owned_report_artifacts(
    session: Session,
    *,
    task_id: str,
    requester_id: str,
    task_type: str,
) -> tuple[ReportTask, list[ReportArtifact]]:
    """读取限定类型的本人任务及其最小产物元数据。"""

    task = get_owned_report_task(
        session, task_id=task_id, requester_id=requester_id, task_type=task_type
    )
    artifacts = session.scalars(
        select(ReportArtifact)
        .where(ReportArtifact.report_task_id == task.id)
        .order_by(ReportArtifact.created_at.asc(), ReportArtifact.id.asc())
    ).all()
    return task, list(artifacts)


def get_requester_report_artifacts(
    session: Session, *, task_id: str, requester_id: str
) -> tuple[ReportTask, list[ReportArtifact]]:
    """读取家长本人任务与产物，供历史详情接口保持兼容。"""

    task = get_requester_report_task(
        session, task_id=task_id, requester_id=requester_id
    )
    artifacts = session.scalars(
        select(ReportArtifact)
        .where(ReportArtifact.report_task_id == task.id)
        .order_by(ReportArtifact.created_at.asc(), ReportArtifact.id.asc())
    ).all()
    return task, list(artifacts)


def get_downloadable_report_artifact(
    session: Session,
    *,
    task_id: str,
    requester_id: str,
    task_type: str = PARENT_LEARNING_REPORT,
) -> tuple[ReportTask, ReportArtifact]:
    """选择并校验正式 PDF，同时兼容历史家长 Markdown 任务。"""

    task, artifacts = get_owned_report_artifacts(
        session,
        task_id=task_id,
        requester_id=requester_id,
        task_type=task_type,
    )
    if task.status != "completed":
        raise ReportArtifactNotReadyError("报告尚未生成完成")
    markdown_artifacts = [item for item in artifacts if item.artifact_type == "markdown"]
    pdf_artifacts = [item for item in artifacts if item.artifact_type == "pdf"]

    # 新链路只有一个私有 PDF；另外两种形态仅用于阶段 15-A 历史兼容。
    historical_markdown = (
        task.task_type == PARENT_LEARNING_REPORT
        and len(artifacts) == 1
        and len(markdown_artifacts) == 1
    )
    historical_dual_parent_report = (
        task.task_type == PARENT_LEARNING_REPORT
        and len(artifacts) == 2
        and len(markdown_artifacts) == 1
        and len(pdf_artifacts) == 1
    )
    current_pdf_report = len(artifacts) == 1 and len(pdf_artifacts) == 1
    if not (
        historical_markdown or historical_dual_parent_report or current_pdf_report
    ):
        raise ReportArtifactIntegrityError("报告产物数量或类型异常")

    if historical_markdown:
        markdown = markdown_artifacts[0]
        validate_downloadable_markdown(task, markdown)
        return task, markdown
    if historical_dual_parent_report:
        validate_downloadable_markdown(task, markdown_artifacts[0])

    pdf = pdf_artifacts[0]
    validate_downloadable_pdf(pdf)
    return task, pdf
