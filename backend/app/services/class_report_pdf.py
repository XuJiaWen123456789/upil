"""教师班级报告的权威统计校验和 PDF 转换薄层。"""

from __future__ import annotations

from datetime import datetime

from backend.app.class_learning_contracts import ClassLearningSummary
from backend.app.config import Settings
from backend.app.services.markdown_pdf import (
    ReportPdfDocument, ReportPdfError, markdown_to_pdf, validate_safe_markdown,
)
from backend.app.services.report_pdf import extract_report_fields


def validate_class_report_markdown(
    markdown: str, snapshot: ClassLearningSummary
) -> None:
    """确保报告全部统计值与数据库汇总一致，LLM 不能改写口径。"""

    validate_safe_markdown(markdown)
    if markdown.replace("\r\n", "\n").split("\n").count("# 班级学情运营报表") != 1:
        raise ReportPdfError("报告标题不符合班级报告契约")
    fields = extract_report_fields(markdown)
    top5 = "；".join(
        f"学员-{rank:02d}：缺勤 {item.absent_lessons} 次"
        for rank, item in enumerate(snapshot.absence_top5, start=1)
    ) or "无缺勤记录"
    expected = {
        "课程": snapshot.course_name,
        "统计周期": f"{snapshot.period_start} 至 {snapshot.period_end}",
        "有效报名学员": f"{snapshot.enrolled_learners} 人",
        "周期内计划课次": f"{snapshot.scheduled_lessons} 次",
        "完课率": f"{snapshot.completion_rate:.0%}",
        "出勤率": f"{snapshot.attendance_rate:.0%}",
        "应登记考勤": f"{snapshot.expected_attendance_records} 条",
        "已登记考勤": f"{snapshot.marked_attendance_records} 条",
        "出勤": f"{snapshot.attended_records} 条",
        "缺勤": f"{snapshot.absent_records} 条",
        "请假": f"{snapshot.excused_records} 条",
        "未登记": f"{snapshot.unmarked_records} 条",
        "缺勤 TOP5": top5,
        "低课时阈值": f"剩余课时 ≤ {snapshot.low_balance_threshold} 节",
        "低课时学员数": f"{len(snapshot.low_balance_learners)} 人",
        "缺失课时账户": f"{snapshot.missing_hour_accounts} 人",
    }
    if set(fields) != set(expected):
        raise ReportPdfError("班级报告字段缺失或包含契约外字段")
    for key, value in expected.items():
        if fields[key] != value:
            raise ReportPdfError(f"班级报告字段与权威统计不一致：{key}")


def generate_class_report_pdf(
    markdown: str,
    snapshot: ClassLearningSummary,
    settings: Settings,
    *,
    generated_at: datetime,
    filename: str,
) -> ReportPdfDocument:
    """校验班级报告并生成 PDF；原始班级和学员 ID 不得进入文件。"""

    validate_class_report_markdown(markdown, snapshot)
    private_values = [snapshot.class_id]
    private_values.extend(item.learner_id for item in snapshot.learner_metrics)
    return markdown_to_pdf(
        markdown,
        title="班级学情运营报表",
        template_version=settings.report_pdf_template_version,
        font_path=settings.report_pdf_font_path,
        max_bytes=settings.report_pdf_max_bytes,
        max_pages=settings.report_pdf_max_pages,
        filename=filename,
        generated_at=generated_at,
        forbidden_values=tuple(private_values),
    )
