"""使用真实 ChatModel 评估结构化意图识别。

运行前在项目根目录 .env 中配置 LLM_*。本脚本不会输出 API Key，也不会
修改 LangGraph、SSE 或数据库；它只打印脱敏后的结构化识别结果与通过率。
"""

from __future__ import annotations

from backend.app.config import get_settings
from backend.app.integrations.llm import build_langchain_llm
from backend.app.services.intent_recognition import recognize_intent_detailed
from scripts.intent_evaluation.cases import INTENT_CASES
from scripts.intent_evaluation.metrics import (
    EvaluationRecord,
    build_classification_report,
    field_accuracy,
)
from scripts.intent_evaluation.reporting import format_classification_report


def main() -> int:
    """执行真实模型评估，并用进程退出码表达是否全部通过。"""

    settings = get_settings()
    selected_model = settings.llm_router_model or settings.llm_model
    # 与线上依赖工厂保持一致：Router 评测固定零温度，不继承普通回答温度。
    model = build_langchain_llm(
        settings, model_name=selected_model, temperature=0
    )
    if model is None:
        print("未启用真实模型：请检查 .env 中的 LLM_ENABLED、LLM_API_KEY 和 LLM_MODEL。")
        return 2

    records: list[EvaluationRecord] = []
    print(f"Router 模型：{selected_model}；用例数：{len(INTENT_CASES)}")
    for index, case in enumerate(INTENT_CASES, start=1):
        outcome = recognize_intent_detailed(
            case.message,
            active_entity=case.active_entity,
            model=model,
        )
        result = outcome.result
        entity_name = result.mentioned_entity.entity_name if result.mentioned_entity else None
        record = EvaluationRecord(
            expected_intent=case.expected_intent.value,
            actual_intent=result.intent.value,
            expected_entity=case.expected_entity,
            actual_entity=entity_name,
            expected_live_data=case.expected_live_data,
            actual_live_data=result.needs_live_data,
            expected_source=case.expected_source.value,
            actual_source=outcome.source.value,
        )
        records.append(record)
        success = all((
            record.expected_intent == record.actual_intent,
            record.expected_entity == record.actual_entity,
            record.expected_live_data == record.actual_live_data,
            record.expected_source == record.actual_source,
        ))
        print(
            f"[{index}] {'通过' if success else '失败'} | "
            f"intent={result.intent.value} | entity={entity_name or '-'} | "
            f"live={result.needs_live_data} | clarify={result.clarification_needed} | "
            f"source={outcome.source.value}"
        )

    report = build_classification_report(
        (record.expected_intent for record in records),
        (record.actual_intent for record in records),
    )
    print(format_classification_report(report))
    print(
        "字段准确率："
        f"entity={field_accuracy((r.expected_entity for r in records), (r.actual_entity for r in records)):.2%}, "
        f"live_data={field_accuracy((r.expected_live_data for r in records), (r.actual_live_data for r in records)):.2%}, "
        f"source={field_accuracy((r.expected_source for r in records), (r.actual_source for r in records)):.2%}"
    )
    passed = sum(
        all((
            record.expected_intent == record.actual_intent,
            record.expected_entity == record.actual_entity,
            record.expected_live_data == record.actual_live_data,
            record.expected_source == record.actual_source,
        ))
        for record in records
    )
    print(f"严格通过：{passed}/{len(records)}")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
