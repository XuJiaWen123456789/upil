"""阶段 1 对话图使用的演示数据。

该模块只用于让 API 在没有初始化数据库时保持可演示状态，不代表生产
数据源；正式流程应调用 services.learning 的数据库查询服务。
"""

from typing import Any


LEARNER_SUMMARIES: dict[str, dict[str, Any]] = {
    # 固定样例用于接口冒烟测试，数值不应被当作真实学员数据。
    "L1001": {
        "learner_id": "L1001",
        "learner_name": "演示学员",
        "remaining_hours": 12,
        "consumed_hours": 8,
        "attendance_rate": 0.9,
        "recent_absences": 1,
    }
}


def get_learner_summary(learner_id: str | None) -> dict[str, Any] | None:
    """按学员编号读取演示摘要，找不到时返回 None。"""

    if learner_id is None:
        return None
    return LEARNER_SUMMARIES.get(learner_id)
