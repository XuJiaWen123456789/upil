"""阶段 14-A-2：学情报告周期解析测试。"""

from datetime import date

import pytest

from backend.app.services.learning_reports import (
    ReportPeriodResolutionError,
    resolve_report_period,
)


DEMO_TODAY = date(2026, 9, 8)


def test_previous_month_is_resolved_to_full_calendar_month() -> None:
    """“上个月”应解析为 2026 年 8 月完整自然月。"""

    result = resolve_report_period("生成上个月的学情报告", today=DEMO_TODAY)
    assert result.period_start == date(2026, 8, 1)
    assert result.period_end == date(2026, 8, 31)
    assert result.period_type == "previous_month"
    assert result.period_label == "2026年8月"


def test_current_month_is_resolved_up_to_today() -> None:
    """“本月”只统计到当前日期，不把未来日期算入报告。"""

    result = resolve_report_period("查看本月学情", today=DEMO_TODAY)
    assert result.period_start == date(2026, 9, 1)
    assert result.period_end == DEMO_TODAY
    assert result.period_type == "current_month"


def test_recent_thirty_days_is_inclusive_of_today() -> None:
    """最近 30 天应包含今天，总天数为 30 天。"""

    result = resolve_report_period("生成最近30天报告", today=DEMO_TODAY)
    # 今天也计入统计范围，因此起点是今天往前 29 个自然日。
    assert result.period_start == date(2026, 8, 10)
    assert result.period_end == DEMO_TODAY
    assert (result.period_end - result.period_start).days + 1 == 30
    assert result.period_type == "recent_30_days"


def test_custom_date_range_supports_chinese_and_iso_formats() -> None:
    """明确起止日期支持中文日期和 ISO 日期混合表达。"""

    chinese = resolve_report_period(
        "统计 2026年8月1日 至 2026年8月31日", today=DEMO_TODAY
    )
    iso = resolve_report_period("统计 2026-08-01 到 2026-08-31", today=DEMO_TODAY)
    assert chinese.period_start == iso.period_start == date(2026, 8, 1)
    assert chinese.period_end == iso.period_end == date(2026, 8, 31)
    assert chinese.period_type == iso.period_type == "custom"


def test_full_month_expression_is_supported() -> None:
    """明确月份可以作为自定义完整月份周期。"""

    result = resolve_report_period("请生成 2026年8月 学情报告", today=DEMO_TODAY)
    assert result.period_start == date(2026, 8, 1)
    assert result.period_end == date(2026, 8, 31)
    assert result.period_type == "custom"


@pytest.mark.parametrize(
    "message",
    [
        "帮我生成学情报告",
        "查看最近几个月的情况",
        "查看一段时间的出勤",
        "生成 2026-08-31 的报告",
        "统计 2026-08-31 至 2026-08-01",
        "统计 2027-01-01 至 2027-01-31",
    ],
)
def test_ambiguous_invalid_or_future_period_is_rejected(message: str) -> None:
    """缺少周期、周期模糊、倒置或未来日期都不能静默生成报告。"""

    with pytest.raises(ReportPeriodResolutionError):
        resolve_report_period(message, today=DEMO_TODAY)


def test_multiple_period_expressions_are_rejected() -> None:
    """同时说“上个月”和“最近30天”时必须要求家长重新确认。"""

    with pytest.raises(ReportPeriodResolutionError):
        resolve_report_period("上个月最近30天的报告", today=DEMO_TODAY)
