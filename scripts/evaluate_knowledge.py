"""离线校验样本，显式 --live 时执行 RAGFlow 知识问答基线。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.config import get_settings
from backend.app.integrations.ragflow import RagflowClient
from scripts.knowledge_evaluation.cases import DEFAULT_CASES, cases_fingerprint, load_cases
from scripts.knowledge_evaluation.scoring import score_case, summarize


def main() -> int:
    parser = argparse.ArgumentParser(description="知识问答固定集；默认只校验样本，不连接外部服务")
    parser.add_argument("--live", action="store_true", help="使用真实 RAGFlow，按知识域调用两个 Assistant")
    parser.add_argument("--output", type=Path, help="只写脱敏指标和样本编号，不保存问题或回答")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES,
                        help="合成样本文件；指定扩展集时会生成独立指纹")
    args = parser.parse_args()
    cases = load_cases(args.cases)
    print(f"样本校验通过：{len(cases)} 条；公开知识 {sum(c.domain == 'public' for c in cases)} 条，"
          f"服务规则 {sum(c.domain == 'rules' for c in cases)} 条")
    if not args.live:
        print("未执行真实检索；无召回率或回答正确率数据。添加 --live 才会调用 RAGFlow。")
        return 0

    settings = get_settings()
    if not settings.ragflow_api_key or not settings.ragflow_public_chat_id or not settings.ragflow_service_rules_chat_id:
        print("两个知识域的 Chat ID 或 RAGFlow Key 未配置，未产生有效基线。")
        return 2
    clients = {
        "public": RagflowClient(settings, chat_id=settings.ragflow_public_chat_id),
        "rules": RagflowClient(settings, chat_id=settings.ragflow_service_rules_chat_id),
    }
    # 这里测的是 RAGFlow Chat 的回答与引用，不声称测到了原始候选切片的 Recall@k/MRR。
    # 问题均为人工审核的虚构资料样本，不请求真实业务身份与学情工具。
    scores = []
    for case in cases:
        score = score_case(case, clients[case.domain].ask_result(case.question))
        if score.provider == "unavailable":
            print(f"{case.case_id} 的知识服务不可用；中止评测，不写质量基线。")
            return 2
        scores.append(score)
    report = summarize(tuple(scores))
    report["cases_fingerprint"] = cases_fingerprint(cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 2 if report["fallback_count"] else (1 if report["failures"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
