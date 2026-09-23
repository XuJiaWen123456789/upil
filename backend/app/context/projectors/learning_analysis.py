"""统一学情分析 Agent 的上下文投影。"""


def project_learning_analysis(envelope) -> dict[str, object]:
    """学情 Agent 只拿到路由、短期摘要和授权主体，不把记忆当事实源。"""

    return {
        "route": envelope.route,
        "learner_scope": envelope.access_context.user_id,
        "recent_turns": envelope.recent_turns,
        "rolling_summary": envelope.rolling_summary,
    }
