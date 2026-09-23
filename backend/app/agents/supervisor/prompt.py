"""Supervisor 结构化意图识别 Prompt 构造器。

Prompt 正文位于资源文件中；本模块只负责注入运行时白名单和当前轮受控
上下文，不把自然语言回答逻辑混入意图识别。
"""

import json

from backend.app.conversation_understanding import (
    CLASS_ALIASES,
    COURSE_ALIASES,
    EntityReference,
    EntityType,
    IntentResult,
    IntentType,
)
from backend.app.prompts import load_prompt

from .constants import ALLOWED_REQUESTED_ATTRIBUTES


def build_intent_prompt(
    message: str,
    *,
    active_entity: EntityReference | None = None,
    rewritten_query: str | None = None,
) -> str:
    """构造带少量高价值混淆样例的结构化识别提示词。

    用户输入通过 JSON 编码后放在不可信数据区域；动态 Schema、课程和班级
    白名单从代码契约注入，避免静态 Prompt 与运行时校验发生漂移。few-shot
    只覆盖容易混淆的业务边界，不能代替后续确定性守卫和状态机仲裁。
    """

    context = {
        "message": message,
        "rewritten_query": rewritten_query or message,
        "active_entity": (
            active_entity.model_dump(mode="json") if active_entity is not None else None
        ),
    }
    schema = IntentResult.model_json_schema()
    return (
        f"{load_prompt('intent_router.txt')}\n"
        f"{load_prompt('intent_router_examples.txt')}\n"
        f"允许的意图：{json.dumps([item.value for item in IntentType], ensure_ascii=False)}\n"
        f"允许的实体类型：{json.dumps([item.value for item in EntityType], ensure_ascii=False)}\n"
        f"当前课程白名单：{json.dumps(sorted(COURSE_ALIASES), ensure_ascii=False)}\n"
        f"当前班级白名单：{json.dumps(sorted(CLASS_ALIASES), ensure_ascii=False)}\n"
        f"允许的属性：{json.dumps(sorted(ALLOWED_REQUESTED_ATTRIBUTES), ensure_ascii=False)}\n"
        f"输出结构：{json.dumps(schema, ensure_ascii=False)}\n"
        f"待识别数据：{json.dumps(context, ensure_ascii=False)}"
    )
