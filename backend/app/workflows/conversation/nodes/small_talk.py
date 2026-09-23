"""问候、礼貌回应和待办取消的固定对话节点。"""

from backend.app.conversation_understanding import IntentType
from backend.app.dialogue import DialogueAct
from backend.app.workflows.conversation.contracts import ConversationState


def _pending_hint(flow_type: IntentType) -> str:
    """返回不泄露内部状态的待办提示。"""

    if flow_type == IntentType.LEARNING_REPORT:
        return "刚才的学情报告请求还在，您可以继续告诉我报告周期。"
    if flow_type == IntentType.CLASS_LEARNING_SUMMARY:
        return "刚才的班级学情查询还在，您可以继续补充班级或统计周期。"
    return "您可以继续补充刚才的问题。"


def answer_small_talk(state: ConversationState) -> dict[str, str]:
    """不访问知识库，直接处理不改变业务事实的会话动作。"""

    decision = state.get("decision")
    if decision is not None and decision.dialogue_act == DialogueAct.CANCEL:
        answer = "好的，已取消刚才未完成的操作。您还可以继续咨询其他课程或服务。"
    elif decision is not None and decision.dialogue_act == DialogueAct.DEFER:
        entity = state.get("active_entity")
        target = (
            entity.entity_name
            if entity is not None and entity.entity_name
            else "当前课程"
        )
        message = state.get("message", "")
        if "联系" in message:
            answer = (
                "好的，目前只保留您的课程咨询，不会安排销售顾问老师联系。"
                "以后如果需要确认名额、费用或试听安排，您再告诉我即可。"
            )
        else:
            answer = (
                f"好的，{target}先不用安排。我不会继续推进本次试听或报名；"
                "您考虑好后随时告诉我，我会接着之前的信息继续协助。"
            )
    elif decision is not None and decision.dialogue_act == DialogueAct.COURTESY:
        if decision.pending_flow is not None:
            answer = f"不客气。{_pending_hint(decision.pending_flow.flow_type)}"
        else:
            answer = "不客气，如有其他课程或服务问题，您可以继续告诉我。"
    else:
        answer = (
            "您好，我是 uPil 学习顾问。您可以咨询课程选择、试听报名、"
            "请假调课或孩子的学情与报告。"
        )
    return {"answer": answer, "provider": "workflow"}
