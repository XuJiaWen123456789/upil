"""会话状态、结构化路由和状态隔离测试。"""

import json
import time

from backend.app.services.conversation_state import (
    InMemoryConversationStore,
    plan_conversation,
)


class FakeIntentModel:
    """根据提示词中的当前消息返回可预测结构化结果。"""

    def invoke(self, prompt: str):
        if "不是舞蹈" in prompt:
            name = "编程项目实践班"
        elif "中国舞进阶班" in prompt:
            name = "中国舞进阶班"
        else:
            name = "编程项目实践班"
        return json.dumps(
            {
                "intent": "course_detail",
                "confidence": 0.96,
                "mentioned_entity": {
                    "entity_type": "course",
                    "entity_name": name,
                    "raw_mention": name,
                    "is_explicit": True,
                    "is_correction": "不是舞蹈" in prompt,
                    "confidence": 0.98,
                },
                "requested_attributes": [],
                "needs_live_data": False,
                "clarification_needed": False,
            },
            ensure_ascii=False,
        )


def test_three_turn_state_rewrites_latest_course() -> None:
    """课程纠正后，后续指代必须使用最新实体生成独立检索问题。"""

    store = InMemoryConversationStore()
    model = FakeIntentModel()
    plan_conversation(
        "孩子8岁，想学中国舞进阶班",
        conversation_id="conversation-a",
        store=store,
        model=model,
    )
    plan_conversation(
        "不是舞蹈，是编程项目实践班",
        conversation_id="conversation-a",
        store=store,
        model=model,
    )
    third = plan_conversation(
        "这个课程适合多大孩子？需要什么基础？",
        conversation_id="conversation-a",
        store=store,
        model=model,
    )

    assert third.active_entity is not None
    assert third.active_entity.entity_name == "编程项目实践班"
    assert third.rewritten_query == "编程项目实践班适合多大孩子？需要什么基础？"


def test_different_conversations_are_isolated() -> None:
    """不同 conversation_id 不得共享课程实体。"""

    store = InMemoryConversationStore()
    plan_conversation(
        "中国舞进阶班适合几岁", conversation_id="a", store=store
    )
    other = plan_conversation(
        "这个课程适合几岁", conversation_id="b", store=store
    )

    assert other.active_entity is None
    assert other.rewritten_query == "这个课程适合几岁"


def test_missing_conversation_id_is_stateless() -> None:
    """兼容旧客户端：不传会话 ID 时每轮都按无状态请求处理。"""

    store = InMemoryConversationStore()
    plan_conversation("音乐启蒙班适合几岁", conversation_id=None, store=store)
    follow_up = plan_conversation("这个课程多久", conversation_id=None, store=store)
    assert follow_up.active_entity is None
    assert follow_up.rewritten_query == "这个课程多久"


def test_expired_conversation_does_not_reuse_entity() -> None:
    """超过 TTL 后必须清除旧实体，避免长期错误绑定。"""

    store = InMemoryConversationStore(ttl_seconds=0.01)
    plan_conversation("童声合唱班适合几岁", conversation_id="exp", store=store)
    time.sleep(0.02)
    follow_up = plan_conversation("这个课程多久", conversation_id="exp", store=store)
    assert follow_up.active_entity is None


def test_high_risk_routes_do_not_enter_static_faq() -> None:
    """学情走数据库，尚无工具的实时名额走人工，不能进入静态 FAQ。"""

    store = InMemoryConversationStore()
    learning = plan_conversation(
        "查询课时和出勤", conversation_id="risk", store=store
    )
    seats = plan_conversation(
        "编程项目实践班还有名额吗", conversation_id="risk", store=store
    )
    assert learning.route == "learning_summary"
    assert seats.route == "human_handoff"


def test_class_learning_summary_has_independent_route() -> None:
    """明确班级和周期的聚合统计请求进入班级统计路由。"""

    store = InMemoryConversationStore()
    plan = plan_conversation(
        "统计舞蹈一班 2026年8月的出勤率",
        conversation_id="class-summary",
        store=store,
    )

    assert plan.route == "class_learning_summary"
    assert plan.intent_result.intent.value == "class_learning_summary"
    assert plan.intent_result.needs_live_data is True
    assert plan.intent_result.clarification_needed is False
    assert plan.active_entity is not None
    assert plan.active_entity.entity_name == "CLASS_DANCE_01"


def test_class_learning_summary_without_period_enters_clarification() -> None:
    """班级统计没有周期时不能直接进入数据库查询分支。"""

    store = InMemoryConversationStore()
    plan = plan_conversation(
        "舞蹈二班缺勤最多的学员有哪些",
        conversation_id="class-summary-missing-period",
        store=store,
    )

    assert plan.intent_result.intent.value == "class_learning_summary"
    assert plan.intent_result.clarification_needed is True
    assert plan.route == "clarification"


def test_personal_learning_summary_route_is_not_changed() -> None:
    """个人学员的动态课时查询仍使用原有学情路由。"""

    store = InMemoryConversationStore()
    plan = plan_conversation(
        "查询 L1001 的剩余课时",
        conversation_id="personal-summary",
        store=store,
    )

    assert plan.route == "learning_summary"
    assert plan.intent_result.intent.value == "learning_summary"


def test_service_rules_questions_use_dedicated_route() -> None:
    """静态请假、调课和安全规则应进入服务规则 Assistant。"""

    store = InMemoryConversationStore()
    leave = plan_conversation("孩子生病请假后可以补课吗", conversation_id="leave", store=store)
    schedule = plan_conversation("课程可以调到其他时间吗", conversation_id="schedule", store=store)
    safety = plan_conversation("孩子在课堂上受伤了怎么办", conversation_id="safety", store=store)

    assert leave.route == "service_rules"
    assert schedule.route == "service_rules"
    assert safety.route == "service_rules"
