"""uPil 核心业务数据模型。

模型覆盖用户、校区、课程、班级、报名、课时、出勤以及任务审计记录。
字段设计优先保证权限校验、统计口径和后续 A2A 任务追踪所需的数据完整性。
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class User(Base):
    """系统用户，包括家长、教师和管理员。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(32), index=True)
    campus_id: Mapped[str | None] = mapped_column(ForeignKey("campuses.id"), nullable=True)
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
    # 预留结构化范围和模板版本，支持未来 A2A 任务重放与审计。
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
    """任务产生的 Markdown、JSON 或执行轨迹等产物。"""

    __tablename__ = "report_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 报表正文、指标 JSON 或执行轨迹均作为任务产物独立保存。
    report_task_id: Mapped[str] = mapped_column(ForeignKey("report_tasks.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
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


class MediaAsset(Base):
    """媒体资产元数据；原文件保存在 MinIO，业务库不保存二进制。"""

    __tablename__ = "media_assets"

    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    alt_text: Mapped[str] = mapped_column(String(500))
    source_document: Mapped[str] = mapped_column(String(300))
    visibility: Mapped[str] = mapped_column(String(32), default="public_faq", index=True)
    review_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
