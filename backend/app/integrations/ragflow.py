"""RAGFlow 知识库 HTTP 适配器。

RAGFlow 只负责提供有来源约束的知识检索和回答，业务层不直接拼接 URL、
鉴权头或解析第三方响应。未配置 Chat ID/API Key 时，适配器明确返回 None。
"""

from typing import Any

import httpx

from backend.app.config import Settings, get_settings
from backend.app.schemas import AgentResponse, SourceReference


class RagflowClient:
    """面向 RAGFlow OpenAI 兼容 Chat API 的最小客户端。"""

    # v0.27+ 的推荐 OpenAI 兼容路径；旧 chats_openai 路径仅作为兼容入口保留。
    OPENAI_CHAT_PATH = "/api/v1/openai/{chat_id}/chat/completions"

    def __init__(self, settings: Settings | None = None, chat_id: str | None = None) -> None:
        """保存配置快照，并允许业务智能体显式指定自己的 Assistant。

        显式 Chat ID 用于隔离公开咨询和服务规则两个知识域；为空时保留
        旧版单 Chat ID 配置的兼容行为，避免已有本地测试和部署配置中断。
        """

        self.settings = settings or get_settings()
        self.chat_id = chat_id

    def ask_result(self, question: str) -> AgentResponse | None:
        """向知识库提问并提取统一结果，失败时返回 None。"""

        settings = self.settings
        chat_id = self.chat_id or settings.ragflow_chat_id
        if not settings.ragflow_api_key or not chat_id:
            return None

        url = f"{settings.ragflow_base_url.rstrip('/')}{self.OPENAI_CHAT_PATH.format(chat_id=chat_id)}"
        payload = {
            # 使用 Chat Assistant 已配置的模型；RAGFlow 将占位值 model
            # 解析为该 Assistant 的 llm_id，避免把 ragflow 当成真实模型名。
            "model": "model",
            "messages": [{"role": "user", "content": question}],
            "stream": False,
            # RAGFlow 只有显式开启引用时，才会在 message.reference.chunks
            # 中返回命中文档、切片和图片标识，供 uPil 做脱敏来源展示。
            "extra_body": {"reference": True},
        }
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {settings.ragflow_api_key}"},
                json=payload,
                timeout=settings.ragflow_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = self._extract_content(data)
            if not content:
                return None
            return AgentResponse(
                answer=content,
                provider="ragflow",
                sources=self._extract_sources(data),
            )
        except (httpx.HTTPError, ValueError, TypeError):
            # 不将地址、密钥、响应正文或第三方错误直接暴露给用户。
            return None

    def ask(self, question: str) -> str | None:
        """保留文本接口，兼容早期调用方；新代码优先使用 ask_result。"""

        result = self.ask_result(question)
        return result.answer if result else None

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str | None:
        """从 OpenAI 兼容响应中提取第一条回答文本。"""

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        message = choices[0].get("message", {})
        content = message.get("content") if isinstance(message, dict) else None
        return content.strip() if isinstance(content, str) and content.strip() else None

    @staticmethod
    def _extract_sources(data: dict[str, Any]) -> list[SourceReference]:
        """提取 RAGFlow 引用并转换成 uPil 的脱敏来源结构。

        RAGFlow 不同版本或不同接口可能将引用放在三种位置：
        顶层 references、choices[0].message.reference.chunks，或
        choices[0].message.reference（直接是列表）。这里统一兼容，
        后续业务层只处理 SourceReference，不感知第三方响应差异。
        """

        references = data.get("references")
        if not isinstance(references, list):
            choices = data.get("choices")
            message = choices[0].get("message", {}) if isinstance(choices, list) and choices else {}
            reference = message.get("reference") if isinstance(message, dict) else None
            if isinstance(reference, list):
                # 当前 RAGFlow OpenAI 兼容接口会直接返回 reference 列表。
                references = reference
            elif isinstance(reference, dict):
                # 兼容部分版本使用 reference.chunks 包装引用列表的结构。
                references = reference.get("chunks")
        if not isinstance(references, list):
            return []

        sources: list[SourceReference] = []
        # 先完整解析，再按文档去重并限制数量，避免前几个重复切片挤占有效来源。
        for reference in references:
            if not isinstance(reference, dict):
                continue
            source_id = reference.get("chunk_id") or reference.get("id") or reference.get("document_id")
            title = (
                reference.get("document_name")
                or reference.get("docnm_kwd")
                or reference.get("doc_name")
            )
            snippet = reference.get("content") or reference.get("content_with_weight") or reference.get("snippet")
            raw_score = reference.get("similarity") or reference.get("score")
            try:
                score = float(raw_score) if raw_score is not None else None
            except (TypeError, ValueError):
                score = None
            media_asset_id = reference.get("image_id") or reference.get("img_id")
            # 只返回短片段，避免把知识库原文大量暴露给客户端。
            if isinstance(snippet, str):
                snippet = snippet.strip()[:500] or None
            else:
                snippet = None
            if not any(isinstance(value, str) and value.strip() for value in (source_id, title, snippet)):
                continue
            sources.append(
                SourceReference(
                    source_id=str(source_id) if source_id is not None else None,
                    title=str(title) if title is not None else None,
                    snippet=snippet,
                    media_asset_id=str(media_asset_id) if media_asset_id is not None else None,
                    score=score if score is None or 0 <= score <= 1 else None,
                )
            )
        return RagflowClient._deduplicate_sources(sources)

    @staticmethod
    def _deduplicate_sources(sources: list[SourceReference]) -> list[SourceReference]:
        """按文档标题合并来源，只保留同一文档中分数最高的切片。

        RAGFlow 可能为同一文档返回多个相邻切片。对家长端或审计摘要而言，
        重复展示同一个文件会降低可读性，因此这里保留最高分切片；没有文档
        标题时才退回使用 source_id，避免无标题来源被意外全部合并。
        """

        best_by_document: dict[str, SourceReference] = {}
        for source in sources:
            title = (source.title or "").strip()
            source_id = (source.source_id or "").strip()
            # 文档名优先作为聚合键；缺少文档名时使用切片 ID 保留来源边界。
            key = f"title:{title.casefold()}" if title else f"id:{source_id}"
            current = best_by_document.get(key)
            if current is None or _source_score(source) > _source_score(current):
                best_by_document[key] = source

        # 分数越高越靠前；无分数来源保持在末尾，并最多返回 10 份文档。
        return sorted(
            best_by_document.values(),
            key=_source_score,
            reverse=True,
        )[:10]


def _source_score(source: SourceReference) -> float:
    """将缺失分数的来源排在有分数来源之后。"""

    return source.score if source.score is not None else -1.0
