"""报课意向 Agent 的上下文投影。"""


def project_enrollment_intent(envelope) -> dict[str, object]:
    """招生旁路只读取脱敏当前消息和课程实体，不读取数据库私密事实。"""

    return {
        "message": envelope.message,
        "active_entity": envelope.active_entity,
        "conversation_id": envelope.conversation_id,
    }
