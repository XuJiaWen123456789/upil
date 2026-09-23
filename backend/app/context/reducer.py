"""多 Agent 结果归并器。"""

from __future__ import annotations

from typing import Any

from backend.app.context.agent_result import AgentResult
from backend.app.context.conflicts import ContextConflict, merge_state_updates


DEFAULT_WRITABLE_KEYS = frozenset({
    "answer",
    "provider",
    "sources",
    "lead_evidence",
    "memory_candidates",
})


def reduce_agent_results(
    results: tuple[AgentResult, ...] | list[AgentResult],
    *,
    writable_keys: frozenset[str] = DEFAULT_WRITABLE_KEYS,
) -> tuple[dict[str, Any], tuple[ContextConflict, ...]]:
    """按固定顺序合并并行 Agent 结果。

    共享上下文只允许结果归并器写入；后到的 Agent 不能静默覆盖前一结果。
    这使 FAQ 与招生旁路可以并行分析，却不会互相覆盖路由、身份或权限。
    """

    state: dict[str, Any] = {}
    conflicts: list[ContextConflict] = []
    for result in results:
        state, result_conflicts = merge_state_updates(
            state,
            result.as_state(),
            writable_keys=writable_keys,
        )
        conflicts.extend(result_conflicts)
    return state, tuple(conflicts)
