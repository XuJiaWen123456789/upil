"""教师班级学情摘要节点。"""

from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.app.class_learning_contracts import ClassLearningSummary
from backend.app.tools.class_learning_tools import query_class_learning_summary
from backend.app.workflows.conversation.contracts import ConversationState


def answer_class_learning_summary(state: ConversationState) -> dict[str, Any]:
    """查询教师有权访问班级的确定性聚合指标。"""

    context = state.get("access_context")
    if context is None:
        return {"answer": "当前用户身份无效，请重新登录后再查询。", "provider": "workflow"}
    if context.role != "teacher":
        return {"answer": "班级学情统计仅向已授权的教师开放。", "provider": "database"}

    session = state.get("session")
    class_id = state.get("class_id")
    period_start = state.get("period_start")
    period_end = state.get("period_end")
    if session is None or not class_id or period_start is None or period_end is None:
        return {
            "answer": "请补充具体班级和统计周期，例如“统计舞蹈一班2026年8月的出勤率”。",
            "provider": "workflow",
        }
    try:
        summary = query_class_learning_summary(
            session=session,
            context=context,
            class_id=class_id,
            period_start=period_start,
            period_end=period_end,
            low_balance_threshold=state.get("low_balance_threshold", 5),
        )
    except (SQLAlchemyError, ValueError):
        return {
            "answer": "班级学情统计暂时不可用，请检查统计周期后重试或转人工客服。",
            "provider": "database",
        }
    if summary is None:
        return {
            "answer": "暂未找到可访问的班级学情数据，请核对授权范围后重试。",
            "provider": "database",
        }
    try:
        validated = ClassLearningSummary.model_validate(summary.model_dump())
    except Exception:
        return {"answer": "班级学情统计结果无法校验，请转人工客服处理。", "provider": "database"}

    def format_learner(metric: Any) -> str:
        """生成仅供已授权教师查看的学员统计行。"""

        return (
            f"{metric.learner_name}（{metric.learner_id}，"
            f"缺勤{metric.absent_lessons}次，剩余课时"
            f"{metric.remaining_hours if metric.remaining_hours is not None else '未知'}节）"
        )

    absence_text = "、".join(format_learner(item) for item in validated.absence_top5)
    if not absence_text:
        absence_text = "暂无缺勤记录"
    low_balance_text = "、".join(
        format_learner(item) for item in validated.low_balance_learners
    )
    if not low_balance_text:
        low_balance_text = "暂无低课时学员"

    period_text = f"{validated.period_start.isoformat()} 至 {validated.period_end.isoformat()}"
    answer = (
        f"{validated.class_name}（{validated.course_name}）{period_text}学情统计：\n"
        f"- 有效学员：{validated.enrolled_learners}人\n"
        f"- 计划课次：{validated.scheduled_lessons}次\n"
        f"- 完课率：{validated.completion_rate:.2%}\n"
        f"- 出勤率：{validated.attendance_rate:.2%}\n"
        f"- 缺勤TOP5：{absence_text}\n"
        f"- 低课时学员（剩余课时≤{validated.low_balance_threshold}节）：{low_balance_text}\n"
        f"- 未登记考勤：{validated.unmarked_records}条；缺失课时账户："
        f"{validated.missing_hour_accounts}人\n\n"
        "说明：完课率按出勤课次除以应登记考勤记录计算；出勤率按出勤课次除以已登记考勤记录计算；"
        "请假和未登记记录不计入出勤分子。"
    )
    return {"answer": answer, "provider": "database"}
