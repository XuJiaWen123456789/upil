"""加载人工审核的合成知识问答样本。"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CASES = Path(__file__).resolve().parents[2] / "knowledge_base/evaluation/knowledge_cases.jsonl"
DOMAINS = frozenset({"public", "rules"})
BOUNDARIES = frozenset({"answer", "handoff", "refuse"})


@dataclass(frozen=True)
class KnowledgeCase:
    case_id: str
    domain: str
    question: str
    expected_sources: tuple[str, ...]
    must_include: tuple[str, ...]
    must_not_include: tuple[str, ...]
    boundary: str


def load_cases(path: Path = DEFAULT_CASES) -> tuple[KnowledgeCase, ...]:
    """拒绝非法/重复样本，避免静默跳过样本导致基线虚高。"""

    cases: list[KnowledgeCase] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        case_id = row["id"]
        if not isinstance(case_id, str) or not case_id.startswith("KE-") or case_id in seen:
            raise ValueError(f"第 {line_number} 行样本编号无效或重复")
        seen.add(case_id)
        if row["domain"] not in DOMAINS or row["boundary"] not in BOUNDARIES:
            raise ValueError(f"{case_id} 的知识域或边界无效")
        fields = ("expected_sources", "must_include", "must_not_include")
        if not isinstance(row["question"], str) or not row["question"].strip():
            raise ValueError(f"{case_id} 缺少问题")
        if any(not isinstance(row[name], list) or any(not isinstance(x, str) for x in row[name]) for name in fields):
            raise ValueError(f"{case_id} 的期望字段必须是字符串列表")
        cases.append(KnowledgeCase(
            case_id=case_id,
            domain=row["domain"],
            question=row["question"],
            expected_sources=tuple(row["expected_sources"]),
            must_include=tuple(row["must_include"]),
            must_not_include=tuple(row["must_not_include"]),
            boundary=row["boundary"],
        ))
    if not cases:
        raise ValueError("评测集为空")
    return tuple(cases)


def cases_fingerprint(cases: tuple[KnowledgeCase, ...]) -> str:
    """对规范化样本内容取指纹，避免仅靠样本数误比不同版本。"""

    payload = [vars(case) for case in cases]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
