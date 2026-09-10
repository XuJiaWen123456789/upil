"""LangGraph 对话工作流。

当前版本实现最小可运行闭环：Supervisor 意图分类后，将请求交给 FAQ、
学情分析或人工转接节点。节点先保持进程内运行，后续可将学情分析节点
替换为 A2A 远程调用，而不改变上层路由契约。

本文件中的注释重点说明“业务边界为什么存在”，而不仅是重复 Python
语法。教育机构的公开咨询、个人学情和班级统计具有不同的数据敏感等级，
因此它们必须在工作流层面分流，不能让一个通用 Agent 直接访问所有数据。
"""

import calendar
import hashlib
import re
from datetime import date, timedelta
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.services.access_control import AccessContext
from backend.app.schemas import AgentResponse, SourceReference
from backend.app.services.faq import answer_faq_result
from backend.app.services.service_rules import answer_service_rules_result
from backend.app.tools.business_tools import execute_learning_snapshot_via_registry
from backend.app.conversation_understanding import (
    CLASS_ALIASES,
    EntityReference,
    EntityType,
    IntentResult,
    normalize_class_name,
)
from backend.app.integrations.a2a_client import A2ALearningClient
from backend.app.learning_contracts import LearningSummary
from backend.app.services.learning_reports import (
    ReportPeriodResolutionError,
    build_learning_report_snapshot,
)
from backend.app.services.report_tasks import (
    ReportTaskError,
    complete_report_task,
    create_report_task,
    fail_report_task,
    list_report_artifacts,
    mark_report_task_running,
)
from backend.app.tools.class_learning_tools import query_class_learning_summary
from backend.app.class_learning_contracts import ClassLearningSummary


RouteName = Literal[
    "faq",
    "service_rules",
    "learning_summary",
    "class_learning_summary",
    "learning_report",
    "human_handoff",
    "clarification",
]
# 路由名称是工作流内部的稳定契约，SSE 完成事件也会返回它。


class ConversationState(TypedDict, total=False):
    """LangGraph 节点之间传递的最小会话状态。

    状态不是数据库模型，也不是把整个聊天记录塞进节点的“共享内存”。
    这里只保留路由、必要实体、已授权的业务上下文和追踪字段，避免知识
    正文、密钥、原始隐私数据在节点之间无边界扩散。生产环境还应结合
    Checkpointer 对状态做租户隔离、过期清理和审计。
    """

    message: str
    # 权限上下文必须由 HTTP 认证边界或可信内部调用方注入，图内不解析凭据。
    access_context: AccessContext
    learner_id: str | None
    session: Session
    conversation_id: str | None
    intent_result: IntentResult
    active_entity: EntityReference | None
    rewritten_query: str
    recognition_source: str
    # HTTP 请求追踪 ID 由入口生成，用于串联 LangGraph 与业务工具调用。
    request_id: str
    # 功能开关和客户端由应用入口注入；默认缺失表示沿用数据库摘要。
    a2a_learning_enabled: bool
    a2a_learning_client: A2ALearningClient | None
    a2a_status: str
    a2a_task_id: str
    a2a_correlation_id: str
    # 主系统报告任务 ID 与远程 A2A task_id 分离，便于分别审计业务和执行链路。
    report_task_id: str
    # 班级统计节点只保存已白名单化的班级 ID 和已解析的日期范围。
    class_id: str | None
    class_name: str | None
    period_start: date | None
    period_end: date | None
    low_balance_threshold: int
    route: RouteName
    answer: str
    provider: str
    sources: list[SourceReference]


def classify_intent(state: ConversationState) -> dict[str, Any]:
    """根据关键词完成演示版意图分类。

    生产版本可替换为结构化模型调用，但输出仍应限制在 RouteName
    允许的集合内，防止模型产生不可执行的路由名称。路由白名单同时是
    安全边界：模型不能通过返回自定义字符串来触发任意工具或内部节点。
    """

    # SSE 入口完成结构化规划后会携带受控 route；同步旧调用方未提供时才
    # 使用关键词基线，保证迁移期间向后兼容。
    return {"route": state.get("route") or classify_route(state["message"])}


def classify_route(message: str) -> RouteName:
    """复用 Supervisor 的纯路由逻辑，供同步图和 SSE 流式路径共同调用。

    这是迁移期间保留的确定性基线，不等同于完整的自然语言理解。对于
    课时、考勤等动态数据，宁可进入受控的学情链路，也不能把问题降级为
    静态 FAQ；静态规则则交给专用 Assistant，避免不同知识库互相污染。
    """

    if any(keyword in message for keyword in ("人工", "投诉", "争议", "不满意")):
        route: RouteName = "human_handoff"
    elif any(keyword in message for keyword in ("课时", "消课", "出勤", "考勤", "缺勤")):
        route = "learning_summary"
    elif any(keyword in message for keyword in ("请假", "补课", "调课", "调到其他时间", "换个时间", "延期", "顺延", "过期", "退费", "退款", "受伤", "过敏")):
        # 静态服务规则进入专用 Assistant，避免与公开课程知识混用。
        route = "service_rules"
    else:
        route = "faq"
    return route


def answer_faq(state: ConversationState) -> dict[str, Any]:
    """调用 FAQ 服务，并把来源和提供方写入工作流状态。

    FAQ 只适合公开、相对稳定的课程和服务说明。它不应承担剩余课时、
    班级空位或退款金额等动态事实；这些事实必须由对应业务系统确认。
    """

    result: AgentResponse = answer_faq_result(
        state.get("rewritten_query") or state["message"]
    )
    return {
        "answer": result.answer,
        "provider": result.provider,
        "sources": result.sources,
    }


def answer_learning_summary(state: ConversationState) -> dict[str, Any]:
    """返回学情分析智能体的演示摘要。

    当前已改为调用数据库查询服务。数据库连接、身份认证等基础设施异常
    会转换为用户可理解的提示，详细异常应由服务端日志记录而不是通过 SSE 泄露。
    这里的“数据库优先”不是为了绕开大模型，而是为了保证课时、消课和
    出勤等可核验事实不会因模型幻觉变成对家长的错误承诺。
    """

    context = state.get("access_context")
    if context is None:
        return {"answer": "当前用户身份无效，请重新登录后再查询。", "provider": "workflow"}
    if context.role == "parent" and not state.get("learner_id"):
        return {"answer": "为了保护学员信息，请先提供已绑定的学员编号。", "provider": "database"}

    session = state.get("session")
    learner_id = state.get("learner_id")
    if session is None or learner_id is None:
        return {"answer": "当前缺少学情查询所需的会话信息，请转人工客服处理。", "provider": "database"}

    try:
        tool_result = execute_learning_snapshot_via_registry(
            session=session,
            context=context,
            learner_id=learner_id,
            request_id=state.get("request_id"),
            actor_role=context.role,
        )
    except SQLAlchemyError:
        # 不向用户暴露数据库连接、表名或 SQL 细节，避免扩大信息泄露面。
        return {"answer": "学情数据服务暂时不可用，请稍后重试或转人工客服。", "provider": "database"}

    if tool_result.status != "success":
        # denied、not_implemented 和 failed 都不允许模型继续猜测动态数据。
        if tool_result.status == "denied":
            return {
                "answer": "暂未找到对应的学员数据，或当前账号无权访问该学员，请核对后转人工确认。",
                "provider": "database",
            }
        return {
            "answer": "学情数据服务暂时不可用，请稍后重试或转人工客服。",
            "provider": "database",
        }

    data = tool_result.data
    profile = data["profile"]
    balance = data["balance"]
    attendance_data = data["attendance"]
    if not isinstance(profile, dict) or not isinstance(balance, dict) or not isinstance(attendance_data, dict):
        # 工具契约异常时宁可降级，也不把不完整结构拼接成用户可见事实。
        return {
            "answer": "学情数据服务返回结果无法校验，请转人工客服处理。",
            "provider": "database",
        }

    attendance = f"{attendance_data['attendance_rate']:.0%}"
    database_answer = (
        f"{profile['learner_name']}当前剩余课时 {balance['remaining_hours']} 节，"
        f"累计消课 {balance['consumed_hours']} 节，近期出勤率 {attendance}，"
        f"近期缺勤 {attendance_data['absent_lessons']} 次。以上数据来自受权限保护的学情数据库。"
    )

    # A2A 只能在权限校验和结构化工具查询成功后运行。默认关闭时完全保留
    # 原有数据库摘要；远程增强失败时也返回可信数据库结果，不让模型猜测。
    # 这体现“增强失败可降级”：远程智能体负责解释和建议，不能替代本地
    # 权限判断，也不能成为动态数据的唯一事实来源。
    if not state.get("a2a_learning_enabled"):
        return {"answer": database_answer, "provider": "database"}

    a2a_client = state.get("a2a_learning_client")
    if a2a_client is None:
        return {
            "answer": database_answer,
            "provider": "database",
            "a2a_status": "failed",
        }

    try:
        # 工具层字典必须再次通过 LearningSummary 契约，禁止把任意响应交给子节点。
        snapshot = LearningSummary.model_validate(data)
        a2a_result = a2a_client.analyze(
            snapshot,
            request_id=state.get("request_id") or "req_internal_a2a",
        )
    except Exception:
        # A2A 属于增强能力，异常细节应写服务端日志；用户仍可得到可信基础摘要。
        return {
            "answer": database_answer,
            "provider": "database",
            "a2a_status": "failed",
        }

    task_fields = {
        "a2a_status": a2a_result.status,
        "a2a_task_id": a2a_result.task_id,
        "a2a_correlation_id": a2a_result.correlation_id,
    }
    if a2a_result.status == "completed" and len(a2a_result.artifacts) == 1:
        # 基础动态事实仍来自本地权限数据；A2A Artifact 只补充分析与建议。
        return {
            "answer": f"{database_answer}\n\n{a2a_result.artifacts[0].content}",
            "provider": a2a_client.provider,
            **task_fields,
        }

    return {
        "answer": f"{database_answer} 学情分析增强服务暂时不可用，已返回基础查询结果。",
        "provider": "database",
        **task_fields,
    }


def answer_class_learning_summary(state: ConversationState) -> dict[str, Any]:
    """返回教师或管理员可见的班级级学情统计。

    班级统计和家长查询本人学员是两条不同的权限链路：班级统计会同时
    触及多名学员的出勤和课时信息，因此不能复用 answer_learning_summary，
    也不能把家长提交的 learner_id 当作班级范围。这里的班级、日期和阈值
    均来自会话规划层的结构化字段，节点不再从自然语言中自行猜测 SQL 参数。

    统计数字由后端工具确定性计算，LLM、RAGFlow 和 A2A/DSH 都不参与
    核心指标计算。这样即使模型服务超时或远程智能体不可用，教师仍不会
    看到一组无法复核的“看起来合理”的出勤率。后续若需要生成运营报告，
    只能在本节点得到可信结果后，对脱敏聚合结果调用 A2A/DSH 排版。
    """

    context = state.get("access_context")
    if context is None:
        return {
            "answer": "当前用户身份无效，请重新登录后再查询。",
            "provider": "workflow",
        }
    role = context.role
    if role not in {"teacher", "admin"}:
        # 家长只允许查询本人绑定学员，不能通过修改 class_id 读取全班数据。
        return {
            "answer": "班级学情统计仅向已授权的教师或管理员开放。",
            "provider": "database",
        }

    session = state.get("session")
    class_id = state.get("class_id")
    period_start = state.get("period_start")
    period_end = state.get("period_end")
    if session is None or not class_id or period_start is None or period_end is None:
        # 缺少任一关键参数都不能“猜一个默认月份”继续查询，避免报表范围
        # 与用户意图不一致；正常入口会在会话规划阶段先进入 clarification。
        return {
            "answer": "请补充具体班级和统计周期，例如“统计舞蹈一班2026年8月的出勤率”。",
            "provider": "workflow",
        }

    try:
        summary = query_class_learning_summary(
            session=session,
            context=context,
            class_id=class_id,
            period_start=period_start,
            period_end=period_end,
            low_balance_threshold=state.get("low_balance_threshold", 5),
        )
    except (SQLAlchemyError, ValueError):
        # 数据库和参数错误统一转换为安全提示；服务端日志应记录 request_id
        # 和异常堆栈，SSE 不应暴露表名、SQL 或内部连接信息。
        return {
            "answer": "班级学情统计暂时不可用，请检查统计周期后重试或转人工客服。",
            "provider": "database",
        }

    if summary is None:
        # 工具统一隐藏“班级不存在”和“当前身份无权访问”的差异，节点也
        # 不把 class_id 原样回显给用户，降低班级存在性枚举风险。
        return {
            "answer": "暂未找到可访问的班级学情数据，请核对授权范围后重试。",
            "provider": "database",
        }

    # 第二次契约校验是编排层门禁：即使未来替换了数据库适配器，也不能让
    # 一个不完整的对象直接进入客服回答或后续脱敏报表链路。
    try:
        validated = ClassLearningSummary.model_validate(summary.model_dump())
    except Exception:
        return {
            "answer": "班级学情统计结果无法校验，请转人工客服处理。",
            "provider": "database",
        }

    def format_learner(metric: Any) -> str:
        """按固定字段生成内部工作人员可读的学员统计行。"""

        # 这里展示姓名和编号是因为当前节点只面向已授权内部角色；如果把
        # 结果送往 A2A/DSH，应先使用独立脱敏 DTO，不能复用这段文本。
        return (
            f"{metric.learner_name}（{metric.learner_id}，"
            f"缺勤{metric.absent_lessons}次，剩余课时"
            f"{metric.remaining_hours if metric.remaining_hours is not None else '未知'}节）"
        )

    absence_text = "、".join(format_learner(metric) for metric in validated.absence_top5)
    if not absence_text:
        absence_text = "暂无缺勤记录"

    low_balance_text = "、".join(format_learner(metric) for metric in validated.low_balance_learners)
    if not low_balance_text:
        low_balance_text = "暂无低课时学员"

    period_text = f"{validated.period_start.isoformat()} 至 {validated.period_end.isoformat()}"
    answer = (
        f"{validated.class_name}（{validated.course_name}）{period_text}学情统计：\n"
        f"- 有效学员：{validated.enrolled_learners}人\n"
        f"- 计划课次：{validated.scheduled_lessons}次\n"
        f"- 完课率：{validated.completion_rate:.2%}\n"
        f"- 出勤率：{validated.attendance_rate:.2%}\n"
        f"- 缺勤TOP5：{absence_text}\n"
        f"- 低课时学员（剩余课时≤{validated.low_balance_threshold}节）：{low_balance_text}\n"
        f"- 未登记考勤：{validated.unmarked_records}条；缺失课时账户：{validated.missing_hour_accounts}人\n\n"
        "说明：完课率按出勤课次除以应登记考勤记录计算；出勤率按出勤课次除以已登记考勤记录计算；请假和未登记记录不计入出勤分子。"
    )
    return {"answer": answer, "provider": "database"}


def answer_learning_report(state: ConversationState) -> dict[str, Any]:
    """生成家长学情报告，并持久化主任务和安全 Markdown 产物。

    主服务负责身份、周期、权限、统计和脱敏；A2A 子节点只能根据脱敏聚合
    快照组织报告文本。任何一步失败都不得使用模型猜测学员动态数据。
    报告属于可追踪的长任务，所以采用 ReportTask 管理状态，而不是把一次
    HTTP 请求当作任务生命周期；这样便于幂等、重试、查询进度和审计。
    """

    context = state.get("access_context")
    if context is None or context.role != "parent":
        return {
            "answer": "当前学情报告入口仅支持已登录家长查询本人绑定的学员。",
            "provider": "workflow",
        }
    learner_id = state.get("learner_id")
    if not learner_id:
        return {
            "answer": "为了保护学员信息，请先提供已绑定的学员编号，并说明报告周期。",
            "provider": "workflow",
        }
    session = state.get("session")
    if session is None:
        return {
            "answer": "当前缺少生成学情报告所需的会话信息，请稍后重试。",
            "provider": "database",
        }

    requester_id = context.user_id
    try:
        snapshot = build_learning_report_snapshot(
            session,
            context,
            learner_id,
            state.get("rewritten_query") or state["message"],
        )
    except ReportPeriodResolutionError:
        # 周期不明确时不创建任务，避免后台静默选择错误的统计范围。
        return {
            "answer": "请说明报告周期，例如上个月、本月、最近30天或具体起止日期。",
            "provider": "workflow",
        }
    except SQLAlchemyError:
        session.rollback()
        return {
            "answer": "学情数据服务暂时不可用，未生成报告，请稍后重试。",
            "provider": "database",
        }

    if snapshot is None:
        # 学员不存在和无访问权限使用同一提示，防止通过响应差异枚举学员。
        return {
            "answer": "暂未找到可访问的学员数据，请核对绑定关系后再试。",
            "provider": "database",
        }

    request_id = state.get("request_id") or f"req_{uuid4().hex}"
    report_task_id = _report_task_id(
        request_id=request_id,
        requester_id=requester_id,
        learner_ref=snapshot.learner_ref,
        period_start=snapshot.period.period_start.isoformat(),
        period_end=snapshot.period.period_end.isoformat(),
    )
    scope = {
        "report_scope": snapshot.report_scope,
        # 持久化任务只保存不可逆引用，不保存原始 learner_id。
        "learner_ref": snapshot.learner_ref,
        "period_start": snapshot.period.period_start.isoformat(),
        "period_end": snapshot.period.period_end.isoformat(),
        "period_type": snapshot.period.period_type,
    }
    metrics = [
        "attendance_rate",
        "attendance_breakdown",
        "lesson_balance",
        "published_progress",
    ]

    try:
        task = create_report_task(
            session,
            task_id=report_task_id,
            requester_id=requester_id,
            task_type="parent_learning_report",
            scope=scope,
            metrics=metrics,
            template_version="learning-report-v1",
        )
        # pending 必须先提交，确保远程调用期间主服务崩溃时仍可审计任务。
        session.commit()
    except (SQLAlchemyError, ReportTaskError):
        session.rollback()
        return {
            "answer": "报告任务创建失败，未生成报告，请稍后重试。",
            "provider": "database",
        }

    # 相同请求 ID 的重复提交复用已有终态，避免重复调用远程智能体。
    if task.status == "completed":
        artifacts = list_report_artifacts(session, report_task_id)
        if len(artifacts) == 1:
            return {
                "answer": artifacts[0].content,
                "provider": "report_cache",
                "report_task_id": report_task_id,
                "a2a_status": "completed",
            }
    if task.status in {"failed", "cancelled"}:
        return {
            "answer": "本次报告任务未能完成，请重新发起请求或转人工客服处理。",
            "provider": "workflow",
            "report_task_id": report_task_id,
            "a2a_status": "failed",
        }
    if task.status == "running":
        return {
            "answer": "本次学情报告正在生成，请稍后使用任务编号查询结果。",
            "provider": "workflow",
            "report_task_id": report_task_id,
            "a2a_status": "working",
        }

    try:
        mark_report_task_running(session, report_task_id)
        session.commit()
    except (SQLAlchemyError, ReportTaskError):
        session.rollback()
        return {
            "answer": "报告任务暂时无法执行，请稍后重试。",
            "provider": "database",
            "report_task_id": report_task_id,
            "a2a_status": "failed",
        }

    a2a_client = state.get("a2a_learning_client")
    if not state.get("a2a_learning_enabled") or a2a_client is None:
        _fail_report_safely(session, report_task_id, "A2A 报告服务未启用或配置无效")
        return {
            "answer": "学情报告生成服务暂时不可用，请稍后重试或转人工客服。",
            "provider": "workflow",
            "report_task_id": report_task_id,
            "a2a_status": "failed",
        }

    try:
        result = a2a_client.generate_report(snapshot, request_id=request_id)
        task_fields = {
            "report_task_id": report_task_id,
            "a2a_status": result.status,
            "a2a_task_id": result.task_id,
            "a2a_correlation_id": result.correlation_id,
        }
        # 客户端校验之外再执行编排层门禁，防止替代实现绕过质量与产物约束。
        if (
            result.status != "completed"
            or result.quality is None
            or not result.quality.passed
            or len(result.artifacts) != 1
        ):
            _fail_report_safely(session, report_task_id, result.message)
            return {
                "answer": "学情报告生成失败，未展示不完整结果，请稍后重试或转人工客服。",
                "provider": a2a_client.provider,
                **task_fields,
            }

        artifact = result.artifacts[0]
        if (
            artifact.name != "learning-report.md"
            or snapshot.learner_ref in artifact.content
            or learner_id in artifact.content
        ):
            raise ReportTaskError("报告产物名称或隐私字段校验失败")

        complete_report_task(
            session,
            report_task_id,
            artifact_id=artifact.artifact_id,
            artifact_name=artifact.name,
            content=artifact.content,
        )
        session.commit()
        return {
            "answer": artifact.content,
            "provider": a2a_client.provider,
            **task_fields,
        }
    except Exception:
        # 不把远程异常、响应正文、连接地址或数据库细节回传给家长。
        session.rollback()
        _fail_report_safely(session, report_task_id, "A2A 报告调用或产物安全校验失败")
        return {
            "answer": "学情报告生成失败，未展示不可信结果，请稍后重试或转人工客服。",
            "provider": a2a_client.provider,
            "report_task_id": report_task_id,
            "a2a_status": "failed",
        }


def _report_task_id(
    *,
    request_id: str,
    requester_id: str,
    learner_ref: str,
    period_start: str,
    period_end: str,
) -> str:
    """根据请求和报告范围生成不含业务主键的幂等任务 ID。"""

    material = "|".join(
        (request_id, requester_id, learner_ref, period_start, period_end)
    )
    return f"report_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"


def _fail_report_safely(session: Session, task_id: str, message: str) -> None:
    """尽力保存失败终态；持久化故障不能覆盖原始安全降级回答。"""

    try:
        fail_report_task(session, task_id, message)
        session.commit()
    except (SQLAlchemyError, ReportTaskError):
        session.rollback()


def answer_service_rules(state: ConversationState) -> dict[str, Any]:
    """调用服务规则 Assistant，处理请假、退费、安全和异常规则。

    服务规则属于比公开 FAQ 更严格的业务边界，但仍然是静态政策说明；
    具体订单金额、实时课时和责任认定不能由该节点自行推断，超出资料的
    问题应由识别层或回答层进入人工兜底。
    """

    result: AgentResponse = answer_service_rules_result(
        state.get("rewritten_query") or state["message"]
    )
    return {
        "answer": result.answer,
        "provider": result.provider,
        "sources": result.sources,
    }


def answer_human_handoff(state: ConversationState) -> dict[str, str]:
    """生成转人工提示，正式版本应在这里创建客服队列任务。

    当前演示只返回安全提示，不宣称工单已经创建。生产实现应在此接入
    客服工单系统，并返回真实的工单编号和可追踪状态。
    """

    return {
        "answer": "已识别为需要人工协助的问题。演示阶段先记录转人工意图，正式版本将进入人工客服队列。",
        "provider": "handoff",
    }


def answer_clarification(state: ConversationState) -> dict[str, str]:
    """当实体或意图不足以安全执行时，先请求用户补充必要信息。

    澄清是安全控制的一部分：当用户说“这个课程”但历史实体不唯一，或
    报告缺少统计周期时，继续执行会把错误对象带入检索或数据库查询。
    """

    return {
        "answer": "为了准确回答，请说明你想咨询的具体课程、校区或业务问题。",
        "provider": "workflow",
    }


def route_to_agent(state: ConversationState) -> RouteName:
    """读取分类节点写入的路由，供条件边选择下一个节点。

    条件边只负责“选择已经允许的分支”，不在这里拼接工具参数，也不把
    用户原文直接当作 SQL、文件路径或远程任务参数使用。
    """

    return state["route"]


def build_conversation_graph():
    """构建并编译 uPil 的最小对话图。

    图结构将业务责任显式化：分类节点只决定去向，业务节点负责各自的
    数据访问和回答，END 表示本次工作流已经产生最终结果。班级统计已经
    作为独立的权限和数据契约分支接入，不能复用个人学情节点。
    """

    graph = StateGraph(ConversationState)
    # 节点命名采用“职责 + agent”形式，便于在 LangGraph 调试界面和日志中
    # 快速定位：分类、公开咨询、服务规则、动态学情和人工兜底彼此分工。
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("faq_agent", answer_faq)
    graph.add_node("service_rules_agent", answer_service_rules)
    graph.add_node("learning_summary_agent", answer_learning_summary)
    # 班级统计面向教师/管理员，和家长查询本人学员使用不同的权限边界。
    # 单独注册节点可以在 LangGraph 调试界面中清楚展示“班级聚合查询”路径。
    graph.add_node("class_learning_summary_agent", answer_class_learning_summary)
    graph.add_node("learning_report_agent", answer_learning_report)
    graph.add_node("human_handoff", answer_human_handoff)
    graph.add_node("clarification", answer_clarification)
    # 所有请求先经过 Supervisor 分类，再进入单一业务分支。单一路径可以
    # 避免一次请求同时触发多个业务工具，降低重复扣费、权限串用和结果冲突。
    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_to_agent,
        {
            "faq": "faq_agent",
            "service_rules": "service_rules_agent",
            "learning_summary": "learning_summary_agent",
            "class_learning_summary": "class_learning_summary_agent",
            "learning_report": "learning_report_agent",
            "human_handoff": "human_handoff",
            "clarification": "clarification",
        },
    )
    # 每个分支当前都是一次性响应，后续可在分支内部增加检索或任务节点。
    # FAQ/服务规则与动态学情故意保持独立：静态文本检索不应绕过动态数据
    # 的身份校验，个人学情也不应把隐私字段混入公开咨询上下文。
    graph.add_edge("faq_agent", END)
    graph.add_edge("service_rules_agent", END)
    graph.add_edge("learning_summary_agent", END)
    graph.add_edge("class_learning_summary_agent", END)
    graph.add_edge("learning_report_agent", END)
    graph.add_edge("human_handoff", END)
    graph.add_edge("clarification", END)
    return graph.compile()


conversation_graph = build_conversation_graph()
# 模块加载时编译一次，避免每个请求重复构建工作流。
