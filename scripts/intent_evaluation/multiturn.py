"""无外部模型依赖的多轮对话状态评测器。

本模块关注单轮分类之外的工程指标：路由、主/旁路意图、UNKNOWN 细分类、
槽位值与来源，以及 pending 流程的建立、保留、恢复和取消。评测器默认调用
本地确定性规划链，不访问真实模型、RAGFlow、PostgreSQL、Redis 或 MinIO。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from backend.app.dialogue import DialogueAct
from backend.app.memory.conversation import (
    ConversationSubject,
    InMemoryConversationStore,
)
from backend.app.services.conversation_state import (
    ConversationPlan,
    plan_conversation,
)
from scripts.intent_evaluation.metrics import field_accuracy


@dataclass(frozen=True, slots=True)
class ExpectedSlot:
    """一个需要核对值、来源和确认状态的槽位。"""

    value: object
    source: str
    confirmed: bool = True


@dataclass(frozen=True, slots=True)
class MultiTurnStep:
    """一轮虚构评测输入及其结构化期望。"""

    message: str
    expected_route: str
    expected_primary_intent: str
    expected_secondary_intents: tuple[str, ...] = ()
    expected_unknown_kind: str | None = None
    expected_pending_intent: str | None = None
    expected_slots: Mapping[str, ExpectedSlot] | None = None
    expected_pending_transition: str | None = None
    user_id: str = "P1001"
    role: str = "parent"


@dataclass(frozen=True, slots=True)
class MultiTurnCase:
    """共享一个会话编号的多轮状态场景。"""

    case_id: str
    turns: tuple[MultiTurnStep, ...]


@dataclass(frozen=True, slots=True)
class MultiTurnFailure:
    """不包含真实身份或联系方式的合成用例失败详情。"""

    case_id: str
    turn_index: int
    field: str
    expected: str
    actual: str


@dataclass(frozen=True, slots=True)
class MultiTurnEvaluationReport:
    """多轮决策链的聚合指标。"""

    case_count: int
    turn_count: int
    route_accuracy: float
    primary_intent_accuracy: float
    secondary_intent_accuracy: float
    unknown_kind_accuracy: float
    pending_state_accuracy: float
    slot_value_accuracy: float
    slot_source_accuracy: float
    slot_confirmation_accuracy: float
    pending_transition_accuracy: Mapping[str, float]
    failures: tuple[MultiTurnFailure, ...]


Planner = Callable[..., ConversationPlan]


def _enum_value(value: object | None) -> str | None:
    """把枚举或普通值统一为便于比较的字符串。"""

    if value is None:
        return None
    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _pending_transition(
    previous: str | None,
    current: str | None,
    plan: ConversationPlan,
) -> str:
    """根据前后状态计算本轮 pending 动作。

    只在评测层推导动作，不写回业务状态。取消与正常补全都表现为 pending
    清除，因此使用对话行为进一步区分，避免把取消错误统计成成功恢复。
    """

    if previous is None and current is not None:
        return "established"
    if previous is not None and current == previous:
        return "preserved"
    if previous is not None and current is None:
        if plan.decision and plan.decision.dialogue_act == DialogueAct.CANCEL:
            return "cancelled"
        return "recovered"
    return "none"


def _append_failure(
    failures: list[MultiTurnFailure],
    *,
    case_id: str,
    turn_index: int,
    field: str,
    expected: object,
    actual: object,
) -> None:
    """只记录合成标签，不把消息正文复制到评测结果。"""

    if expected == actual:
        return
    failures.append(MultiTurnFailure(
        case_id=case_id,
        turn_index=turn_index,
        field=field,
        expected=str(expected),
        actual=str(actual),
    ))


def evaluate_multiturn_cases(
    cases: Iterable[MultiTurnCase],
    *,
    planner: Planner = plan_conversation,
) -> MultiTurnEvaluationReport:
    """回放多轮合成场景并计算状态准确率。

    每个场景拥有独立进程内 Store；同一场景内则复用 conversation_id。
    主体由每轮的 tenant/user/role 共同构造，因此还能覆盖“相同会话编号、
    不同用户不得串状态”的隔离边界。
    """

    resolved_cases = tuple(cases)
    route_expected: list[str] = []
    route_actual: list[str] = []
    primary_expected: list[str] = []
    primary_actual: list[str] = []
    secondary_expected: list[tuple[str, ...]] = []
    secondary_actual: list[tuple[str, ...]] = []
    unknown_expected: list[str | None] = []
    unknown_actual: list[str | None] = []
    pending_expected: list[str | None] = []
    pending_actual: list[str | None] = []
    slot_values_expected: list[object] = []
    slot_values_actual: list[object] = []
    slot_sources_expected: list[str | None] = []
    slot_sources_actual: list[str | None] = []
    slot_confirmed_expected: list[bool] = []
    slot_confirmed_actual: list[bool] = []
    transition_results: dict[str, list[bool]] = {}
    failures: list[MultiTurnFailure] = []
    turn_count = 0

    for case in resolved_cases:
        store = InMemoryConversationStore()
        previous_pending: str | None = None
        for turn_index, step in enumerate(case.turns, start=1):
            turn_count += 1
            subject = ConversationSubject(
                tenant_id="default",
                user_id=step.user_id,
                role=step.role,
            )
            plan = planner(
                step.message,
                conversation_id=f"evaluation-{case.case_id}",
                store=store,
                subject=subject,
                model=None,
            )
            decision = plan.decision
            if decision is None:
                raise RuntimeError("多轮评测要求规划器返回 TurnDecision")

            actual_primary = decision.primary_intent.value
            actual_secondary = tuple(
                intent.value for intent in decision.secondary_intents
            )
            actual_unknown = _enum_value(decision.unknown_kind)
            actual_pending = _enum_value(plan.pending_intent)

            route_expected.append(step.expected_route)
            route_actual.append(plan.route)
            primary_expected.append(step.expected_primary_intent)
            primary_actual.append(actual_primary)
            secondary_expected.append(step.expected_secondary_intents)
            secondary_actual.append(actual_secondary)
            unknown_expected.append(step.expected_unknown_kind)
            unknown_actual.append(actual_unknown)
            pending_expected.append(step.expected_pending_intent)
            pending_actual.append(actual_pending)

            for field, expected, actual in (
                ("route", step.expected_route, plan.route),
                ("primary_intent", step.expected_primary_intent, actual_primary),
                ("secondary_intents", step.expected_secondary_intents, actual_secondary),
                ("unknown_kind", step.expected_unknown_kind, actual_unknown),
                ("pending_intent", step.expected_pending_intent, actual_pending),
            ):
                _append_failure(
                    failures,
                    case_id=case.case_id,
                    turn_index=turn_index,
                    field=field,
                    expected=expected,
                    actual=actual,
                )

            for slot_name, expected_slot in (step.expected_slots or {}).items():
                actual_slot = decision.slot_updates.get(slot_name)
                actual_value = actual_slot.value if actual_slot else None
                actual_source = actual_slot.source.value if actual_slot else None
                actual_confirmed = actual_slot.confirmed if actual_slot else False
                slot_values_expected.append(expected_slot.value)
                slot_values_actual.append(actual_value)
                slot_sources_expected.append(expected_slot.source)
                slot_sources_actual.append(actual_source)
                slot_confirmed_expected.append(expected_slot.confirmed)
                slot_confirmed_actual.append(actual_confirmed)
                for suffix, expected, actual in (
                    ("value", expected_slot.value, actual_value),
                    ("source", expected_slot.source, actual_source),
                    ("confirmed", expected_slot.confirmed, actual_confirmed),
                ):
                    _append_failure(
                        failures,
                        case_id=case.case_id,
                        turn_index=turn_index,
                        field=f"slot.{slot_name}.{suffix}",
                        expected=expected,
                        actual=actual,
                    )

            transition = _pending_transition(previous_pending, actual_pending, plan)
            if step.expected_pending_transition is not None:
                success = transition == step.expected_pending_transition
                transition_results.setdefault(
                    step.expected_pending_transition, []
                ).append(success)
                _append_failure(
                    failures,
                    case_id=case.case_id,
                    turn_index=turn_index,
                    field="pending_transition",
                    expected=step.expected_pending_transition,
                    actual=transition,
                )
            previous_pending = actual_pending

    return MultiTurnEvaluationReport(
        case_count=len(resolved_cases),
        turn_count=turn_count,
        route_accuracy=field_accuracy(route_expected, route_actual),
        primary_intent_accuracy=field_accuracy(primary_expected, primary_actual),
        secondary_intent_accuracy=field_accuracy(secondary_expected, secondary_actual),
        unknown_kind_accuracy=field_accuracy(unknown_expected, unknown_actual),
        pending_state_accuracy=field_accuracy(pending_expected, pending_actual),
        slot_value_accuracy=field_accuracy(slot_values_expected, slot_values_actual),
        slot_source_accuracy=field_accuracy(slot_sources_expected, slot_sources_actual),
        slot_confirmation_accuracy=field_accuracy(
            slot_confirmed_expected, slot_confirmed_actual
        ),
        pending_transition_accuracy={
            name: field_accuracy(values, [True] * len(values))
            for name, values in sorted(transition_results.items())
        },
        failures=tuple(failures),
    )
