"""FAQ Agent 的上下文投影。"""


_PREFERENCE_LABELS = {
    "course_interest": "课程兴趣",
    "class_time_preference": "上课时间偏好",
}
_RECOMMENDATION_MARKERS = ("推荐", "怎么选", "选什么", "适合什么", "课程建议", "选课")
_TIME_MARKERS = ("上课时间", "上课时段", "时间安排", "什么时候上课")
_MEMORY_REFERENCE_MARKERS = (
    "以前记住", "之前记住", "已经记住", "已记住", "记住的",
    "记录的偏好", "已记录的偏好", "长期偏好", "记忆中的偏好",
)
_MEMORY_RECALL_MARKERS = (
    "还记得", "记得孩子", "记得我们", "之前告诉", "以前告诉",
    "保存的", "已保存", "记录的", "已记录",
    # 用户也可能不说“记得”，而是直接询问已知 key 对应的稳定事实。
    "小名是什么", "叫什么小名", "昵称是什么",
    "喜欢什么课程", "对什么课程感兴趣",
    "方便上课的时间是什么", "方便什么时候上课",
)
_MEMORY_FIELD_MARKERS = {
    "child_nickname": ("小名", "昵称"),
    "course_interest": (
        "喜欢什么", "喜欢的课程", "课程兴趣", "感兴趣的课程",
    ),
    "class_time_preference": (
        "什么时候方便", "什么时间方便", "方便上课的时间",
        "上课时间偏好", "上课时段",
    ),
}


def build_memory_reference_answer(query: str, memories) -> str | None:
    """为用户明确引用长期偏好时生成确定性回答。

    长期偏好虽然会被拼入 FAQ 检索问题，但外部知识库中的旧客服话术仍可能
    错误声称“无法读取记忆”。当用户明确要求根据已保存偏好推荐课程时，应用
    已经掌握结构化事实，不应再让生成模型判断自己是否具有记忆能力。这里仅
    复述低敏感白名单字段并给出课程方向建议；具体班次、价格和名额仍不推断。
    """

    values = {
        str(memory.get("key", "")): str(memory.get("value", "")).strip()
        for memory in memories or ()
        if str(memory.get("value", "")).strip()
    }

    # “你还记得孩子的小名吗”属于读取既有事实，而不是新的记忆写入命令。
    # 字段由固定白名单和确定性短语匹配选择，模型不能自行指定任意 memory_key，
    # 从而避免把一个用户的全部偏好一次性暴露，也不会把查询误送到知识库。
    recalls_memory = any(marker in query for marker in _MEMORY_RECALL_MARKERS)
    recalled_key = next(
        (
            key
            for key, markers in _MEMORY_FIELD_MARKERS.items()
            if any(marker in query for marker in markers)
        ),
        None,
    )
    if recalls_memory and recalled_key is not None:
        value = values.get(recalled_key)
        if recalled_key == "child_nickname":
            return (
                f"记得，孩子的小名叫{value}。"
                if value
                else "我目前没有查到已保存的孩子小名。"
            )
        if recalled_key == "course_interest":
            return (
                f"记得，孩子对{value}课程感兴趣。"
                if value
                else "我目前没有查到已保存的课程兴趣。"
            )
        return (
            f"记得，您之前说{value}方便上课。"
            if value
            else "我目前没有查到已保存的上课时间偏好。"
        )

    # 综合推荐沿用原有入口：只有用户明确引用长期偏好并要求推荐时，才把
    # 多个低敏感字段组合起来，普通 FAQ 不会因为存在长期记忆而被拦截。
    if not any(marker in query for marker in _MEMORY_REFERENCE_MARKERS):
        return None
    if not any(marker in query for marker in _RECOMMENDATION_MARKERS):
        return None

    interest = values.get("course_interest")
    time_preference = values.get("class_time_preference")
    nickname = values.get("child_nickname")
    if not interest and not time_preference:
        return (
            "我目前没有查到可用于推荐的已保存课程偏好。您可以告诉我孩子的年龄、"
            "课程兴趣和方便上课的时段，我再帮您筛选。"
        )

    subject = nickname or "孩子"
    remembered: list[str] = []
    if interest:
        remembered.append(f"{subject}对{interest}感兴趣")
    if time_preference:
        remembered.append(f"通常{time_preference}方便上课")

    if interest:
        recommendation = f"可以优先了解{interest}方向的课程。"
    else:
        recommendation = "还需要补充孩子感兴趣的课程方向后，我才能进一步推荐。"
    return (
        f"根据之前记住的偏好，{'，'.join(remembered)}。{recommendation}"
        "再告诉我孩子的年龄和是否有相关基础，我可以继续筛选具体班型。"
        "具体时段、班次和实时名额需要由销售顾问老师结合当前排课确认。"
    )


def build_preference_aware_query(query: str, memories) -> str:
    """仅在推荐或时间选择问题中附加低敏感长期偏好。

    长期偏好只是检索和表达提示，不能覆盖课程目录、实时名额、价格或
    业务数据库事实。昵称不影响知识检索，因此不拼入 Query，减少无关信息。
    """

    wants_recommendation = any(marker in query for marker in _RECOMMENDATION_MARKERS)
    wants_time = any(marker in query for marker in _TIME_MARKERS)
    if not wants_recommendation and not wants_time:
        return query

    allowed_keys = {"class_time_preference"}
    if wants_recommendation:
        allowed_keys.add("course_interest")
    hints = [
        f"{_PREFERENCE_LABELS[key]}={str(memory.get('value', ''))[:100]}"
        for memory in memories or ()
        if (key := str(memory.get("key", ""))) in allowed_keys
        and str(memory.get("value", "")).strip()
    ]
    if not hints:
        return query
    return f"{query}\n已确认的长期偏好（仅作推荐参考）：{'；'.join(hints)}"


def project_faq(envelope) -> dict[str, object]:
    """FAQ 只读取脱敏检索问题和课程短期实体。"""

    query = envelope.rewritten_query or envelope.message
    return {
        "query": build_preference_aware_query(query, envelope.structured_memories),
        "active_entity": envelope.active_entity,
        "recent_turns": envelope.recent_turns,
        "structured_memories": envelope.structured_memories,
    }
