"""学情分析领域服务。

本模块保留面向业务的摘要接口，并将具体的结构化读取委托给 tools 包。
这样 LangGraph 节点可以继续使用稳定的旧接口，同时新的工具契约可以被
API、测试和未来的 A2A 子节点复用。
"""

from sqlalchemy.orm import Session

from backend.app.services.access_control import AccessContext, can_access_learner
from backend.app.tools.learning_tools import query_learning_snapshot


def get_learning_summary(
    session: Session, context: AccessContext, learner_id: str
) -> dict | None:
    """查询单名学员的课时和出勤摘要。"""

    # 先做一次显式授权，再进入工具组合查询，避免把“无权限”和“无数据”
    # 暴露给客户端；工具内部仍会重复校验，形成纵深防御。
    if not can_access_learner(session, context, learner_id):
        return None

    snapshot = query_learning_snapshot(session, context, learner_id)
    if snapshot is None:
        return None

    profile = snapshot["profile"]
    balance = snapshot["balance"]
    attendance = snapshot["attendance"]

    return {
        "learner_id": profile.learner_id,
        "learner_name": profile.learner_name,
        "remaining_hours": balance.remaining_hours,
        "consumed_hours": balance.consumed_hours,
        "attendance_rate": attendance.attendance_rate,
        "recent_absences": attendance.absent_lessons,
    }


def get_learning_snapshot(
    session: Session, context: AccessContext, learner_id: str
) -> dict | None:
    """返回经过 Pydantic 契约校验的完整学情快照。"""

    # 该接口面向结构化 API 和未来 A2A 任务，不直接生成自然语言。
    return query_learning_snapshot(session, context, learner_id)
