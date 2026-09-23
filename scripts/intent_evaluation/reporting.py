"""评测指标的终端文本格式化。"""

from scripts.intent_evaluation.metrics import ClassificationReport
from scripts.intent_evaluation.multiturn import MultiTurnEvaluationReport


def format_classification_report(report: ClassificationReport) -> str:
    """输出逐类指标和文本混淆矩阵，行是期望、列是实际。"""

    lines = [f"主意图准确率：{report.accuracy:.2%}", "逐类指标："]
    for item in report.per_class:
        lines.append(
            f"- {item.label}: precision={item.precision:.2%}, "
            f"recall={item.recall:.2%}, f1={item.f1:.2%}, support={item.support}, "
            f"TP={item.true_positive}, FP={item.false_positive}, FN={item.false_negative}"
        )

    label_width = max([6, *(len(label) for label in report.labels)])
    cell_width = max(5, label_width)
    lines.append("混淆矩阵（行=期望，列=实际）：")
    lines.append(" " * (label_width + 3) + " ".join(
        label.rjust(cell_width) for label in report.labels
    ))
    for label, row in zip(report.labels, report.confusion_matrix, strict=True):
        lines.append(
            f"{label.rjust(label_width)} | "
            + " ".join(str(value).rjust(cell_width) for value in row)
        )
    return "\n".join(lines)


def format_multiturn_report(report: MultiTurnEvaluationReport) -> str:
    """格式化多轮路由、槽位和 pending 状态指标。"""

    lines = [
        f"多轮场景：{report.case_count}；总轮次：{report.turn_count}",
        f"路由准确率：{report.route_accuracy:.2%}",
        f"主意图准确率：{report.primary_intent_accuracy:.2%}",
        f"旁路意图精确匹配率：{report.secondary_intent_accuracy:.2%}",
        f"UNKNOWN 细分类准确率：{report.unknown_kind_accuracy:.2%}",
        f"pending 状态准确率：{report.pending_state_accuracy:.2%}",
        f"槽位值准确率：{report.slot_value_accuracy:.2%}",
        f"槽位来源准确率：{report.slot_source_accuracy:.2%}",
        f"槽位确认状态准确率：{report.slot_confirmation_accuracy:.2%}",
        "pending 转换成功率：",
    ]
    for name, accuracy in report.pending_transition_accuracy.items():
        lines.append(f"- {name}: {accuracy:.2%}")
    if report.failures:
        lines.append("失败明细（仅合成标签）：")
        for failure in report.failures:
            lines.append(
                f"- {failure.case_id}#{failure.turn_index} {failure.field}: "
                f"expected={failure.expected}, actual={failure.actual}"
            )
    else:
        lines.append("失败明细：无")
    return "\n".join(lines)
