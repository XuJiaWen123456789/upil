"""多轮状态评测使用的虚构业务场景。

样例覆盖课程推荐、纠错、指代、报告 pending、复合意图、实时数据边界和
主体隔离。所有身份编号都是本项目演示账号或合成值，不包含真实联系方式。
"""

from __future__ import annotations

from backend.app.services.conversation_state import parse_statistics_period
from scripts.intent_evaluation.multiturn import (
    ExpectedSlot,
    MultiTurnCase,
    MultiTurnStep,
)


def build_multiturn_cases() -> tuple[MultiTurnCase, ...]:
    """按执行日期生成自然月期望，并返回稳定的评测场景。"""

    previous_month = parse_statistics_period("上个月")
    if previous_month is None:  # pragma: no cover - 确定性解析器契约守卫
        raise RuntimeError("无法构造上个月评测周期")
    period_start, period_end = previous_month

    return (
        MultiTurnCase(
            "age_and_foundation",
            (
                MultiTurnStep("我想了解编程课", "faq", "course_detail"),
                MultiTurnStep(
                    "12岁，没有编程基础",
                    "faq",
                    "course_recommendation",
                    expected_slots={
                        "child_age": ExpectedSlot(12, "user_explicit"),
                        "programming_foundation": ExpectedSlot(
                            "none", "user_explicit"
                        ),
                    },
                ),
            ),
        ),
        MultiTurnCase(
            "course_correction_and_reference",
            (
                MultiTurnStep("想了解少儿美术创意班", "faq", "course_detail"),
                MultiTurnStep("我说错了，是素描基础班", "faq", "course_detail"),
                MultiTurnStep("那个班需要什么基础", "faq", "course_detail"),
            ),
        ),
        MultiTurnCase(
            "report_pending_resume",
            (
                MultiTurnStep(
                    "帮我生成学情报告",
                    "clarification",
                    "learning_report",
                    expected_unknown_kind="needs_clarification",
                    expected_pending_intent="learning_report",
                    expected_pending_transition="established",
                ),
                MultiTurnStep(
                    "谢谢",
                    "small_talk",
                    "unknown",
                    expected_unknown_kind="small_talk",
                    expected_pending_intent="learning_report",
                    expected_pending_transition="preserved",
                ),
                MultiTurnStep(
                    "上个月",
                    "learning_report",
                    "learning_report",
                    expected_slots={
                        "period_start": ExpectedSlot(
                            period_start, "deterministic"
                        ),
                        "period_end": ExpectedSlot(period_end, "deterministic"),
                    },
                    expected_pending_transition="recovered",
                ),
            ),
        ),
        MultiTurnCase(
            "report_pending_cancel",
            (
                MultiTurnStep(
                    "生成学情报告",
                    "clarification",
                    "learning_report",
                    expected_unknown_kind="needs_clarification",
                    expected_pending_intent="learning_report",
                    expected_pending_transition="established",
                ),
                MultiTurnStep(
                    "不用了",
                    "small_talk",
                    "unknown",
                    expected_unknown_kind="unknown",
                    expected_pending_transition="cancelled",
                ),
            ),
        ),
        MultiTurnCase(
            "price_and_trial",
            (
                MultiTurnStep("我想了解编程项目实践班", "faq", "course_detail"),
                MultiTurnStep(
                    "这个班多少钱，我还想预约试听",
                    "faq",
                    "course_detail",
                    expected_secondary_intents=("trial_booking",),
                ),
            ),
        ),
        MultiTurnCase(
            "live_seat_boundary",
            (
                MultiTurnStep(
                    "少儿编程基础班现在还有名额吗？",
                    "human_handoff",
                    "schedule_or_seat",
                    expected_unknown_kind="unsupported_in_domain",
                ),
            ),
        ),
        MultiTurnCase(
            "live_learning_summary",
            (
                MultiTurnStep(
                    "查询孩子的剩余课时和出勤",
                    "learning_summary",
                    "learning_summary",
                ),
            ),
        ),
        MultiTurnCase(
            "report_history",
            (
                MultiTurnStep(
                    "查看孩子的学习报告",
                    "report_history",
                    "report_history",
                ),
            ),
        ),
        MultiTurnCase(
            "direct_report_generation",
            (
                MultiTurnStep(
                    "帮我生成上个月的学情报告",
                    "learning_report",
                    "learning_report",
                    expected_slots={
                        "period_start": ExpectedSlot(
                            period_start, "deterministic"
                        ),
                        "period_end": ExpectedSlot(period_end, "deterministic"),
                    },
                ),
            ),
        ),
        MultiTurnCase(
            "unresolved_reference",
            (
                MultiTurnStep(
                    "这个课程多少钱",
                    "clarification",
                    "course_detail",
                    expected_unknown_kind="needs_clarification",
                ),
            ),
        ),
        MultiTurnCase(
            "out_of_scope",
            (
                MultiTurnStep(
                    "帮我分析股票走势",
                    "out_of_scope",
                    "unknown",
                    expected_unknown_kind="out_of_scope",
                ),
            ),
        ),
        MultiTurnCase(
            "same_conversation_subject_isolation",
            (
                MultiTurnStep(
                    "我想了解编程项目实践班",
                    "faq",
                    "course_detail",
                    user_id="P1001",
                ),
                MultiTurnStep(
                    "这个课程多少钱",
                    "clarification",
                    "course_detail",
                    expected_unknown_kind="needs_clarification",
                    user_id="P1002",
                ),
            ),
        ),
    )


MULTITURN_CASES = build_multiturn_cases()
