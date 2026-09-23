"""无外部依赖的分类、字段和混淆矩阵指标。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """一次预测的期望值与实际值，均为受控标签。"""

    expected_intent: str
    actual_intent: str
    expected_entity: str | None = None
    actual_entity: str | None = None
    expected_live_data: bool = False
    actual_live_data: bool = False
    expected_source: str = "model"
    actual_source: str = "model"


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    """一个意图标签的分类指标。"""

    label: str
    precision: float
    recall: float
    f1: float
    support: int
    true_positive: int
    false_positive: int
    false_negative: int


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    """总体准确率、逐类指标和矩阵。"""

    labels: tuple[str, ...]
    accuracy: float
    per_class: tuple[ClassMetrics, ...]
    confusion_matrix: tuple[tuple[int, ...], ...]


def _safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def build_classification_report(
    expected: Iterable[str],
    actual: Iterable[str],
    *,
    labels: Iterable[str] | None = None,
) -> ClassificationReport:
    """计算准确率、Precision/Recall/F1 和 expected×actual 矩阵。"""

    expected_values = tuple(expected)
    actual_values = tuple(actual)
    if len(expected_values) != len(actual_values):
        raise ValueError("期望值与实际值数量必须一致")
    resolved_labels = tuple(
        dict.fromkeys(labels or sorted(set(expected_values) | set(actual_values)))
    )
    if not resolved_labels and expected_values:
        raise ValueError("非空样本必须至少包含一个标签")
    index = {label: position for position, label in enumerate(resolved_labels)}
    if any(value not in index for value in (*expected_values, *actual_values)):
        raise ValueError("样本中存在未纳入矩阵的标签")

    matrix = [[0 for _ in resolved_labels] for _ in resolved_labels]
    for expected_value, actual_value in zip(expected_values, actual_values, strict=True):
        matrix[index[expected_value]][index[actual_value]] += 1

    classes: list[ClassMetrics] = []
    for position, label in enumerate(resolved_labels):
        true_positive = matrix[position][position]
        false_positive = sum(row[position] for row in matrix) - true_positive
        false_negative = sum(matrix[position]) - true_positive
        precision = _safe_divide(true_positive, true_positive + false_positive)
        recall = _safe_divide(true_positive, true_positive + false_negative)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        classes.append(ClassMetrics(
            label=label,
            precision=precision,
            recall=recall,
            f1=f1,
            support=sum(matrix[position]),
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
        ))

    correct = sum(
        expected_value == actual_value
        for expected_value, actual_value in zip(expected_values, actual_values, strict=True)
    )
    return ClassificationReport(
        labels=resolved_labels,
        accuracy=_safe_divide(correct, len(expected_values)),
        per_class=tuple(classes),
        confusion_matrix=tuple(tuple(row) for row in matrix),
    )


def field_accuracy(expected: Iterable[Hashable], actual: Iterable[Hashable]) -> float:
    """计算实体、实时标记、来源、槽位或 pending 的精确匹配率。"""

    expected_values = tuple(expected)
    actual_values = tuple(actual)
    if len(expected_values) != len(actual_values):
        raise ValueError("期望值与实际值数量必须一致")
    return _safe_divide(
        sum(
            expected_value == actual_value
            for expected_value, actual_value in zip(
                expected_values, actual_values, strict=True
            )
        ),
        len(expected_values),
    )
