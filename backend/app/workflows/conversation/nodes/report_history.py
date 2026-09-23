"""家长历史学情报告入口节点。"""

from typing import Any

from backend.app.workflows.conversation.contracts import ConversationState


def answer_report_history(state: ConversationState) -> dict[str, Any]:
    """返回受控站内入口，不生成报告任务，也不接受模型提供的 URL。

    报告列表接口会再次按当前家长与孩子绑定关系执行权限过滤；这里的按钮
    只是页面导航，不能替代报告列表、详情和下载接口自身的授权校验。
    """

    context = state.get("access_context")
    if context is None or context.role != "parent":
        return {
            "answer": "当前历史学情报告入口仅支持已登录家长查看本人绑定孩子的报告。",
            "provider": "workflow",
        }
    return {
        "answer": (
            "可以，您可以进入学情报告页面，查看已生成报告的任务状态、"
            "历史详情和可下载文件。查看历史不会重新生成报告。"
        ),
        "provider": "workflow",
        "navigation_path": "/parent/reports",
        "navigation_label": "查看学情报告",
    }
