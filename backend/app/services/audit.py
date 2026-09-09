"""审计日志服务。"""

from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import AuditLog


def write_audit_log(
    session: Session,
    *,
    actor_user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """追加一条操作日志并刷新记录，以便调用方获得生成的主键。"""

    record = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        metadata_json=metadata or {},
    )
    session.add(record)
    session.flush()
    return record
