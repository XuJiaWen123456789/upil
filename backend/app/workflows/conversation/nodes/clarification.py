"""信息不足时的澄清节点。"""

from backend.app.conversation_understanding import IntentType
from backend.app.dialogue import UnknownKind
from backend.app.conversation_understanding import has_course_reference
from backend.app.workflows.conversation.contracts import ConversationState


def answer_clarification(state: ConversationState) -> dict[str, str]:
    """阻止不完整实体或意图进入数据与工具层。

    澄清问题必须承接用户当前正在办理的业务，不能统一回复成“请说明具体
    问题”。否则虽然安全地阻止了不完整请求，用户仍会误以为系统忘记了上
    一句话。这里仅依据 Supervisor 已确认的白名单意图选择固定文案，不让
    模型自由生成日期、班级或学员等业务参数。
    """

    intent_result = state.get("intent_result")
    intent = intent_result.intent if intent_result is not None else IntentType.UNKNOWN
    decision = state.get("decision")

    if intent == IntentType.LEARNING_REPORT:
        answer = (
            "请说明要生成哪个周期的学情报告，例如“本月”“上个月”"
            "或“最近30天”。"
        )
    elif intent == IntentType.CLASS_LEARNING_SUMMARY:
        if state.get("class_id"):
            answer = (
                "请说明要查询哪个周期的班级学情，例如“本月”“上个月”"
                "或“最近30天”。"
            )
        else:
            answer = (
                "请说明要查询的班级和统计周期，例如“舞蹈一班上个月的"
                "学情情况”。"
            )
    elif (
        decision is not None
        and decision.unknown_kind == UnknownKind.NEEDS_CLARIFICATION
        and has_course_reference(state.get("message", ""))
        and state.get("active_entity") is None
    ):
        answer = (
            "您提到的“这个课程”目前没有可关联的上文。请告诉我具体课程名称，"
            "例如“少儿编程基础班”或“舞蹈启蒙班”，我再继续回答。"
        )
    else:
        answer = "为了准确回答，请说明您想咨询的具体课程、校区或业务问题。"

    return {
        "answer": answer,
        "provider": "workflow",
    }
