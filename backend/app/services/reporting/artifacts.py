"""报告产物的基础持久化操作。

本模块不决定任务状态，也不执行下载授权；这些职责分别属于 commands 和
queries。
"""

from sqlalchemy.orm import Session

from backend.app.models import ReportArtifact


def add_report_artifact(
    session: Session,
    *,
    artifact_id: str,
    task_id: str,
    artifact_type: str,
    content: str | None,
    checksum: str | None = None,
    object_key: str | None = None,
    media_type: str | None = None,
    filename: str | None = None,
    size_bytes: int | None = None,
    page_count: int | None = None,
) -> ReportArtifact:
    """创建一条产物记录；事务提交由上层工作流统一负责。"""

    artifact = ReportArtifact(
        id=artifact_id,
        report_task_id=task_id,
        artifact_type=artifact_type,
        content=content,
        checksum=checksum,
        object_key=object_key,
        media_type=media_type,
        filename=filename,
        size_bytes=size_bytes,
        page_count=page_count,
    )
    session.add(artifact)
    session.flush()
    return artifact
