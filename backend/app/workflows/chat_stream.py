"""对话 SSE 编排与招生意向旁路。

本模块编排一次对话请求的生命周期，不定义 LangGraph 节点，也不直接注册
HTTP 路由。联系方式先在边界脱敏，主业务规划和报课意向分析再并行消费同一
份受控文本；只有线索领域服务可以接触当前请求中提取出的联系方式原值。
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict
import json
import logging
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.runtime import settings
from backend.app.context import assemble_context
from backend.app.conversations.service import ConversationHistoryService
from backend.app.context.projectors import (
    build_memory_reference_answer,
    project_enrollment_intent,
    project_faq,
)
from backend.app.integrations.minio import MinioMediaStore
from backend.app.memory.chat_memory import (
    handle_explicit_memory_command,
    read_structured_projection,
    write_structured_memory,
)
from backend.app.memory.structured.admission import is_explicit_memory_request
from backend.app.memory.structured.contracts import MemoryCommandResult
from backend.app.memory.conversation import ConversationStore, ConversationSubject, read_snapshot, record_turn
from backend.app.observability import build_decision_event, log_decision_event
from backend.app.schemas import ChatRequest, LeadChatCardResponse
from backend.app.services.access_control import AccessContext
from backend.app.services.conversation_state import plan_conversation
from backend.app.services.enrollment_intent import (
    analyze_enrollment_intent,
    deterministic_enrollment_intent,
    has_explicit_enrollment_decline,
)
from backend.app.services.enrollment_contact_follow_up import resolve_contact_follow_up
from backend.app.services.enrollment_leads import LeadConflictError, apply_enrollment_intent
from backend.app.services.faq import stream_faq_answer
from backend.app.services.lead_contacts import (
    ContactProtectionError,
    ContactProtector,
    extract_contacts,
)
from backend.app.services.parent_learner_resolution import (
    learner_resolution_answer,
    resolve_parent_learner,
)
from backend.app.services.service_rules import stream_service_rules_answer
from backend.app.workflows.conversation import conversation_graph


logger = logging.getLogger(__name__)


def sse_event(event: str, data: dict) -> str:
    """将结构化事件编码为 SSE 文本块。"""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _memory_command_answer(result: MemoryCommandResult) -> str:
    """把显式记忆命令的内部结果转换为真实场景业务文案。"""

    if result.status == "stored" and result.stored_memory is not None:
        key = result.stored_memory.memory_key
        value = result.stored_memory.memory_value.get("value", "")
        labels = {
            "course_interest": f"孩子喜欢{value}",
            "class_time_preference": f"上课时间偏好是{value}",
            "child_nickname": f"孩子的小名是{value}",
        }
        detail = labels.get(key, "这项偏好")
        return f"好的，我记住了：{detail}。之后为您提供课程建议时，我会参考这项偏好。"
    if result.status == "rejected":
        return (
            "这条信息暂时不适合作为长期偏好保存，可能是临时安排、动态数据、"
            "不确定信息或敏感内容。我仍会根据当前对话继续为您提供帮助。"
        )
    if result.status == "unauthorized":
        return "当前无法确认这项偏好的归属，因此暂不保存；我仍会根据当前对话继续为您提供帮助。"
    return "我暂时无法保存这项偏好，但仍会根据当前对话继续为您提供帮助。"


async def stream_answer(
    request: ChatRequest,
    access_context: AccessContext,
    session: Session,
    store: ConversationStore,
    intent_model=None,
    lead_intent_model=None,
    request_id: str | None = None,
    report_store: MinioMediaStore | None = None,
    *,
    planner: Callable = plan_conversation,
    faq_stream: Callable = stream_faq_answer,
    service_rules_stream: Callable = stream_service_rules_answer,
) -> AsyncIterator[str]:
    """推送 accepted、routed、业务片段、线索卡与 complete 事件。"""

    loop = asyncio.get_running_loop()
    request_started_at = loop.time()
    yield sse_event("status", {"stage": "accepted"})
    await asyncio.sleep(0)

    # 联系方式在任何模型或 RAGFlow 调用前移除；原值只交给加密线索服务。
    contact_extraction = extract_contacts(request.message)
    safe_request = request.model_copy(update={"message": contact_extraction.redacted_text})
    explicit_memory_command = is_explicit_memory_request(safe_request.message)
    conversation_subject = ConversationSubject(
        tenant_id=access_context.tenant_id,
        user_id=access_context.user_id,
        role=access_context.role,
    )
    conversation_ref = safe_request.conversation_id or request_id or f"turn_{uuid4().hex}"
    # 线索卡后的手机号/邮箱回复必须先于普通回答判断，避免被 FAQ 误当成
    # 新会话欢迎语。该门禁只读已有等待授权线索，不会凭联系方式创建线索。
    contact_follow_up = (
        resolve_contact_follow_up(
            session,
            access_context,
            conversation_ref=conversation_ref,
            safe_message=safe_request.message,
            contact_extraction=contact_extraction,
        )
        if (
            access_context.role == "parent"
            and not explicit_memory_command
            # 明确拒绝联系/暂缓试听时，必须让消息继续进入正常对话仲裁与
            # 招生意图旁路，由后者撤回已有线索。否则等待联系方式的状态会
            # 抢先把“不用联系我”误当成联系方式补全轮，导致线索无法撤回。
            and not has_explicit_enrollment_decline(safe_request.message)
        )
        else None
    )
    if contact_follow_up is not None:
        # 联系方式补全轮已经有明确的会话状态，不需要再次经过 Supervisor、
        # FAQ 或模型。否则普通规划器可能把“手机号/同意”解释成新会话，
        # 既浪费一次模型/检索调用，也会覆盖本轮应使用的专用路由。
        yield sse_event("status", {"stage": "routed", "route": "lead_contact_follow_up"})
        answer_parts: list[str] = []
        for index in range(0, len(contact_follow_up.answer), 12):
            chunk = contact_follow_up.answer[index : index + 12]
            answer_parts.append(chunk)
            yield sse_event("token", {"content": chunk})

        try:
            # 这里只使用脱敏后的消息做确定性证据判断；原始联系方式仅在
            # apply_enrollment_intent 内短暂用于加密，绝不进入普通 Agent。
            lead_result = deterministic_enrollment_intent(safe_request.message)
            lead_card = apply_enrollment_intent(
                session,
                context=access_context,
                conversation_ref=conversation_ref,
                requested_learner_id=safe_request.learner_id,
                context_course_name=None,
                intent=lead_result,
                contact_extraction=contact_extraction,
                protector=ContactProtector.from_settings(settings),
                settings=settings,
            )
        except (LeadConflictError, ContactProtectionError, SQLAlchemyError):
            session.rollback()
            logger.warning("lead_sidecar_failed reason=storage_or_protection")
            lead_card = None

        if lead_card is not None:
            card_data = LeadChatCardResponse.model_validate(asdict(lead_card))
            yield sse_event("lead", card_data.model_dump())
        try:
            # 联系方式补全轮也要留下脱敏后的会话痕迹，保证下一轮仍能识别
            # 当前线索上下文；这里不写长期结构化记忆。
            safe_answer = extract_contacts("".join(answer_parts)).redacted_text
            record_turn(
                store,
                conversation_id=safe_request.conversation_id,
                subject=conversation_subject,
                user_message=safe_request.message,
                assistant_answer=safe_answer,
                recent_turn_limit=settings.conversation_recent_turns,
                summary_token_budget=settings.conversation_summary_token_budget,
                context_token_budget=settings.conversation_context_token_budget,
            )
        except Exception:
            logger.warning("conversation_memory_write_failed reason=storage_or_policy")
        try:
            ConversationHistoryService(session).persist_turn(
                safe_request.conversation_id, access_context, store,
                user_message=safe_request.message, assistant_answer=safe_answer,
            )
        except Exception:
            session.rollback()
            # 消息持久化属于辅助能力，不能把已经生成完成的主回答改成失败；
            # 日志只记录故障类型，不记录任何对话正文。
            logger.warning("conversation_history_write_failed reason=storage_or_database")
        complete_event = {
            "route": "lead_contact_follow_up",
            "provider": "workflow",
            "sources": [],
        }
        if lead_card is not None:
            complete_event["lead_status"] = lead_card.status
        log_decision_event(
            logger,
            build_decision_event(
                request_id=request_id,
                route="lead_contact_follow_up",
                decision=None,
                decision_source="deterministic_guard",
                lead_sidecar_fallback_reason="contact_follow_up_deterministic",
                contact_redaction_applied=bool(
                    contact_extraction.contacts
                    or contact_extraction.has_invalid_contact_candidate
                ),
                total_duration_ms=(loop.time() - request_started_at) * 1000,
            ),
        )
        yield sse_event("complete", complete_event)
        return
    lead_task: asyncio.Task | None = None
    lead_started_at: float | None = None
    if (
        access_context.role == "parent"
        and not explicit_memory_command
        and contact_follow_up is None
    ):
        # 旁路只读脱敏文本且不持有数据库 Session，因此超时取消不会留下写副作用。
        lead_task = asyncio.create_task(
            asyncio.to_thread(
                analyze_enrollment_intent,
                safe_request.message,
                model=lead_intent_model,
            )
        )
        lead_started_at = asyncio.get_running_loop().time()
        await asyncio.sleep(0)

    planning_started_at = loop.time()
    plan = await asyncio.to_thread(
        planner,
        safe_request.message,
        conversation_id=safe_request.conversation_id,
        store=store,
        subject=conversation_subject,
        model=intent_model,
    )
    planning_duration_ms = (loop.time() - planning_started_at) * 1000
    # 家长查看实时学情或生成报告时，优先从当前账号的绑定关系解析孩子。
    # 唯一绑定自动使用；多个绑定必须明确选择；显式越权统一拒绝。这个解析
    # 放在图执行前，保证数据库工具、上下文和最终回答使用同一个有效学员范围。
    effective_learner_id = safe_request.learner_id
    resolution_message: str | None = None
    if (
        access_context.role == "parent"
        and plan.route in {"learning_summary", "learning_report"}
    ):
        resolution = resolve_parent_learner(
            session,
            access_context,
            requested_learner_id=safe_request.learner_id,
            message=safe_request.message,
        )
        if resolution.status == "resolved":
            effective_learner_id = resolution.learner_id
        else:
            effective_learner_id = None
            resolution_message = learner_resolution_answer(resolution)
    # 规划器已经完成路由判定；先把可信路由写入请求上下文，后续 FAQ、
    # 服务规则和 LangGraph 分支都从同一个值读取，避免上下文与执行分支漂移。
    route = plan.route
    snapshot = read_snapshot(
        store,
        conversation_id=safe_request.conversation_id,
        subject=conversation_subject,
    )
    # 长期记忆读取统一经过作用域解析和学员权限校验。这里只接收安全投影，
    # 不让聊天编排直接依赖 ORM，也不把记忆表的主键和版本传播给 Agent。
    structured_memories = read_structured_projection(
        session,
        access_context,
        effective_learner_id,
    )
    context_envelope = assemble_context(
        access_context=access_context,
        request_id=request_id,
        conversation_id=safe_request.conversation_id,
        message=safe_request.message,
        rewritten_query=plan.rewritten_query,
        route=route,
        decision=plan.decision,
        active_entity=plan.active_entity,
        child_age=plan.child_age,
        programming_foundation=plan.programming_foundation,
        class_time_preference=plan.class_time_preference,
        pending_intent=(plan.pending_intent.value if plan.pending_intent else None),
        rolling_summary=snapshot.rolling_summary,
        recent_turns=snapshot.recent_turns,
        structured_memories=structured_memories,
    )
    # Supervisor 对“你还记得孩子的小名吗”这类自然问法可能判为 UNKNOWN。
    # 长期记忆已经按可信身份完成隔离读取，因此在执行 UNKNOWN 澄清前先做一次
    # 白名单字段级匹配。命中后统一按 FAQ 形态返回确定性答案，不调用 RAGFlow，
    # 也不把读取问句误当成新的记忆写入。人工转接和其他有副作用路由不覆盖。
    memory_reference_answer = build_memory_reference_answer(
        safe_request.message,
        context_envelope.structured_memories,
    )
    if (
        memory_reference_answer is not None
        and route in {"faq", "clarification", "small_talk", "out_of_scope"}
    ):
        route = "faq"
    # 所有旁路分析都只拿到同一份受控投影，不共享可写的大字典。
    project_enrollment_intent(context_envelope)
    answer_parts: list[str] = []
    complete_event: dict = {
        "route": route,
        "provider": "workflow",
        "sources": [],
        "recognition_source": plan.recognition_source.value,
    }
    if plan.decision is not None:
        # 完成事件只暴露白名单分类结果，便于前端调试与离线评测；不记录
        # 消息正文、槽位值、学员标识或联系方式。
        complete_event["primary_intent"] = plan.decision.primary_intent.value
        complete_event["secondary_intents"] = [
            intent.value for intent in plan.decision.secondary_intents
        ]
        if plan.decision.unknown_kind is not None:
            complete_event["unknown_kind"] = plan.decision.unknown_kind.value
    if route == "memory":
        yield sse_event("status", {"stage": "routed", "route": route})
        memory_result = handle_explicit_memory_command(
            session,
            access_context,
            safe_request.learner_id,
            safe_request.message,
            conversation_id=safe_request.conversation_id,
            message_id=request_id,
            settings=settings,
        )
        answer = _memory_command_answer(memory_result)
        for index in range(0, len(answer), 12):
            chunk = answer[index : index + 12]
            answer_parts.append(chunk)
            yield sse_event("token", {"content": chunk})
        complete_event.update({
            "provider": "workflow",
            "memory_status": memory_result.status,
        })
    elif route == "faq":
        yield sse_event("status", {"stage": "routed", "route": route})
        provider = "offline"
        sources = []
        # 明确的结构化记忆读取必须优先于 Supervisor 为 UNKNOWN 生成的通用
        # 澄清话术；普通 FAQ 没有命中记忆时仍沿用规划器的确定性回答。
        effective_direct_answer = memory_reference_answer or plan.direct_answer
        if effective_direct_answer is not None:
            # 确定性课程初筛已经得到完整回答时，不再访问 RAGFlow/LLM。这样既
            # 降低延迟，也从根源上避免孤立年龄召回其他课程。用户明确引用
            # 长期偏好时同样由结构化记忆直接回答，避免知识库旧话术否认记忆。
            provider = "workflow"
            for index in range(0, len(effective_direct_answer), 12):
                answer_parts.append(effective_direct_answer[index : index + 12])
                yield sse_event(
                    "token", {"content": effective_direct_answer[index : index + 12]}
                )
        else:
            # FAQ 检索只在课程推荐/时间选择时使用安全的长期偏好投影；
            # 普通校区、规则等问题保持原 Query，避免无关记忆污染检索。
            faq_query = project_faq(context_envelope)["query"]
            async for chunk in faq_stream(faq_query):
                provider = chunk.provider
                sources = chunk.sources
                answer_parts.append(chunk.content)
                yield sse_event("token", {"content": chunk.content})
        complete_event.update({
            "provider": provider,
            "sources": (
                [source.model_dump() for source in sources]
                if settings.expose_sources else []
            ),
        })
    elif route == "service_rules":
        yield sse_event("status", {"stage": "routed", "route": route})
        provider = "offline"
        sources = []
        async for chunk in service_rules_stream(plan.rewritten_query):
            provider = chunk.provider
            sources = chunk.sources
            # 会话历史依赖 answer_parts 持久化完整公开回答。原先这里只向
            # SSE 推送片段，会导致请假、调课等服务规则在刷新后显示为空。
            answer_parts.append(chunk.content)
            yield sse_event("token", {"content": chunk.content})
        complete_event.update({
            "provider": provider,
            "sources": (
                [source.model_dump() for source in sources]
                if settings.expose_sources else []
            ),
        })
    else:
        # 图只接收认证后的权限上下文和规划后的结构化值，不接收联系方式原文。
        result = conversation_graph.invoke({
            "message": safe_request.message,
            "route": route,
            "conversation_id": safe_request.conversation_id,
            "intent_result": plan.intent_result,
            "decision": plan.decision,
            "active_entity": plan.active_entity,
            "rewritten_query": plan.rewritten_query,
            "recognition_source": plan.recognition_source.value,
            "request_id": request_id,
            "report_pdf_enabled": settings.report_pdf_enabled,
            "report_pdf_settings": settings,
            "report_store": report_store,
            "access_context": access_context,
            # 个人学情和报告节点必须使用边界层完成权限解析后的学员。
            # 家长只提交自然语言且仅绑定一个孩子时，effective_learner_id
            # 才是唯一可执行的资源范围；继续传原始请求值会让自动解析结果
            # 丢失，最终错误地提示家长提供学员编号。
            "learner_id": effective_learner_id,
            "class_id": plan.class_id,
            "class_name": plan.class_name,
            "period_start": plan.period_start,
            "period_end": plan.period_end,
            "low_balance_threshold": plan.low_balance_threshold,
            "session": session,
            "context_envelope": context_envelope,
            "learner_resolution_answer": resolution_message,
        })
        yield sse_event("status", {"stage": "routed", "route": result["route"]})
        if result.get("report_task_id"):
            report_status = {"working": "running"}.get(
                result.get("report_status"), result.get("report_status", "pending")
            )
            yield sse_event("status", {
                "stage": "report_task",
                "task_id": result["report_task_id"],
                "status": report_status,
            })
        for chunk in result["answer"]:
            answer_parts.append(chunk)
            yield sse_event("token", {"content": chunk})
            await asyncio.sleep(0)
        complete_event.update({
            "route": result["route"],
            "provider": result.get("provider", "database"),
            "sources": (
                [source.model_dump() for source in result.get("sources", [])]
                if settings.expose_sources else []
            ),
        })
        if result.get("report_task_id"):
            complete_event["report_task_id"] = result["report_task_id"]
        # 只透传图节点写入的固定站内动作；不接受模型或用户消息中的任意 URL。
        if result.get("navigation_path") == "/parent/reports":
            complete_event["navigation_path"] = "/parent/reports"
            complete_event["navigation_label"] = "查看学情报告"

    lead_sidecar_fallback_reason: str | None = None
    if lead_task is not None:
        try:
            # 超时预算从旁路启动时计时，主回答耗时不会为旁路换取额外等待时间。
            elapsed = asyncio.get_running_loop().time() - (lead_started_at or 0)
            remaining = max(0.0, settings.lead_intent_timeout_seconds - elapsed)
            if lead_task.done():
                lead_result = lead_task.result()
            elif remaining > 0:
                lead_result = await asyncio.wait_for(lead_task, timeout=remaining)
            else:
                lead_task.cancel()
                lead_result = deterministic_enrollment_intent(safe_request.message)
                lead_sidecar_fallback_reason = "budget_exhausted"
        except asyncio.TimeoutError:
            lead_task.cancel()
            lead_result = deterministic_enrollment_intent(safe_request.message)
            lead_sidecar_fallback_reason = "timeout"
        except asyncio.CancelledError:
            lead_task.cancel()
            raise
        except Exception:
            lead_result = deterministic_enrollment_intent(safe_request.message)
            lead_sidecar_fallback_reason = "provider_error"
        if lead_sidecar_fallback_reason is None and lead_result.source == "deterministic_fallback":
            lead_sidecar_fallback_reason = (
                "model_not_configured"
                if lead_intent_model is None
                else "invalid_or_provider_fallback"
            )
        try:
            active_course = (
                plan.active_entity.entity_name
                if plan.active_entity is not None
                and plan.active_entity.entity_type.value in {"course", "course_category"}
                else None
            )
            lead_card = apply_enrollment_intent(
                session,
                context=access_context,
                conversation_ref=conversation_ref,
                requested_learner_id=safe_request.learner_id,
                context_course_name=active_course,
                intent=lead_result,
                contact_extraction=contact_extraction,
                protector=ContactProtector.from_settings(settings),
                settings=settings,
            )
            if lead_card is not None:
                card_data = LeadChatCardResponse.model_validate(asdict(lead_card))
                yield sse_event("lead", card_data.model_dump())
                complete_event["lead_status"] = lead_card.status
        except (LeadConflictError, ContactProtectionError, SQLAlchemyError):
            session.rollback()
            logger.warning("lead_sidecar_failed reason=storage_or_protection")
            lead_sidecar_fallback_reason = "storage_or_protection"
    try:
        # 只写入已脱敏的用户消息和公开回答。写入边界再次脱敏，防止未来新增
        # 节点误把联系方式原文拼进回答后污染短期摘要。
        safe_answer = extract_contacts("".join(answer_parts)).redacted_text
        record_turn(
            store,
            conversation_id=safe_request.conversation_id,
            subject=conversation_subject,
            user_message=safe_request.message,
            assistant_answer=safe_answer,
            recent_turn_limit=settings.conversation_recent_turns,
            summary_token_budget=settings.conversation_summary_token_budget,
            context_token_budget=settings.conversation_context_token_budget,
        )
    except Exception:
        # 记忆治理失败不应改变已经完成的主回答；日志不携带消息正文。
        logger.warning("conversation_memory_write_failed reason=storage_or_policy")
    try:
        ConversationHistoryService(session).persist_turn(
            safe_request.conversation_id, access_context, store,
            user_message=safe_request.message, assistant_answer=safe_answer,
        )
    except Exception:
        session.rollback()
        logger.warning("conversation_history_write_failed reason=storage_or_database")
    # 结构化长期记忆允许显式请求，或对低敏感白名单字段执行保守的高置信度
    # 自主判断。写入门面会再次执行权限与敏感检查；失败不改变主回答。
    if route not in {"memory", "lead_contact_follow_up"}:
        write_structured_memory(
            session,
            access_context,
            safe_request.learner_id,
            safe_request.message,
            conversation_id=safe_request.conversation_id,
            message_id=request_id,
            settings=settings,
        )
    log_decision_event(
        logger,
        build_decision_event(
            request_id=request_id,
            route=complete_event["route"],
            decision=plan.decision,
            decision_source=plan.recognition_source.value,
            model_fallback_reason=plan.recognition_fallback_reason,
            lead_sidecar_fallback_reason=lead_sidecar_fallback_reason,
            contact_redaction_applied=bool(
                contact_extraction.contacts
                or contact_extraction.has_invalid_contact_candidate
            ),
            planning_duration_ms=planning_duration_ms,
            total_duration_ms=(loop.time() - request_started_at) * 1000,
        ),
    )
    yield sse_event("complete", complete_event)
