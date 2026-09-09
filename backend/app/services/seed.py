"""开发数据库初始化数据。

该模块只提供可重复执行的演示数据写入逻辑，方便本地联调和 DBX 等
数据工具查看；生产环境不应直接使用这些演示账号和学员信息。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    Attendance,
    Campus,
    ClassGroup,
    Course,
    Enrollment,
    HourAccount,
    Learner,
    Lesson,
    ParentLearner,
    User,
)


def seed_demo_data(session: Session) -> int:
    """向数据库写入最小演示数据，并返回本次新增记录数。

    使用业务主键判断是否已存在，保证脚本重复执行不会产生重复的
    用户、学员、班级或课次记录。
    """

    added = 0

    def add_if_missing(model: type, identity: object, values: dict) -> None:
        """按主键或指定唯一标识补充一条记录。"""

        nonlocal added
        if session.get(model, identity) is None:
            session.add(model(**values))
            added += 1

    def update_if_different(model: type, identity: object, field: str, value: object) -> None:
        """把已有演示记录的单个字段同步到当前数据方案。"""

        record = session.get(model, identity)
        if record is not None and getattr(record, field) != value:
            setattr(record, field, value)

    add_if_missing(Campus, "C01", {"id": "C01", "name": "主校区"})
    add_if_missing(Campus, "C02", {"id": "C02", "name": "分校区"})
    # 先刷新校区，确保后续 User.campus_id 外键在 PostgreSQL 中可解析。
    # flush 只把当前事务中的 INSERT 发给数据库，不会提前提交事务。
    session.flush()

    add_if_missing(
        User,
        "P1001",
        {"id": "P1001", "display_name": "演示家长", "role": "parent"},
    )
    add_if_missing(
        User,
        "T1001",
        {"id": "T1001", "display_name": "演示教师", "role": "teacher", "campus_id": "C01"},
    )
    add_if_missing(
        User,
        "T1002",
        {"id": "T1002", "display_name": "分校区演示教师", "role": "teacher", "campus_id": "C02"},
    )
    add_if_missing(
        User,
        "T1003",
        {"id": "T1003", "display_name": "未授课演示教师", "role": "teacher", "campus_id": "C01"},
    )
    add_if_missing(
        User,
        "A1001",
        {"id": "A1001", "display_name": "演示管理员", "role": "admin", "campus_id": "C01"},
    )
    add_if_missing(
        User,
        "A2001",
        {"id": "A2001", "display_name": "分校区演示管理员", "role": "admin", "campus_id": "C02"},
    )
    # 一个家长可以绑定多个孩子；该关系由 ParentLearner 单独表达，不把家长直接挂到班级。
    parent_names = {
        "P1002": "演示家长二",
        "P1003": "演示家长三",
        "P1004": "演示家长四",
        "P1005": "演示家长五",
        "P1006": "演示家长六",
        "P1007": "演示家长七",
        "P1008": "演示家长八",
        "P1009": "演示家长九",
        "P1010": "演示家长十",
        "P1011": "演示家长十一",
    }
    for parent_id, display_name in parent_names.items():
        add_if_missing(
            User,
            parent_id,
            {"id": parent_id, "display_name": display_name, "role": "parent"},
        )
    # 先刷新用户，确保教师外键和家长绑定关系使用的用户记录已经存在。
    session.flush()

    add_if_missing(Learner, "L1001", {"id": "L1001", "display_name": "演示学员"})
    add_if_missing(Learner, "L2001", {"id": "L2001", "display_name": "其他学员"})
    # 目标统计班沿用现有舞蹈课程，补齐 12 名学员以便验证缺勤 TOP5 和低课时名单。
    for learner_number in range(1002, 1013):
        learner_id = f"L{learner_number}"
        add_if_missing(
            Learner,
            learner_id,
            {"id": learner_id, "display_name": f"舞蹈演示学员{learner_number - 1000}"},
        )
    add_if_missing(
        Course,
        "COURSE_DANCE",
        {"id": "COURSE_DANCE", "name": "舞蹈", "category": "舞蹈"},
    )
    # 学员和课程先落入当前事务，后续班级、报名和课次的外键才能稳定写入。
    session.flush()

    add_if_missing(
        ClassGroup,
        "CLASS_DANCE_01",
        {
            "id": "CLASS_DANCE_01",
            "name": "舞蹈一班",
            "campus_id": "C01",
            "course_id": "COURSE_DANCE",
            "teacher_id": "T1001",
        },
    )
    add_if_missing(
        ClassGroup,
        "CLASS_DANCE_02",
        {
            "id": "CLASS_DANCE_02",
            "name": "舞蹈二班",
            "campus_id": "C02",
            "course_id": "COURSE_DANCE",
            "teacher_id": "T1001",
        },
    )
    # 让两个现有班级分别归属不同教师，便于验证教师和校区的数据隔离。
    update_if_different(ClassGroup, "CLASS_DANCE_02", "teacher_id", "T1002")
    # 先刷新班级，后续 Enrollment 和 Lesson 的 class_id 外键才可用。
    session.flush()

    # 联合主键和业务唯一约束没有单一字符串主键，因此用查询判断关系是否存在。
    if session.scalar(
        select(ParentLearner).where(
            ParentLearner.parent_id == "P1001", ParentLearner.learner_id == "L1001"
        )
    ) is None:
        session.add(ParentLearner(parent_id="P1001", learner_id="L1001"))
        added += 1

    parent_bindings = {
        "P1002": ["L1002"],
        # 同一家长绑定两个学员，用于验证多子女场景。
        "P1003": ["L1003", "L1004"],
        "P1004": ["L1005"],
        "P1005": ["L1006"],
        "P1006": ["L1007"],
        "P1007": ["L1008"],
        "P1008": ["L1009"],
        "P1009": ["L1010"],
        "P1010": ["L1011"],
        "P1011": ["L1012"],
    }
    for parent_id, learner_ids in parent_bindings.items():
        for learner_id in learner_ids:
            if session.scalar(
                select(ParentLearner).where(
                    ParentLearner.parent_id == parent_id,
                    ParentLearner.learner_id == learner_id,
                )
            ) is None:
                session.add(ParentLearner(parent_id=parent_id, learner_id=learner_id))
                added += 1

    if session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == "CLASS_DANCE_01", Enrollment.learner_id == "L1001"
        )
    ) is None:
        session.add(Enrollment(class_id="CLASS_DANCE_01", learner_id="L1001"))
        added += 1
    if session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == "CLASS_DANCE_02", Enrollment.learner_id == "L2001"
        )
    ) is None:
        session.add(Enrollment(class_id="CLASS_DANCE_02", learner_id="L2001"))
        added += 1

    for learner_number in range(1002, 1013):
        learner_id = f"L{learner_number}"
        if session.scalar(
            select(Enrollment).where(
                Enrollment.class_id == "CLASS_DANCE_01",
                Enrollment.learner_id == learner_id,
            )
        ) is None:
            session.add(Enrollment(class_id="CLASS_DANCE_01", learner_id=learner_id))
            added += 1

    add_if_missing(
        HourAccount,
        "L1001",
        {"learner_id": "L1001", "total_hours": 20, "consumed_hours": 8, "remaining_hours": 12},
    )
    add_if_missing(
        HourAccount,
        "L2001",
        {"learner_id": "L2001", "total_hours": 20, "consumed_hours": 4, "remaining_hours": 16},
    )
    # L1012 有效报名但故意缺少课时账户，用于验证数据不完整时的保守处理。
    balances = {
        "L1002": 8,
        "L1003": 3,
        "L1004": 2,
        "L1005": 15,
        "L1006": 6,
        "L1007": 4,
        "L1008": 10,
        "L1009": 9,
        "L1010": 18,
        "L1011": 7,
    }
    for learner_id, remaining_hours in balances.items():
        add_if_missing(
            HourAccount,
            learner_id,
            {
                "learner_id": learner_id,
                "total_hours": 20,
                "consumed_hours": 20 - remaining_hours,
                "remaining_hours": remaining_hours,
            },
        )
    add_if_missing(
        Lesson,
        "LESSON_01",
        {"id": "LESSON_01", "class_id": "CLASS_DANCE_01", "lesson_date": date(2026, 8, 1), "planned_hours": 1},
    )
    add_if_missing(
        Lesson,
        "LESSON_02",
        {"id": "LESSON_02", "class_id": "CLASS_DANCE_01", "lesson_date": date(2026, 8, 8), "planned_hours": 1},
    )
    for lesson_id, lesson_date in [
        ("LESSON_03", date(2026, 8, 15)),
        ("LESSON_04", date(2026, 8, 22)),
        ("LESSON_05", date(2026, 8, 29)),
        ("LESSON_06", date(2026, 8, 31)),
    ]:
        add_if_missing(
            Lesson,
            lesson_id,
            {
                "id": lesson_id,
                "class_id": "CLASS_DANCE_01",
                "lesson_date": lesson_date,
                "planned_hours": 1,
            },
        )
    # PostgreSQL 会立即校验外键；先刷新课次，再插入依赖课次的出勤记录。
    # 整个函数仍在同一个事务中，后续失败时由调用方统一回滚。
    session.flush()

    # 每行对应 LESSON_01 至 LESSON_06；None 表示本次课尚未登记考勤。
    # 这些状态只用于本地 staging 和答辩演示，不代表真实学员数据。
    attendance_plan = {
        "L1001": ["present", "absent", "present", "absent", "present", "present"],
        "L1002": ["present", "present", "absent", "present", "absent", "present"],
        "L1003": ["absent", "absent", "absent", "present", "leave", "absent"],
        "L1004": ["absent", "present", "absent", "absent", "present", "absent"],
        "L1005": ["present", "absent", "present", "absent", "absent", "present"],
        "L1006": ["present", "present", "leave", "present", "absent", "present"],
        "L1007": ["absent", "leave", "present", "absent", "present", "absent"],
        "L1008": ["present", "present", "present", "present", "present", "present"],
        "L1009": ["present", "absent", "present", "present", "absent", "present"],
        "L1010": ["absent", "present", "absent", "present", "present", "present"],
        "L1011": ["present", "present", "excused", "present", "present", "absent"],
        "L1012": ["present", "absent", None, "present", "absent", "present"],
    }
    existing_attendance = {
        (row.lesson_id, row.learner_id)
        for row in session.execute(select(Attendance.lesson_id, Attendance.learner_id)).all()
    }
    lesson_ids = ["LESSON_01", "LESSON_02", "LESSON_03", "LESSON_04", "LESSON_05", "LESSON_06"]
    for learner_id, statuses in attendance_plan.items():
        for lesson_id, status in zip(lesson_ids, statuses, strict=True):
            if status is None or (lesson_id, learner_id) in existing_attendance:
                continue
            session.add(Attendance(lesson_id=lesson_id, learner_id=learner_id, status=status))
            added += 1

    session.commit()
    return added
