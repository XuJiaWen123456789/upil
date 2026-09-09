"""阶段 14-C-4：班级学情统计接入 LangGraph 的回归测试。

+这些测试验证从“结构化会话规划”进入 LangGraph 班级统计节点后的完整闭环：
+权限由节点再次校验，统计数字由隔离数据库计算，结果由固定路由返回。

本文件刻意不调用真实大模型、RAGFlow 或 DSH。班级出勤率、完课率和缺勤
TOP5 属于可审计的动态业务事实，不能交给生成式模型重新计算；后续如果
要生成报表，也只能把脱敏后的聚合结果交给 A2A/DSH 做排版增强。
"""

from datetime import date

from backend.app.graph import conversation_graph
from backend.app.services.access_control import AccessContext
from backend.app.services.conversation_state import (
    InMemoryConversationStore,
    plan_conversation,
)
from backend.app.services.seed import seed_demo_data
from tests.test_database import make_session


PERIOD_START = date(2026, 8, 1)
PERIOD_END = date(2026, 8, 31)


def _planned_class_state(session, message: str, *, actor_role: str, actor_user_id: str):
    """把真实会话规划结果转换成 LangGraph 可执行状态。

    入口层在生产环境还会注入认证上下文；测试这里显式传入演示身份，
    目的是验证“路由规划 → 图节点 → 数据库统计”的边界，而不是模拟 JWT。
    """

    plan = plan_conversation(
        message,
        conversation_id="graph-class-learning-test",
        store=InMemoryConversationStore(),
    )
    return plan, {
        "message": message,
        "route": plan.route,
        "conversation_id": plan.conversation_id,
        "intent_result": plan.intent_result,
        "active_entity": plan.active_entity,
        "rewritten_query": plan.rewritten_query,
        "recognition_source": plan.recognition_source.value,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "class_id": plan.class_id,
        "class_name": plan.class_name,
        "period_start": plan.period_start,
        "period_end": plan.period_end,
        "low_balance_threshold": plan.low_balance_threshold,
        "session": session,
    }


def test_teacher_class_summary_runs_through_langgraph() -> None:
    """授课教师可以通过班级统计路由得到确定性聚合结果。"""

    with make_session() as session:
        seed_demo_data(session)
        message = "统计舞蹈一班2026年8月的出勤率、完课率和缺勤TOP5"
        plan, state = _planned_class_state(
            session, message, actor_role="teacher", actor_user_id="T1001"
        )

        assert plan.route == "class_learning_summary"
        result = conversation_graph.invoke(state)

        assert result["route"] == "class_learning_summary"
        assert result["provider"] == "database"
        assert "舞蹈一班" in result["answer"]
        assert "完课率：56.94%" in result["answer"]
        assert "出勤率：57.75%" in result["answer"]
        assert "舞蹈演示学员3" in result["answer"]
        assert "低课时学员" in result["answer"]
        assert "未登记考勤：1条" in result["answer"]
        assert "缺失课时账户：1人" in result["answer"]


def test_admin_class_summary_uses_authorized_scope() -> None:
    """授权校区管理员可以读取班级聚合统计。"""

    with make_session() as session:
        seed_demo_data(session)
        _, state = _planned_class_state(
            session,
            "统计舞蹈一班2026年8月的完课率",
            actor_role="admin",
            actor_user_id="A1001",
        )
        result = conversation_graph.invoke(state)

        assert result["route"] == "class_learning_summary"
        assert result["provider"] == "database"
        assert "有效学员：12人" in result["answer"]


def test_parent_cannot_enter_class_summary_data_path() -> None:
    """家长不能通过修改请求文本读取包含多名学员的班级数据。"""

    with make_session() as session:
        seed_demo_data(session)
        _, state = _planned_class_state(
            session,
            "统计舞蹈一班2026年8月的出勤率",
            actor_role="parent",
            actor_user_id="P1001",
        )
        result = conversation_graph.invoke(state)

        assert result["route"] == "class_learning_summary"
        assert result["provider"] == "database"
        assert result["answer"] == "班级学情统计仅向已授权的教师或管理员开放。"


def test_class_summary_without_period_stops_at_clarification() -> None:
    """没有统计周期时先澄清，不能把当前日期或默认月份写入查询。"""

    with make_session() as session:
        seed_demo_data(session)
        plan, state = _planned_class_state(
            session,
            "舞蹈二班缺勤最多的学员有哪些",
            actor_role="teacher",
            actor_user_id="T1002",
        )

        assert plan.route == "clarification"
        assert plan.period_start is None
        assert plan.period_end is None
        result = conversation_graph.invoke(state)

        assert result["route"] == "clarification"
        assert result["provider"] == "workflow"
        assert "具体课程、校区或业务问题" in result["answer"]


def test_unknown_class_never_becomes_database_query() -> None:
    """未知班级不允许猜测成现有班级，也不能进入统计工具。"""

    with make_session() as session:
        seed_demo_data(session)
        plan, state = _planned_class_state(
            session,
            "统计芭蕾舞班2026年8月的出勤率",
            actor_role="teacher",
            actor_user_id="T1001",
        )

        assert plan.class_id is None
        assert plan.route == "clarification"
        result = conversation_graph.invoke(state)
        assert result["route"] == "clarification"
        assert result["provider"] == "workflow"


def test_personal_learning_summary_route_remains_independent() -> None:
    """个人课时问题仍走 learning_summary，不误用班级聚合统计。"""

    with make_session() as session:
        seed_demo_data(session)
        plan = plan_conversation(
            "查询L1001的剩余课时",
            conversation_id="personal-learning-test",
            store=InMemoryConversationStore(),
        )

        assert plan.route == "learning_summary"


def test_class_summary_does_not_call_a2a_or_ragflow() -> None:
    """班级统计核心链路不依赖 A2A/DSH 或 RAGFlow 才能得到指标。"""

    class ExplodingA2AClient:
        def analyze(self, *args, **kwargs):
            raise AssertionError("班级统计不应调用 A2A/DSH")

    with make_session() as session:
        seed_demo_data(session)
        _, state = _planned_class_state(
            session,
            "统计舞蹈一班2026年8月的出勤率",
            actor_role="teacher",
            actor_user_id="T1001",
        )
        # 即使上游错误地打开学情 A2A 开关，班级统计节点也不应读取它。
        state["a2a_learning_enabled"] = True
        state["a2a_learning_client"] = ExplodingA2AClient()
        result = conversation_graph.invoke(state)

        assert result["provider"] == "database"
        assert "完课率：56.94%" in result["answer"]
        assert "a2a_status" not in result


def test_invalid_period_cannot_reach_class_summary_node() -> None:
    """非法日期只进入澄清，不向数据库传递反向或非法时间范围。"""

    with make_session() as session:
        seed_demo_data(session)
        plan, state = _planned_class_state(
            session,
            "统计舞蹈一班2026年2月31日的出勤率",
            actor_role="teacher",
            actor_user_id="T1001",
        )

        assert plan.route == "clarification"
        assert plan.period_start is None
        assert plan.period_end is None
        result = conversation_graph.invoke(state)
        assert result["route"] == "clarification"
