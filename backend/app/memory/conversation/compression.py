"""短期上下文窗口和确定性滚动摘要。"""

from __future__ import annotations

from backend.app.memory.conversation.contracts import ConversationMemory, ConversationTurn


def estimate_tokens(text: str) -> int:
    """保守估算中英文混合文本 token 数，不绑定特定模型分词器。"""

    if not text:
        return 0
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    return non_ascii_count + (ascii_count + 3) // 4


def _summary_line(turn: ConversationTurn) -> str:
    label = "用户" if turn.role == "user" else "顾问"
    normalized = " ".join(turn.content.split())
    return f"{label}：{normalized[:240]}"


def _trim_to_budget(text: str, token_budget: int) -> str:
    """从尾部保留较新的摘要，直到满足近似 token 预算。"""

    if estimate_tokens(text) <= token_budget:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    for line in reversed(lines):
        candidate = "\n".join(reversed([line, *kept]))
        if estimate_tokens(candidate) > token_budget:
            break
        kept.insert(0, line)
    return "\n".join(kept)


def compress_memory(
    memory: ConversationMemory,
    *,
    recent_turn_limit: int,
    summary_token_budget: int,
    context_token_budget: int,
) -> None:
    """把过旧轮次压入滚动摘要，并执行总上下文预算。

    摘要只压缩已经脱敏的短期文本。它用于恢复话题，不具备业务事实权威性，
    因此课时、出勤、名额和报告状态即使出现在摘要中也不能直接驱动回答。
    """

    overflow = max(0, len(memory.recent_turns) - recent_turn_limit)
    if overflow:
        older = memory.recent_turns[:overflow]
        memory.recent_turns = memory.recent_turns[overflow:]
        additions = "\n".join(_summary_line(turn) for turn in older)
        memory.rolling_summary = "\n".join(
            value for value in (memory.rolling_summary, additions) if value
        )
    memory.rolling_summary = _trim_to_budget(
        memory.rolling_summary, summary_token_budget
    )

    # 总预算超限时先删最旧的原始轮次，摘要和最近一轮优先保留。
    def total_tokens() -> int:
        return estimate_tokens(memory.rolling_summary) + sum(
            estimate_tokens(turn.content) for turn in memory.recent_turns
        )

    while len(memory.recent_turns) > 2 and total_tokens() > context_token_budget:
        removed = memory.recent_turns.pop(0)
        memory.rolling_summary = _trim_to_budget(
            "\n".join(
                value
                for value in (memory.rolling_summary, _summary_line(removed))
                if value
            ),
            summary_token_budget,
        )
