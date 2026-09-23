"""本地学情报告叙事生成器。

本模块只负责把已经通过权限校验和数据契约校验的结构化快照组织成
固定模板 Markdown。统计数字来自数据库快照，Markdown 仅作为 PDF 转换
前的内存中间态，不落库，也不承担权限判断或文件存储职责。
"""

from __future__ import annotations

from backend.app.class_learning_contracts import ClassLearningSummary
from backend.app.learning_contracts import LearningReportSnapshot, LearningSummary


def build_learning_summary_text(snapshot: LearningSummary) -> str:
    """生成聊天场景使用的个人学情摘要。"""

    profile = snapshot.profile
    balance = snapshot.balance
    attendance = snapshot.attendance
    progress = "；".join(
        (
            f"{item.course_name}：{item.current_stage}，完成度 {item.completion_rate:.0%}；"
            f"优势：{'、'.join(item.strengths[:3]) or '暂无'}；"
            f"下一步：{'、'.join(item.next_focus[:3]) or '暂无'}"
        )
        for item in snapshot.progress
    ) or "暂无阶段记录"
    return (
        f"{profile.learner_name}当前剩余课时 {balance.remaining_hours} 节，"
        f"累计消课 {balance.consumed_hours} 节，"
        f"近期出勤率 {attendance.attendance_rate:.0%}，"
        f"近期缺勤 {attendance.absent_lessons} 次。"
        f"阶段反馈：{progress}。"
        "以上数据来自受权限保护的学情数据库。"
    )


def build_parent_report_markdown(snapshot: LearningReportSnapshot) -> str:
    """生成家长固定模板 Markdown。

    不加入自由生成段落，保证报告校验器可以逐字段比对快照；家长可见的
    阶段反馈来自主系统已发布字段，不包含教师内部备注。
    """

    courses = "；".join(_clean_inline(item) for item in snapshot.course_summaries)
    progress = "；".join(
        _format_parent_progress(item) for item in snapshot.published_progress
    )
    courses = courses or "暂无课程摘要"
    progress = progress or "暂无已发布阶段进度"
    period = snapshot.period
    return (
        "# 家长学情报告\n\n"
        "> 本报告依据当前账号有权访问的学情记录生成。\n\n"
        "## 一、报告周期\n"
        f"- 统计周期：{period.period_label}（{period.period_start} 至 {period.period_end}）\n\n"
        "## 二、出勤情况\n"
        f"- 应上课次数：{snapshot.scheduled_sessions} 次\n"
        f"- 出勤次数：{snapshot.attended_sessions} 次\n"
        f"- 请假次数：{snapshot.excused_absences} 次\n"
        f"- 缺勤次数：{snapshot.unexcused_absences} 次\n"
        f"- 出勤率：{snapshot.attendance_rate:.0%}\n\n"
        "## 三、课时情况\n"
        f"- 本周期已完成课时：{snapshot.completed_lessons} 节\n"
        f"- 当前剩余课时：{snapshot.remaining_lessons} 节\n\n"
        "## 四、课程与阶段进度\n"
        f"- 课程概览：{courses}\n"
        f"- 已发布阶段进度：{progress}\n\n"
        "## 五、说明\n"
        "以上内容用于阶段学习回顾，不作为录班、升学、考级或获奖结论；"
        "如需确认具体教学安排，请联系授课教师。"
    )


def build_class_report_markdown(snapshot: ClassLearningSummary) -> str:
    """生成教师班级固定模板 Markdown。

    缺勤排行使用匿名序号，不把原始班级 ID、学员 ID 或姓名写入报告；
    所有统计数字直接取自确定性班级快照。
    """

    top5 = "；".join(
        f"学员-{rank:02d}：缺勤 {item.absent_lessons} 次"
        for rank, item in enumerate(snapshot.absence_top5, start=1)
    ) or "无缺勤记录"
    return (
        "# 班级学情运营报表\n\n"
        "## 一、基本信息\n"
        f"- 课程：{_clean_inline(snapshot.course_name)}\n"
        f"- 统计周期：{snapshot.period_start} 至 {snapshot.period_end}\n"
        f"- 有效报名学员：{snapshot.enrolled_learners} 人\n"
        f"- 周期内计划课次：{snapshot.scheduled_lessons} 次\n\n"
        "## 二、核心指标\n"
        f"- 完课率：{snapshot.completion_rate:.0%}\n"
        f"- 出勤率：{snapshot.attendance_rate:.0%}\n"
        f"- 应登记考勤：{snapshot.expected_attendance_records} 条\n"
        f"- 已登记考勤：{snapshot.marked_attendance_records} 条\n"
        f"- 出勤：{snapshot.attended_records} 条\n"
        f"- 缺勤：{snapshot.absent_records} 条\n"
        f"- 请假：{snapshot.excused_records} 条\n"
        f"- 未登记：{snapshot.unmarked_records} 条\n\n"
        "## 三、缺勤关注\n"
        f"- 缺勤 TOP5：{top5}\n\n"
        "## 四、低课时提醒\n"
        f"- 低课时阈值：剩余课时 ≤ {snapshot.low_balance_threshold} 节\n"
        f"- 低课时学员数：{len(snapshot.low_balance_learners)} 人\n"
        f"- 缺失课时账户：{snapshot.missing_hour_accounts} 人\n\n"
        "## 五、数据说明\n"
        "核心指标由主系统按固定统计口径计算，报告服务只负责组织展示；"
        "缺勤排行已使用匿名序号，报表不展示学员姓名、手机号或原始学员编号。"
    )


def _format_parent_progress(item) -> str:
    """把已发布阶段反馈转换为报告契约要求的单行文本。"""

    strengths = "、".join(item.strengths[:3]) or "暂无"
    next_focus = "、".join(item.next_focus[:3]) or "暂无"
    return (
        f"课程：{_clean_inline(item.course_name)}；"
        f"阶段：{_clean_inline(item.current_stage)}；"
        f"完成度：{item.completion_rate:.0%}；"
        f"优势：{_clean_inline(strengths)}；"
        f"下一步：{_clean_inline(next_focus)}"
    )


def _clean_inline(value: str) -> str:
    """把结构化文本压成单行，避免用户数据改变固定报告结构。"""

    return " ".join(str(value).split())


__all__ = [
    "build_class_report_markdown",
    "build_learning_summary_text",
    "build_parent_report_markdown",
]
