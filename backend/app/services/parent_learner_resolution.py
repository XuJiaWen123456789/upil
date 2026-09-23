"""家长聊天场景中的学员作用域解析。

该服务只解析当前家长已经绑定且仍有效的学员，不把内部学员编号暴露给聊天
用户。显式编号越权、学员不存在和绑定失效使用同一种拒绝状态，避免资源枚举。
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Learner, ParentLearner
from backend.app.services.access_control import AccessContext, can_access_learner


ResolutionStatus = Literal["resolved", "multiple", "missing", "denied"]


@dataclass(frozen=True, slots=True)
class ParentLearnerResolution:
    """家长学员解析结果；候选项只包含可向当前家长展示的孩子姓名。"""

    status: ResolutionStatus
    learner_id: str | None = None
    candidate_names: tuple[str, ...] = ()


def resolve_parent_learner(
    session: Session,
    context: AccessContext,
    *,
    requested_learner_id: str | None,
    message: str,
) -> ParentLearnerResolution:
    """解析本轮学情请求应使用的学员。

    唯一绑定自动选中；多个孩子时允许用户在完整问题中直接写孩子姓名，
    否则返回姓名列表要求选择。绝不默认取数据库第一条，防止查错孩子。
    """

    if context.role != "parent":
        return ParentLearnerResolution(status="denied")

    if requested_learner_id and not can_access_learner(
        session, context, requested_learner_id
    ):
        # 越权时不继续查询或返回当前账号的其他绑定关系。
        return ParentLearnerResolution(status="denied")

    rows = session.execute(
        select(Learner.id, Learner.display_name)
        .join(ParentLearner, ParentLearner.learner_id == Learner.id)
        .where(
            ParentLearner.parent_id == context.user_id,
            Learner.is_active.is_(True),
        )
        .order_by(Learner.display_name, Learner.id)
    ).all()

    if requested_learner_id:
        if any(learner_id == requested_learner_id for learner_id, _ in rows):
            return ParentLearnerResolution(
                status="resolved", learner_id=requested_learner_id
            )
        return ParentLearnerResolution(status="denied")
    if not rows:
        return ParentLearnerResolution(status="missing")
    if len(rows) == 1:
        return ParentLearnerResolution(status="resolved", learner_id=rows[0][0])

    matched = [row for row in rows if row[1] and row[1] in message]
    if len(matched) == 1:
        return ParentLearnerResolution(status="resolved", learner_id=matched[0][0])
    return ParentLearnerResolution(
        status="multiple",
        candidate_names=tuple(dict.fromkeys(name for _, name in rows)),
    )


def learner_resolution_answer(resolution: ParentLearnerResolution) -> str:
    """将内部解析状态转换为不泄露编号和绑定细节的家长提示。"""

    if resolution.status == "multiple":
        names = "、".join(resolution.candidate_names)
        return f"当前账号绑定了多个孩子，请在问题中说明要查询哪位孩子：{names}。"
    return "暂未找到可访问的学员数据，请确认当前账号的绑定关系后再试。"
