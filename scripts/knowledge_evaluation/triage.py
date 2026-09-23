"""将脱敏评测失败编号转换成人工归因清单，不记录真实对话正文。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.knowledge_evaluation.cases import DEFAULT_CASES, load_cases

CAUSES = frozenset({
    "knowledge_gap",
    "retrieval",
    "routing",
    "generation",
    "live_boundary",
    "mechanical_proxy_false_positive",
})
SIGNALS = frozenset({
    "provider_unavailable",
    "missing_fact_or_boundary",
    "forbidden_claim",
    "missing_expected_citation",
    "non_ragflow_fallback",
})
SENSITIVE_PATTERN = re.compile(r"1[3-9]\d{9}|Bearer\s+\S+|sk-[A-Za-z0-9]{12,}", re.I)


def build_triage(report: dict, known_ids: set[str]) -> list[dict]:
    """审查报告中的编号与原因码；归因必须经人工填写，不能自动回写知识库。"""

    rows = []
    for failure in report["failures"]:
        case_id = failure["id"]
        if case_id not in known_ids:
            raise ValueError(f"未知样本编号：{case_id}")
        if not isinstance(failure["codes"], list) or not all(
            isinstance(code, str) and code in SIGNALS for code in failure["codes"]
        ):
            raise ValueError(f"{case_id} 的失败原因码无效")
        rows.append({"id": case_id, "signals": failure["codes"],
                     "cause": "unreviewed", "resolution": "pending", "regression": "pending",
                     "rationale": ""})
    return rows


def apply_reviews(rows: list[dict], reviews: list[dict]) -> list[dict]:
    """把人工审核覆盖到失败清单；审核文件只能包含编号和受控归因字段。

    评测脚本不会从回答正文自动推断原因。这样可以把“关键词代理误报”和
    “真实业务缺陷”明确区分，并且不会把用户的原始对话写入评测产物。
    """

    rows_by_id = {row["id"]: row for row in rows}
    seen: set[str] = set()
    for review in reviews:
        allowed = {"id", "cause", "resolution", "regression", "rationale"}
        if set(review) != allowed:
            raise ValueError("人工归因只能包含 id、cause、resolution、regression、rationale")
        case_id = review["id"]
        if not isinstance(case_id, str) or case_id not in rows_by_id:
            raise ValueError(f"人工归因编号不在当前失败清单中：{case_id}")
        if case_id in seen:
            raise ValueError(f"人工归因编号重复：{case_id}")
        seen.add(case_id)
        if review["cause"] not in CAUSES:
            raise ValueError(f"{case_id} 的人工归因类型无效")
        for field in ("resolution", "regression", "rationale"):
            if not isinstance(review[field], str) or not review[field].strip():
                raise ValueError(f"{case_id} 的 {field} 不能为空")
            if len(review[field]) > 300:
                raise ValueError(f"{case_id} 的 {field} 过长")
            if SENSITIVE_PATTERN.search(review[field]):
                raise ValueError(f"{case_id} 的 {field} 疑似包含敏感信息")
        # 人工记录只允许保存短理由，避免误把回答正文、联系方式等内容带入日志。
        rows_by_id[case_id].update({
            "cause": review["cause"],
            "resolution": review["resolution"],
            "regression": review["regression"],
            "rationale": review["rationale"],
        })
    return list(rows_by_id.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="从知识评测指标创建待人工审核的问题清单")
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES,
                        help="当前评测使用的合成样本文件")
    parser.add_argument("--reviewed", type=Path,
                        help="可选的人工归因覆盖文件，不含问题和回答正文")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    rows = build_triage(report, {case.case_id for case in load_cases(args.cases)})
    if args.reviewed:
        reviews = json.loads(args.reviewed.read_text(encoding="utf-8"))
        if not isinstance(reviews, list):
            raise ValueError("人工归因文件必须是 JSON 数组")
        rows = apply_reviews(rows, reviews)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已列出 {len(rows)} 条待审核样本；归因选项：{', '.join(sorted(CAUSES))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
