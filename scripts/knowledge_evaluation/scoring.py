"""确定性的知识答复评估，不使用模型给自己的回答打分。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas import AgentResponse
from scripts.knowledge_evaluation.cases import KnowledgeCase


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    answer_ok: bool
    citation_ok: bool | None
    provider: str
    failure_codes: tuple[str, ...]


def score_case(case: KnowledgeCase, response: AgentResponse | None) -> CaseScore:
    """来源为文档级匹配；无引用不能假装检索正确，关键字仅为弱代理指标。"""

    if response is None:
        return CaseScore(case.case_id, False, False if case.expected_sources else None,
                         "unavailable", ("provider_unavailable",))
    answer = "".join(response.answer.split()).casefold()
    missing = [part for part in case.must_include if "".join(part.split()).casefold() not in answer]
    forbidden = [part for part in case.must_not_include if "".join(part.split()).casefold() in answer]
    # 明确归属应转人工/拒答的样本，必须至少命中其边界提示，不能只按引用判通过。
    answer_ok = not missing and not forbidden
    titles = tuple((source.title or "").strip() for source in response.sources)
    citation_ok = (any(any(title == expected or title.endswith("/" + expected)
                            for title in titles) for expected in case.expected_sources)
                   if case.expected_sources else None)
    failures: list[str] = []
    if missing:
        failures.append("missing_fact_or_boundary")
    if forbidden:
        failures.append("forbidden_claim")
    if citation_ok is False:
        failures.append("missing_expected_citation")
    if response.provider != "ragflow":
        failures.append("non_ragflow_fallback")
    return CaseScore(case.case_id, answer_ok, citation_ok, response.provider, tuple(failures))


def summarize(scores: tuple[CaseScore, ...]) -> dict[str, object]:
    """分母明确；关键字匹配不等同人工判定的最终正确率。"""

    cited = [score for score in scores if score.citation_ok is not None]
    return {
        "sample_count": len(scores),
        "keyword_proxy_pass": sum(score.answer_ok for score in scores),
        "citation_hit": sum(score.citation_ok is True for score in cited),
        "citation_eligible": len(cited),
        "fallback_count": sum(score.provider != "ragflow" for score in scores),
        "failures": [{"id": score.case_id, "codes": list(score.failure_codes)}
                     for score in scores if score.failure_codes],
    }
