"""家长报告的权威字段校验和共享 PDF 转换薄层。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from backend.app.config import Settings
from backend.app.learning_contracts import LearningReportSnapshot
from backend.app.services.markdown_pdf import (
    PDF_MEDIA_TYPE,
    ReportPdfDocument,
    ReportPdfError,
    inspect_report_pdf,
    markdown_to_pdf,
    validate_safe_markdown,
)


@dataclass(frozen=True)
class ValidatedReportMarkdown:
    """已经与主系统权威快照逐项对齐的家长报告字段。"""

    period: str
    course_overview: str
    progress_overview: str


def validate_report_markdown(
    markdown: str, snapshot: LearningReportSnapshot
) -> ValidatedReportMarkdown:
    """校验安全语法，并拒绝模板正文偏离任何确定性统计数字。"""

    validate_safe_markdown(markdown)
    if markdown.replace("\r\n", "\n").split("\n").count("# 家长学情报告") != 1:
        raise ReportPdfError("报告标题不符合家长报告契约")
    fields = extract_report_fields(markdown)
    period = snapshot.period
    expected = {
        "统计周期": f"{period.period_label}（{period.period_start} 至 {period.period_end}）",
        "应上课次数": f"{snapshot.scheduled_sessions} 次",
        "出勤次数": f"{snapshot.attended_sessions} 次",
        "请假次数": f"{snapshot.excused_absences} 次",
        "缺勤次数": f"{snapshot.unexcused_absences} 次",
        "出勤率": f"{snapshot.attendance_rate:.0%}",
        "本周期已完成课时": f"{snapshot.completed_lessons} 节",
        "当前剩余课时": f"{snapshot.remaining_lessons} 节",
        "课程概览": "；".join(snapshot.course_summaries) or "暂无课程摘要",
        "已发布阶段进度": _expected_progress(snapshot),
    }
    if set(fields) != set(expected):
        raise ReportPdfError("报告字段缺失或包含契约外字段")
    for key, value in expected.items():
        if fields[key] != value:
            raise ReportPdfError(f"报告字段与权威快照不一致：{key}")
    return ValidatedReportMarkdown(
        period=fields["统计周期"],
        course_overview=fields["课程概览"],
        progress_overview=fields["已发布阶段进度"],
    )


def generate_report_pdf(
    markdown: str,
    snapshot: LearningReportSnapshot,
    settings: Settings,
    *,
    generated_at: datetime,
    filename: str,
) -> ReportPdfDocument:
    """校验家长报告后调用共享转换器，Markdown 不在此处落库。"""

    validate_report_markdown(markdown, snapshot)
    return markdown_to_pdf(
        markdown,
        title="家长学情报告",
        template_version=settings.report_pdf_template_version,
        font_path=settings.report_pdf_font_path,
        max_bytes=settings.report_pdf_max_bytes,
        max_pages=settings.report_pdf_max_pages,
        filename=filename,
        generated_at=generated_at,
        forbidden_values=(snapshot.learner_ref,),
    )


def extract_report_fields(markdown: str) -> dict[str, str]:
    """读取固定列表字段，重复字段直接失败，避免后写覆盖。"""

    fields: dict[str, str] = {}
    for line in markdown.replace("\r\n", "\n").split("\n"):
        if not line.startswith("- ") or "：" not in line:
            continue
        key, value = line[2:].split("：", 1)
        if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9 ]{1,30}", key) or key in fields:
            raise ReportPdfError("报告字段名称无效或重复")
        fields[key] = value.strip()
    return fields


def _expected_progress(snapshot: LearningReportSnapshot) -> str:
    """复现本地模板中的已发布进度，供逐字交叉校验。"""

    values: list[str] = []
    for item in snapshot.published_progress:
        strengths = "、".join(item.strengths[:3]) or "暂无"
        next_focus = "、".join(item.next_focus[:3]) or "暂无"
        values.append(
            f"课程：{item.course_name}；阶段：{item.current_stage}；"
            f"完成度：{item.completion_rate:.0%}；优势：{strengths}；下一步：{next_focus}"
        )
    return "；".join(values) or "暂无已发布阶段进度"


__all__ = [
    "PDF_MEDIA_TYPE", "ReportPdfDocument", "ReportPdfError", "ValidatedReportMarkdown",
    "extract_report_fields", "generate_report_pdf", "inspect_report_pdf",
    "validate_report_markdown",
]
