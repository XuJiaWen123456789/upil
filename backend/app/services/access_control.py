"""学员数据访问控制服务。

权限判断集中在服务层，业务查询调用前必须先通过本模块检查，避免把
“无权限”和“无数据”区分暴露给客户端。
"""

from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from backend.app.models import ClassGroup, Enrollment, EnrollmentLead, ParentLearner


@dataclass(frozen=True)
class AccessContext:
    """一次业务请求经过认证后得到的最小权限上下文。"""

    user_id: str
    role: str
    campus_ids: frozenset[str] = frozenset()
    # 权限只允许由认证层从本地数据库注入。使用不可变集合可以防止业务节点
    # 在请求执行过程中临时追加能力，保持整条调用链上的授权结论一致。
    permissions: frozenset[str] = frozenset()
    # 当前项目暂未开放租户切换；保留显式边界是为了让会话和长期记忆在
    # 多机构部署时不会只依赖 user_id 猜测数据归属。默认值兼容所有旧调用。
    tenant_id: str = "default"


def can_manage_leads(context: AccessContext) -> bool:
    """顾问工作区必须同时满足教师角色和明确的线索跟进权限。"""

    return context.role == "teacher" and "lead_followup" in context.permissions


def can_follow_up_lead(context: AccessContext, lead: EnrollmentLead) -> bool:
    """未分配线索可由顾问领取，已分配线索只允许原顾问继续处理。"""

    return can_manage_leads(context) and lead.assigned_advisor_id in {
        None,
        context.user_id,
    }


def can_access_learner(session: Session, context: AccessContext, learner_id: str) -> bool:
    """判断当前用户是否可以访问指定学员。

    家长依赖绑定关系，教师依赖授课班级、有效报名和校区范围。未知角色
    默认拒绝，遵循最小权限原则。
    """

    # 权限判断在读取学员数据之前执行，调用方拿不到越权对象的差异化信息。
    if context.role == "parent":
        # 家长只能访问显式绑定的学员，不能仅凭 learner_id 猜测数据。
        return bool(session.scalar(select(exists().where(
            ParentLearner.parent_id == context.user_id,
            ParentLearner.learner_id == learner_id,
        ))))

    if context.role == "teacher":
        # 认证层正常情况下必定注入教师校区。授权层仍对空范围失败关闭，
        # 形成纵深防御，避免测试桩或未来调用方误把空集合解释成无限范围。
        if not context.campus_ids:
            return False
        conditions = [
            ClassGroup.teacher_id == context.user_id,
            ClassGroup.id == Enrollment.class_id,
            Enrollment.learner_id == learner_id,
            Enrollment.is_active.is_(True),
            ClassGroup.campus_id.in_(context.campus_ids),
        ]
        return bool(session.scalar(select(exists().where(*conditions))))

    return False


def can_access_class(session: Session, context: AccessContext, class_id: str) -> bool:
    """判断当前用户是否可以读取指定班级的聚合统计。

    班级统计包含多名学员的出勤和课时信息，权限不能复用“家长可查看本人
    学员”的规则。家长一律不能读取班级级统计；教师只能读取自己授课的
    有效班级。校区字段仅用于教师跨校区隔离，不代表系统提供校区运营端。
    """

    # 权限判断先于任何班级详情查询，统一将“不存在”和“无权限”处理为 False。
    base_conditions = [ClassGroup.id == class_id, ClassGroup.is_active.is_(True)]

    if context.role == "teacher":
        # 销售顾问老师与授课教师复用 teacher 身份类型，但权限画像互斥。
        # 即使未来误把顾问账号关联到班级，也不能绕过前端导航直接读取班级聚合数据。
        if can_manage_leads(context):
            return False
        # 教师必须同时具备授课关系和明确校区范围，任一条件缺失都拒绝。
        if not context.campus_ids:
            return False
        base_conditions.append(ClassGroup.teacher_id == context.user_id)
        base_conditions.append(ClassGroup.campus_id.in_(context.campus_ids))
        return bool(session.scalar(select(exists().where(*base_conditions))))

    # 家长和未知角色不能通过 class_id 读取包含其他学员的数据。
    return False
