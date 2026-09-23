"""机构业务范围外问题的固定边界节点。"""

from backend.app.workflows.conversation.contracts import ConversationState


def answer_out_of_scope(state: ConversationState) -> dict[str, str]:
    """拒绝把域外问题交给课程知识库生成看似可信的回答。"""

    return {
        "answer": (
            "这个问题不在当前服务范围内。我可以继续帮助您了解 uPil 的课程、"
            "试听报名、校区服务、请假调课和学情报告。"
        ),
        "provider": "workflow",
    }
