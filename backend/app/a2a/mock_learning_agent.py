"""本地 Mock 学情分析智能体。

该模块模拟远程 A2A 子节点的任务处理行为，但不连接数据库、网络、RAGFlow、
MinIO 或 Docker Socket，也不执行用户提交的代码。它只用于自动化测试和答辩演示。
"""

from __future__ import annotations

from backend.app.a2a.contracts import (
    A2AArtifact,
    A2ATaskRequest,
    A2ATaskResult,
    ClassLearningReportInput,
    LearningAnalysisInput,
    LearningReportInput,
)


class MockA2ATimeoutError(TimeoutError):
    """模拟可恢复的远程任务超时。"""


class MockLearningAnalysisAgent:
    """用确定性规则生成学情摘要，便于测试结果稳定可复现。"""

    def __init__(self) -> None:
        # 调用计数用于验证客户端的超时重试上限，不代表生产监控实现。
        self.call_count = 0

    def process(
        self,
        task: A2ATaskRequest,
        *,
        behavior: str = "success",
    ) -> A2ATaskResult:
        """处理一个已通过协议校验的任务。"""

        self.call_count += 1
        if behavior == "timeout":
            raise MockA2ATimeoutError("本地 Mock 节点模拟超时")
        if behavior == "failed":
            return A2ATaskResult(
                task_id=task.task_id,
                correlation_id=task.correlation_id,
                status="failed",
                message="学情分析子节点暂时不可用",
                handoff_required=True,
                retryable=False,
            )
        if behavior == "invalid_artifact":
            # 先构造一个正常结果，再让客户端使用独立校验发现危险内容。
            artifact = A2AArtifact.model_construct(
                artifact_id="artifact_invalid_demo",
                media_type="text/markdown",
                name="learning-summary.md",
                content_ref="artifact://invalid_demo",
                content="#!/bin/sh\necho unsafe",
            )
            return A2ATaskResult.model_construct(
                task_id=task.task_id,
                correlation_id=task.correlation_id,
                status="completed",
                message="本地演示结果",
                artifacts=[artifact],
                quality=None,
                handoff_required=False,
                retryable=False,
            )

        # 按协议技能分发，而不是根据用户文本动态选择执行逻辑。这样可以保证
        # 摘要任务和家长报告任务使用各自固定的输入字段与输出模板。
        if task.skill == "learning_summary":
            report = self._build_summary_report(task)
            artifact_name = "learning-summary.md"
        elif task.skill == "learning_report":
            report = self._build_learning_report(task)
            artifact_name = "learning-report.md"
        elif task.skill == "class_learning_report":
            report = self._build_class_learning_report(task)
            artifact_name = "class-learning-report.md"
        else:  # Literal 已在协议层限制，这里仍保留防御性分支。
            return A2ATaskResult(
                task_id=task.task_id,
                correlation_id=task.correlation_id,
                status="failed",
                message="不支持的 A2A 技能",
                handoff_required=True,
                retryable=False,
            )
        artifact = A2AArtifact(
            artifact_id=f"artifact_{task.task_id}",
            media_type="text/markdown",
            name=artifact_name,
            content_ref=f"artifact://{task.task_id}",
            content=report,
        )
        return A2ATaskResult(
            task_id=task.task_id,
            correlation_id=task.correlation_id,
            status="completed",
            message="本地 Mock 学情分析完成；结果仅用于演示，不代表真实机构结论",
            artifacts=[artifact],
            handoff_required=False,
            retryable=False,
        )

    @staticmethod
    def _build_summary_report(task: A2ATaskRequest) -> str:
        """生成旧版学情摘要，保持阶段 13 的调用兼容性。"""

        # 技能和联合类型同时校验，避免把报告字段误当成摘要字段读取。
        if task.skill != "learning_summary" or not isinstance(task.input, LearningAnalysisInput):
            raise ValueError("摘要任务的输入类型不正确")
        data = task.input
        rate = f"{data.attendance_rate:.0%}"
        focus = "、".join(data.progress_notes) if data.progress_notes else "暂无阶段记录"
        return (
            "# 学情分析摘要\n\n"
            "> 本报告由本地 Mock 学情分析智能体生成，仅用于开发测试和答辩演示。\n\n"
            f"- 分析周期：{data.period}\n"
            f"- 出勤率：{rate}\n"
            f"- 已完成课时：{data.completed_hours}\n"
            f"- 阶段记录：{focus}\n\n"
            "## 建议\n"
            "建议结合教师阶段反馈和后续课堂表现持续观察，不将本摘要作为单次录班或升学结论。"
        )

    @staticmethod
    def _build_learning_report(task: A2ATaskRequest) -> str:
        """生成家长可读的固定 Markdown 报告，不执行任何脚本。"""

        # 报告节点只消费主服务计算后的聚合字段，不重新查询动态数据。
        if task.skill != "learning_report" or not isinstance(task.input, LearningReportInput):
            raise ValueError("报告任务的输入类型不正确")
        data = task.input

        # 课程和进度来自已发布的结构化字段。去掉换行，避免输入被渲染成
        # 报告外部的新标题或列表；这里是展示清洗，不是代码执行沙箱。
        courses = "；".join(_clean_inline(item) for item in data.course_summaries)
        progress = "；".join(_clean_inline(item) for item in data.published_progress)
        courses = courses or "暂无课程摘要"
        progress = progress or "暂无已发布阶段进度"
        rate = f"{data.attendance_rate:.0%}"

        return (
            "# 家长学情报告\n\n"
            "> 本报告由演示环境生成，仅用于开发测试和答辩演示。\n\n"
            "## 一、报告周期\n"
            f"- 统计周期：{data.period_label}（{data.period_start} 至 {data.period_end}）\n\n"
            "## 二、出勤情况\n"
            f"- 应上课次数：{data.scheduled_sessions} 次\n"
            f"- 出勤次数：{data.attended_sessions} 次\n"
            f"- 请假次数：{data.excused_absences} 次\n"
            f"- 缺勤次数：{data.unexcused_absences} 次\n"
            f"- 出勤率：{rate}\n\n"
            "## 三、课时情况\n"
            f"- 本周期已完成课时：{data.completed_lessons} 节\n"
            f"- 当前剩余课时：{data.remaining_lessons} 节\n\n"
            "## 四、课程与阶段进度\n"
            f"- 课程概览：{courses}\n"
            f"- 已发布阶段进度：{progress}\n\n"
            "## 五、说明\n"
            "以上内容基于已授权的演示数据生成，不作为录班、升学、考级或获奖结论。"
        )

    @staticmethod
    def _build_class_learning_report(task: A2ATaskRequest) -> str:
        """使用固定模板组织班级汇总，不接受脚本，也不重新计算指标。"""

        if task.skill != "class_learning_report" or not isinstance(
            task.input, ClassLearningReportInput
        ):
            raise ValueError("班级报表任务的输入类型不正确")
        data = task.input
        top5 = "；".join(_clean_inline(item) for item in data.absence_top5) or "无缺勤记录"

        return (
            "# 班级学情运营报表\n\n"
            "## 一、基本信息\n"
            f"- 课程：{_clean_inline(data.course_name)}\n"
            f"- 统计周期：{_clean_inline(data.period_label)}（{data.period_start} 至 {data.period_end}）\n"
            f"- 有效报名学员：{data.enrolled_learners} 人\n"
            f"- 周期内计划课次：{data.scheduled_lessons} 次\n\n"
            "## 二、核心指标\n"
            f"- 完课率：{data.completion_rate:.0%}\n"
            f"- 出勤率：{data.attendance_rate:.0%}\n"
            f"- 应登记考勤：{data.expected_attendance_records} 条\n"
            f"- 已登记考勤：{data.marked_attendance_records} 条\n"
            f"- 出勤：{data.attended_records} 条\n"
            f"- 缺勤：{data.absent_records} 条\n"
            f"- 请假：{data.excused_records} 条\n"
            f"- 未登记：{data.unmarked_records} 条\n\n"
            "## 三、缺勤关注\n"
            f"- 缺勤 TOP5：{top5}\n\n"
            "## 四、低课时提醒\n"
            f"- 低课时阈值：剩余课时 ≤ {data.low_balance_threshold} 节\n"
            f"- 低课时学员数：{data.low_balance_learner_count} 人\n\n"
            "## 五、数据说明\n"
            "核心指标由主系统按固定统计口径计算，远程报表节点只负责组织展示；"
            "缺勤排行已使用匿名序号，报表不展示学员姓名、手机号或原始学员编号。"
        )


def _clean_inline(value: str) -> str:
    """把结构化文本压成单行，避免破坏固定报告版式。"""

    return " ".join(value.split())
