"""共享上下文和 Agent 结果的冲突策略。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ContextConflict:
    """一项被拒绝或需要审计的状态覆盖。"""

    key: str
    previous: Any
    incoming: Any
    reason: str


def merge_state_updates(
    current: Mapping[str, Any],
    updates: Mapping[str, Any],
    *,
    writable_keys: frozenset[str],
) -> tuple[dict[str, Any], tuple[ContextConflict, ...]]:
    """只合并白名单字段，拒绝 Agent 随意覆盖身份和权限状态。"""

    merged = dict(current)
    conflicts: list[ContextConflict] = []
    for key, value in updates.items():
        if key not in writable_keys:
            conflicts.append(ContextConflict(key, merged.get(key), value, "field_not_writable"))
            continue
        if key in merged and merged[key] not in (None, "", [], {}):
            conflicts.append(ContextConflict(key, merged[key], value, "first_value_wins"))
            continue
        merged[key] = value
    return merged, tuple(conflicts)
