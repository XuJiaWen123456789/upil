"""学员数据访问控制服务。

权限判断集中在服务层，业务查询调用前必须先通过本模块检查，避免把
“无权限”和“无数据”区分暴露给客户端。
"""

from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from backend.app.models import ClassGroup, Enrollment, ParentLearner
from backend.app.models import MediaAsset


@dataclass(frozen=True)
class AccessContext:
    """一次业务请求经过认证后得到的最小权限上下文。"""

    user_id: str
    role: str
    campus_ids: frozenset[str] = frozenset()


def can_manage_media(context: AccessContext) -> bool:
    """判断是否允许上传或审核媒体资产。"""

    # 教师可提交课程资料，管理员负责审核；家长不能把文件写入机构知识资源。
    return context.role in {"teacher", "admin"}


def can_access_media(context: AccessContext, asset: MediaAsset) -> bool:
    """按角色、可见范围和审核状态判断媒体是否可以生成访问地址。"""

    # 未审核或已拒绝的素材不能对普通用户开放；管理员可查看待审核素材。
    if asset.review_status == "rejected":
        return False
    if asset.review_status != "approved":
        return context.role == "admin"
    if context.role == "admin":
        return True
    if context.role == "parent":
        return asset.visibility == "public_faq"
    if context.role == "teacher":
        return asset.visibility in {"public_faq", "internal_staff"}
    return False


def can_access_learner(session: Session, context: AccessContext, learner_id: str) -> bool:
    """判断当前用户是否可以访问指定学员。

    家长依赖绑定关系，教师依赖授课班级和校区范围，管理员可按校区范围
    限制访问。未知角色默认拒绝，遵循最小权限原则。
    """

    # 权限判断在读取学员数据之前执行，调用方拿不到越权对象的差异化信息。
    if context.role == "admin":
        if not context.campus_ids:
            return True
        return session.scalar(
            select(exists().where(
                ClassGroup.campus_id.in_(context.campus_ids),
                ClassGroup.id == Enrollment.class_id,
                Enrollment.learner_id == learner_id,
                Enrollment.is_active.is_(True),
            ))
        )

    if context.role == "parent":
        # 家长只能访问显式绑定的学员，不能仅凭 learner_id 猜测数据。
        return bool(session.scalar(select(exists().where(
            ParentLearner.parent_id == context.user_id,
            ParentLearner.learner_id == learner_id,
        ))))

    if context.role == "teacher":
        # 教师同时受授课关系和校区范围约束，避免跨班级/跨校区读取。
        conditions = [
            ClassGroup.teacher_id == context.user_id,
            ClassGroup.id == Enrollment.class_id,
            Enrollment.learner_id == learner_id,
            Enrollment.is_active.is_(True),
        ]
        if context.campus_ids:
            conditions.append(ClassGroup.campus_id.in_(context.campus_ids))
        return bool(session.scalar(select(exists().where(*conditions))))

    return False


def can_access_class(session: Session, context: AccessContext, class_id: str) -> bool:
    """判断当前用户是否可以读取指定班级的聚合统计。

    班级统计包含多名学员的出勤和课时信息，权限不能复用“家长可查看本人
    学员”的规则。家长一律不能读取班级级统计；教师只能读取自己授课的
    有效班级；管理员可读取自己授权校区内的有效班级。
    """

    # 权限判断先于任何班级详情查询，统一将“不存在”和“无权限”处理为 False。
    base_conditions = [ClassGroup.id == class_id, ClassGroup.is_active.is_(True)]

    if context.role == "admin":
        # 空 campus_ids 表示演示环境中的全局管理员；生产环境应由认证系统
        # 明确注入授权校区范围，而不是依赖客户端传入的角色字段。
        if context.campus_ids:
            base_conditions.append(ClassGroup.campus_id.in_(context.campus_ids))
        return bool(session.scalar(select(exists().where(*base_conditions))))

    if context.role == "teacher":
        # 教师必须是该班级的授课教师，同时可选地受校区范围约束。
        base_conditions.append(ClassGroup.teacher_id == context.user_id)
        if context.campus_ids:
            base_conditions.append(ClassGroup.campus_id.in_(context.campus_ids))
        return bool(session.scalar(select(exists().where(*base_conditions))))

    # 家长和未知角色不能通过 class_id 读取包含其他学员的数据。
    return False
