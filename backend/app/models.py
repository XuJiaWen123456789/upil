"""uPil 核心业务数据模型。

模型覆盖用户、校区、课程、班级、报名、课时、出勤以及任务审计记录。
字段设计优先保证权限校验、统计口径和报告任务追踪所需的数据完整性。
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class User(Base):
    """系统业务用户，包括家长和教师。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(32), index=True)
    campus_id: Mapped[str | None] = mapped_column(ForeignKey("campuses.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class UserPermission(Base):
    """用户的细粒度能力授权，不把能力差异膨胀成新的业务角色。

    uPil 的业务角色只保留家长和教师；媒体上传、媒体复核等机构内部职责
    通过独立权限表达。联合主键保证同一用户不会被重复授予同一能力。
    """

    __tablename__ = "user_permissions"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class ExternalIdentity(Base):
    """OIDC 外部身份与 uPil 本地账号的显式绑定关系。

    OIDC 的 ``sub`` 只在特定 ``issuer`` 下唯一，因此二者共同作为主键。
    授权仍以 ``users`` 表为准，避免外部 Token 中的角色声明直接控制业务权限。
    """

    __tablename__ = "external_identities"
    __table_args__ = (
        # 同一身份提供方下，一个本地用户只绑定一个外部主体。若需要换绑，
        # 必须由受控运维流程先解除旧关系，不能在登录请求中静默覆盖。
        UniqueConstraint("issuer", "user_id", name="uq_external_identity_issuer_user"),
    )

    issuer: Mapped[str] = mapped_column(String(512), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # 单独停用映射可撤销某个 IdP 的登录能力，同时保留本地账号和审计关联。
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Campus(Base):
    """教育机构的校区信息。"""

    __tablename__ = "campuses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Learner(Base):
    """学员基础信息，不直接保存家长关系。"""

    __tablename__ = "learners"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ParentLearner(Base):
    """家长与学员的绑定关系。"""

    __tablename__ = "parent_learners"

    # 使用联合主键，防止同一绑定关系被重复写入。
    parent_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), primary_key=True)


class Course(Base):
    """课程或课程类别信息。"""

    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)


class ClassGroup(Base):
    """具体开班信息，用于连接校区、课程和授课教师。"""

    __tablename__ = "class_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    teacher_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Enrollment(Base):
    """学员与班级的有效报名关系。"""

    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("class_id", "learner_id", name="uq_enrollment_class_learner"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 报表和学情查询都必须通过有效报名关系关联学员与班级。
    class_id: Mapped[str] = mapped_column(ForeignKey("class_groups.id"), index=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Lesson(Base):
    """班级的一次计划课次。"""

    __tablename__ = "lessons"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("class_groups.id"), index=True)
    lesson_date: Mapped[date] = mapped_column(Date, index=True)
    planned_hours: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Attendance(Base):
    """某名学员在某次课次中的出勤状态。"""

    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("lesson_id", "learner_id", name="uq_attendance_lesson_learner"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)


class HourAccount(Base):
    """学员的总课时、已消课时和剩余课时账户。"""

    __tablename__ = "hour_accounts"

    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), primary_key=True)
    total_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remaining_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ReportTask(Base):
    """学情分析或报表任务的生命周期记录。"""

    __tablename__ = "report_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 结构化范围和模板版本用于本地报告任务重放、幂等与审计。
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    scope: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metrics: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReportArtifact(Base):
    """任务最终产物元数据；新任务仅保存私有 PDF。

    ``content`` 继续允许为空是为了兼容阶段 15-A-1 已存在的历史 Markdown
    数据；新的生成链路不会再把 Markdown 中间态写入本表。
    """

    __tablename__ = "report_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 最终 PDF 只在关系库保存元数据，二进制始终位于私有 MinIO。
    report_task_id: Mapped[str] = mapped_column(ForeignKey("report_tasks.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(24))
    # content 仅服务历史 Markdown 兼容；新 PDF 记录必须为空。
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class EnrollmentLead(Base):
    """家长在对话中形成的试听或报名线索。

    线索可以在没有联系方式时先创建。联系方式只保存密文、不可逆指纹和
    脱敏展示值；原始手机号或邮箱不能进入普通业务列、日志或 SSE。
    """

    __tablename__ = "enrollment_leads"
    __table_args__ = (
        CheckConstraint(
            "interest_type IN ('trial', 'enrollment', 'unknown')",
            name="ck_enrollment_lead_interest_type",
        ),
        CheckConstraint(
            "strength IN ('low', 'medium', 'high')",
            name="ck_enrollment_lead_strength",
        ),
        CheckConstraint(
            "destination IN ('lead_pool', 'advisor_queue')",
            name="ck_enrollment_lead_destination",
        ),
        CheckConstraint(
            "status IN ('open', 'awaiting_contact_consent', 'ready_for_followup', "
            "'contacted', 'trial_scheduled', 'enrolled', 'closed_won', "
            "'closed_lost', 'withdrawn')",
            name="ck_enrollment_lead_status",
        ),
        CheckConstraint(
            "(contact_type IS NULL AND contact_ciphertext IS NULL AND "
            "contact_fingerprint IS NULL AND contact_masked IS NULL AND "
            "contact_consent_at IS NULL) OR "
            "(contact_type IN ('phone', 'email') AND contact_ciphertext IS NOT NULL AND "
            "contact_fingerprint IS NOT NULL AND contact_masked IS NOT NULL AND "
            "contact_consent_at IS NOT NULL)",
            name="ck_enrollment_lead_contact_shape",
        ),
        # 同一业务范围只允许一个未关闭线索。部分唯一索引既允许保留历史
        # 终态记录，又能在 PostgreSQL 中挡住两个并发请求同时插入。
        Index(
            "uq_enrollment_lead_open_scope",
            "deduplication_key",
            unique=True,
            postgresql_where=text(
                "status NOT IN ('closed_won', 'closed_lost', 'withdrawn')"
            ),
            sqlite_where=text(
                "status NOT IN ('closed_won', 'closed_lost', 'withdrawn')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 幂等键由家长、学员、课程和意向类型规范化后计算，不包含消息正文。
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    learner_id: Mapped[str | None] = mapped_column(
        ForeignKey("learners.id", ondelete="SET NULL"), nullable=True, index=True
    )
    course_name: Mapped[str] = mapped_column(String(100), index=True)
    interest_type: Mapped[str] = mapped_column(String(24), index=True)
    strength: Mapped[str] = mapped_column(String(16), index=True)
    destination: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    # conversation_ref 只保存前端生成的随机会话引用，不保存用户消息正文。
    conversation_ref: Mapped[str] = mapped_column(String(64), index=True)
    evidence_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    contact_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    contact_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    contact_masked: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assigned_advisor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class LeadFollowUp(Base):
    """课程顾问对招生线索的只追加跟进记录。"""

    __tablename__ = "lead_follow_ups"
    __table_args__ = (
        CheckConstraint(
            "action IN ('claim', 'contact', 'schedule_trial', "
            "'confirm_enrollment', 'close')",
            name="ck_lead_follow_up_action",
        ),
        CheckConstraint(
            "result IN ('claimed', 'reached', 'unreachable', 'declined', "
            "'scheduled', 'cancelled', 'enrolled', 'won', 'lost')",
            name="ck_lead_follow_up_result",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("enrollment_leads.id", ondelete="CASCADE"), index=True
    )
    advisor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[str] = mapped_column(String(32), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    """只追加的操作审计记录。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 审计日志只追加，不承载业务状态，便于后续单独归档和检索。
    actor_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(24))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# 显式导入新增模型，使 Base.metadata、SQLite 测试夹具和迁移生成器都能发现
# 结构化长期记忆表；模型定义本身仍保留在 memory/structured 模块内。
from backend.app.memory.structured.models import StructuredMemoryRecord  # noqa: E402,F401
# 持久会话模型同样单独按领域组织，但必须在这里显式导入，确保
# Base.metadata.create_all() 和测试 SQLite 夹具能够发现对应数据表。
from backend.app.conversations.models import ChatConversation, ChatMessage  # noqa: E402,F401
# 通知 Outbox 按集成领域独立组织；显式导入保证 create_all、测试夹具和
# 元数据检查可以发现该表，同时不把渠道投递逻辑耦合进业务模型文件。
from backend.app.integrations.notifications.models import LeadNotificationOutbox  # noqa: E402,F401
