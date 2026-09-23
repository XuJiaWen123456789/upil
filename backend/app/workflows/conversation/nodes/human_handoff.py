"""人工协助兜底节点。"""

from backend.app.conversation_understanding import IntentType
from backend.app.workflows.conversation.contracts import ConversationState
from backend.app.context.projectors import project_handoff


def _course_name(state: ConversationState) -> str | None:
    """只从已经通过白名单校验的当前实体读取课程名称。"""

    entity = state.get("active_entity")
    if entity is None or entity.entity_type.value != "course":
        return None
    return entity.entity_name


def _live_schedule_answer(state: ConversationState) -> str:
    """完整回答实时班次与同轮费用问题，不强制收集联系方式。"""

    course_name = _course_name(state)
    target = course_name or "您咨询的课程"
    intent_result = state.get("intent_result")
    attributes = set(intent_result.requested_attributes) if intent_result else set()
    asks_seats = "available_seats" in attributes
    asks_price = "price" in attributes

    if asks_seats and asks_price:
        return (
            f"关于{target}当前班次和剩余名额，我暂时不能直接查看；"
            "具体费用也需要结合校区、班型和当期收费安排确认。"
            "这两项都需要由销售顾问老师查询后再给出准确答复。"
            "如果您目前只是了解，可以先不用留下联系方式。"
        )
    if asks_price:
        return (
            f"关于{target}的具体费用，需要结合校区、班型和当期收费安排确认，"
            "我暂时不能直接给出准确金额。销售顾问老师查询后才能提供准确信息；"
            "如果您目前只是了解，可以先到这里。"
        )
    return (
        f"关于{target}当前是否有合适班次，我暂时不能直接查看实时排课和名额。"
        "需要由销售顾问老师结合校区当前安排确认，确认后再为您说明可选时间。"
        "如果您目前只是了解，可以先到这里。"
    )


def answer_human_handoff(state: ConversationState) -> dict[str, str]:
    """返回真实场景下的人工协助提示，不伪造已经创建工单。"""

    envelope = state.get("context_envelope")
    if envelope is not None:
        project_handoff(envelope)
    intent_result = state.get("intent_result")
    if intent_result is not None and intent_result.intent == IntentType.SCHEDULE_OR_SEAT:
        return {"answer": _live_schedule_answer(state), "provider": "handoff"}
    return {
        "answer": (
            "这个问题需要人工协助，当前无法直接给出确定答复。"
            "请留下便于联系的手机号或微信号，并确认同意工作人员与您联系。"
        ),
        "provider": "handoff",
    }
