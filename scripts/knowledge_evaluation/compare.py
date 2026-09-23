"""比较同一合成样本集的两次有效知识问答评测结果。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare_reports(before: dict, after: dict) -> dict:
    """缺服务、样本数量变化或失败 ID 不一致时拒绝给出误导性增益。"""

    if before["fallback_count"] or after["fallback_count"]:
        raise ValueError("包含知识服务失败，不能比较回答质量")
    if (before["sample_count"] != after["sample_count"] or
            before["citation_eligible"] != after["citation_eligible"]):
        raise ValueError("两次评测样本范围不一致")
    if (not before.get("cases_fingerprint") or
            before["cases_fingerprint"] != after.get("cases_fingerprint")):
        raise ValueError("两次评测样本版本不一致，不能比较质量增益")
    return {
        "sample_count": before["sample_count"],
        "keyword_proxy_delta": after["keyword_proxy_pass"] - before["keyword_proxy_pass"],
        "citation_hit_delta": after["citation_hit"] - before["citation_hit"],
        "before_failed_ids": [row["id"] for row in before["failures"]],
        "after_failed_ids": [row["id"] for row in after["failures"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="比较两份有效的知识问答指标文件")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    print(json.dumps(compare_reports(before, after), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
