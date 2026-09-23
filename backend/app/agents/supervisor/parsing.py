"""供应商结构化输出解析。

不同模型适配器可能返回 Pydantic 对象、字典、AIMessage 或单个 JSON 代码块；
这些兼容性判断集中在这里，业务规则模块只接收 IntentResult。
"""

from collections.abc import Mapping
import json
import re
from typing import Any

from backend.app.conversation_understanding import IntentResult


def message_content(output: Any) -> Any:
    """把供应商消息对象规整为字典或文本。"""

    if isinstance(output, Mapping):
        return dict(output)
    content = getattr(output, "content", output)
    if isinstance(content, list):
        # 兼容多模态模型返回的文本块列表，不接受任意非文本块。
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, Mapping) and isinstance(item.get("text"), str)
        )
    return content


def parse_model_output(output: Any) -> IntentResult:
    """解析并校验模型输出的 IntentResult 结构。"""

    if isinstance(output, IntentResult):
        return output
    content = message_content(output)
    if isinstance(content, Mapping):
        return IntentResult.model_validate(dict(content))
    if not isinstance(content, str):
        raise ValueError("结构化模型没有返回JSON文本或字典")

    text = content.strip()
    fenced = re.fullmatch(
        r"\x60\x60\x60(?:json)?\s*(.*?)\s*\x60\x60\x60",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        text = fenced.group(1).strip()
    return IntentResult.model_validate(json.loads(text))
