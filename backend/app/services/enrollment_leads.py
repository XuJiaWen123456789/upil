"""试听与报名线索的确定性状态机和持久化服务。

旁路 Agent 只提供有限证据码；本模块负责强度、队列、授权、幂等和状态
迁移。联系方式明文仅在当前调用栈中短暂存在，不进入普通响应或审计元数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.integrations.notifications.outbox import (
    choose_transition_event,
    enqueue_lead_notification,
)
from backend.app.models import EnrollmentLead, LeadFollowUp, Learner, ParentLearner
from backend.app.services.access_control import AccessContext, can_follow_up_lead, can_manage_leads
from backend.app.services.audit import write_audit_log
from backend.app.services.enrollment_intent import EnrollmentIntentResult
from backend.app.services.lead_contacts import (
    ContactExtraction,
    ContactProtectionError,
    ContactProtector,
)


ACTIVE_STATUSES = frozenset({
    "open",
    "awaiting_contact_consent",
    "ready_for_followup",
    "contacted",
    "trial_scheduled",
    "enrolled",
})
CLOSED_STATUSES = frozenset({"closed_won", "closed_lost", "withdrawn"})
HIGH_EVIDENCE = frozenset({
    "explicit_trial_request",
    "explicit_enrollment_request",
    "advisor_contact_request",
})
MEDIUM_EVIDENCE = frozenset({"positive_interest", "trial_process_question"})
LOW_EVIDENCE = frozenset({"request_more_information"})

# 主回答由业务 Agent 生成；涉及隐私授权的话术由后端固定，避免模型改写
# 为诱导性文案，也让前端和自动化测试依赖稳定契约。
CONTACT_CONSENT_PROMPT = (
    "如果您愿意由销售顾问老师继续确认试听或报名安排，请主动提供手机号或邮箱，"
    "并明确同意由销售顾问老师联系您。"
)
CONTACT_RECONSENT_PROMPT = (
    "为保护您的隐私，刚才的联系方式尚未保存。请在同一条消息中重新提供"
    "联系方式，并明确说明同意记录且由销售顾问老师联系。"
)
CONTACT_INVALID_PROMPT = (
    "这个号码格式似乎不正确。请提供11位中国大陆手机号或有效邮箱，"
    "并在同一条消息中明确说明同意由销售顾问老师联系您。"
)
CONTACT_SAVED_PROMPT = "已按您的明确授权安全登记，销售顾问老师将进行后续跟进。"
WITHDRAWN_PROMPT = "已撤回本次试听或报名意向，并清除已保存的联系方式。"
UNKNOWN_COURSE = "待确认课程"


class LeadServiceError(RuntimeError):
    """线索存储暂时不可用或数据违反受控契约。"""


class LeadNotFoundError(LookupError):
    """线索不存在或当前顾问无权读取。"""


class LeadConflictError(RuntimeError):
    """领取、联系方式或跟进状态与当前记录冲突。"""


@dataclass(frozen=True)
class LeadChatCard:
    """家长 SSE 可见的最小投影，不包含证据、队列或联系方式明文。"""

    lead_id: str
    strength: str
    interest_type: str
    status: str
    course_name: str
    contact_masked: str | None
    prompt: str | None


@dataclass(frozen=True)
class LeadPage:
    items: list[EnrollmentLead]
    total: int


def _deduplication_key(
    parent_id: str, learner_id: str | None, course_name: str, interest_type: str
) -> str:
    """生成不暴露业务值的稳定幂等键。"""

    payload = "\x1f".join((parent_id, learner_id or "", course_name, interest_type))
    return sha256(payload.encode("utf-8")).hexdigest()


def _strength_for(
    intent: EnrollmentIntentResult, extraction: ContactExtraction
) -> str | None:
    """模型只提取证据，最终等级由固定规则计算，拒绝拥有最高优先级。"""

    evidence = set(intent.evidence_codes)
    if "explicit_decline" in evidence:
        return None
    if evidence & HIGH_EVIDENCE:
        return "high"
    # 主动提供联系方式且同轮明确授权，本身就是要求顾问跟进的高强度动作。
    if extraction.contacts and "contact_consent" in evidence:
        return "high"
    if evidence & MEDIUM_EVIDENCE:
        return "medium"
    if evidence & LOW_EVIDENCE:
        return "low"
    return None


def _bound_learner_id(
    session: Session, parent_id: str, requested_learner_id: str | None
) -> str | None:
    """只接受数据库中当前仍绑定的孩子，客户端编号不能直接进入线索。"""

    if not requested_learner_id:
        return None
    return session.scalar(
        select(ParentLearner.learner_id).where(
            ParentLearner.parent_id == parent_id,
            ParentLearner.learner_id == requested_learner_id,
        )
    )


def _conversation_lead(
    session: Session, parent_id: str, conversation_ref: str
) -> EnrollmentLead | None:
    return session.scalar(
        select(EnrollmentLead)
        .where(
            EnrollmentLead.parent_id == parent_id,
            EnrollmentLead.conversation_ref == conversation_ref,
            EnrollmentLead.status.in_(ACTIVE_STATUSES),
        )
        .order_by(EnrollmentLead.updated_at.desc(), EnrollmentLead.id.desc())
        .limit(1)
    )


def _card(lead: EnrollmentLead, prompt: str | None) -> LeadChatCard:
    return LeadChatCard(
        lead_id=lead.id,
        strength=lead.strength,
        interest_type=lead.interest_type,
        status=lead.status,
        course_name=lead.course_name,
        contact_masked=lead.contact_masked,
        prompt=prompt,
    )


def apply_enrollment_intent(
    session: Session,
    *,
    context: AccessContext,
    conversation_ref: str,
    requested_learner_id: str | None,
    context_course_name: str | None,
    intent: EnrollmentIntentResult,
    contact_extraction: ContactExtraction,
    protector: ContactProtector,
    settings: Settings,
) -> LeadChatCard | None:
    """把单轮旁路结果应用到线索状态，并在成功后提交当前事务。

    教师消息不参与招生分析。拒绝或撤回只作用于同一家长的当前会话线索；
    正向结果按业务范围复用未关闭记录，conversation_ref 只辅助多轮继承。
    """

    if context.role != "parent":
        return None

    existing = _conversation_lead(session, context.user_id, conversation_ref)
    evidence = set(intent.evidence_codes)
    now = datetime.utcnow()
    if "explicit_decline" in evidence:
        if existing is None:
            return None
        had_contact = existing.contact_ciphertext is not None
        existing.status = "withdrawn"
        existing.contact_type = None
        existing.contact_ciphertext = None
        existing.contact_fingerprint = None
        existing.contact_masked = None
        existing.contact_consent_at = None
        existing.updated_at = now
        write_audit_log(
            session,
            actor_user_id=context.user_id,
            action="lead.withdraw",
            resource_type="enrollment_lead",
            resource_id=existing.id,
            outcome="success",
            metadata={"had_contact": had_contact},
        )
        session.commit()
        return _card(existing, WITHDRAWN_PROMPT)
    if (
        not evidence
        and not contact_extraction.contacts
        and not contact_extraction.has_invalid_contact_candidate
    ):
        # 当前轮既没有意向证据也没有联系方式时不触碰旧线索，避免普通
        # 售后问答反复弹出招生卡片或刷新线索排序。
        return None
    if existing is None and not evidence.intersection(
        HIGH_EVIDENCE | MEDIUM_EVIDENCE | LOW_EVIDENCE
    ):
        # 联系方式和授权只能补全已经存在的意向，不能单独创造业务线索。
        # 同一轮若同时包含明确试听/报名动作则仍可一次完成创建与授权。
        return None

    strength = _strength_for(intent, contact_extraction)
    # "同意，我的手机号是……"这类第二轮消息可能没有重复课程或报名动词，
    # 只有当前会话已存在意向时才继承，不能凭联系方式单独创建陌生线索。
    if strength is None and existing is None:
        return None
    if strength is None:
        strength = existing.strength

    course_name = intent.course_name or context_course_name
    if existing is not None and not course_name:
        course_name = existing.course_name
    course_name = course_name or UNKNOWN_COURSE
    learner_id = _bound_learner_id(session, context.user_id, requested_learner_id)
    if learner_id is None and existing is not None:
        learner_id = existing.learner_id
    interest_type = intent.interest_type
    if interest_type in {"none", "unknown"} and existing is not None:
        interest_type = existing.interest_type
    if interest_type == "none":
        interest_type = "unknown"

    key = _deduplication_key(context.user_id, learner_id, course_name, interest_type)
    scoped_lead = session.scalar(
        select(EnrollmentLead).where(
            EnrollmentLead.deduplication_key == key,
            EnrollmentLead.status.in_(ACTIVE_STATUSES),
        )
    )
    # 同一家长可能先在当前会话形成一条泛化的“想了解编程”线索，又在
    # 另一个会话中已经存在“编程项目实践班试听”线索。当前轮把泛化线索
    # 升级为具体试听时，若直接改写它的幂等键，会撞上数据库中的活动线索
    # 唯一索引，最终导致家长看不到联系方式授权卡。这里优先复用已经存在
    # 的精确业务范围线索；当前会话的泛化线索继续保留为较早的咨询记录，
    # 不伪造“撤回”或“关闭”状态，也不覆盖其中可能存在的历史信息。
    if scoped_lead is not None and (existing is None or scoped_lead.id != existing.id):
        existing = scoped_lead
    lead = existing or scoped_lead
    created = lead is None
    # 状态变化必须在线索字段被更新前留存，用于确定是否生成一次性通知。
    # 只记录枚举和布尔值，不复制联系方式或用户原话。
    previous_strength = lead.strength if lead is not None else None
    previous_contact_authorized = bool(
        lead is not None and lead.contact_ciphertext is not None
    )
    if lead is None:
        lead = EnrollmentLead(
            id=f"lead_{uuid4().hex}",
            deduplication_key=key,
            parent_id=context.user_id,
            learner_id=learner_id,
            course_name=course_name,
            interest_type=interest_type,
            strength=strength,
            destination="advisor_queue" if strength == "high" else "lead_pool",
            status="open",
            conversation_ref=conversation_ref,
            evidence_codes=[],
            created_at=now,
            updated_at=now,
        )
        session.add(lead)
    else:
        lead.deduplication_key = key
        lead.learner_id = learner_id
        lead.course_name = course_name
        lead.interest_type = interest_type
        # 只有明确拒绝才降级；普通后续问句不能把高意向覆盖成低意向。
        ranks = {"low": 1, "medium": 2, "high": 3}
        lead.strength = max((lead.strength, strength), key=ranks.__getitem__)
        lead.destination = "advisor_queue" if lead.strength == "high" else "lead_pool"
        lead.conversation_ref = conversation_ref
        lead.updated_at = now

    lead.evidence_codes = list(dict.fromkeys([*lead.evidence_codes, *intent.evidence_codes]))
    consent = "contact_consent" in evidence
    contact = contact_extraction.contacts[0] if contact_extraction.contacts else None
    prompt: str | None = None
    if lead.strength == "high" and contact is not None and consent:
        lead.contact_type = contact.contact_type
        lead.contact_ciphertext = protector.encrypt(contact)
        lead.contact_fingerprint = protector.fingerprint(contact)
        lead.contact_masked = contact.masked
        lead.contact_consent_at = now
        if lead.status in {"open", "awaiting_contact_consent"}:
            # 更新联系方式不能把顾问已经推进的跟进状态倒退。
            lead.status = "ready_for_followup"
        prompt = CONTACT_SAVED_PROMPT
    elif lead.strength == "high" and lead.contact_ciphertext is None:
        lead.status = "awaiting_contact_consent"
        if contact_extraction.has_invalid_contact_candidate:
            prompt = CONTACT_INVALID_PROMPT
        else:
            prompt = CONTACT_RECONSENT_PROMPT if contact is not None else CONTACT_CONSENT_PROMPT

    try:
        session.flush()
        write_audit_log(
            session,
            actor_user_id=context.user_id,
            action="lead.create" if created else "lead.update",
            resource_type="enrollment_lead",
            resource_id=lead.id,
            outcome="success",
            # 审计只记录受控枚举和布尔值，不能记录联系方式或用户原文。
            metadata={
                "strength": lead.strength,
                "status": lead.status,
                "contact_authorized": lead.contact_ciphertext is not None,
            },
        )
        event_type = choose_transition_event(
            created=created,
            previous_strength=previous_strength,
            previous_contact_authorized=previous_contact_authorized,
            lead=lead,
        )
        if event_type is not None:
            # Outbox 与线索共用本次 commit：要么同时落库，要么同时回滚。
            # 网络投递由后台循环在事务提交后执行，绝不阻塞家长回复。
            enqueue_lead_notification(
                session, settings, lead, event_type=event_type
            )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # 并发命中唯一索引时让调用方使用安全降级，不在未知事务状态下
        # 继续覆盖另一请求刚写入的授权或联系方式。
        raise LeadConflictError("线索正在更新，请稍后重试") from exc
    # 家长聊天只在需要询问授权、确认保存或确认撤回时显示卡片。普通
    # 重复咨询仍更新同一线索，但不会反复弹出没有行动文案的空卡片。
    return _card(lead, prompt) if prompt is not None else None


def list_advisor_leads(
    session: Session,
    context: AccessContext,
    *,
    destination: str | None,
    limit: int,
    offset: int,
) -> LeadPage:
    """只列出未分配或分配给当前销售顾问老师的线索。"""

    if not can_manage_leads(context):
        raise LeadNotFoundError("线索不存在")
    conditions = [
        EnrollmentLead.status != "withdrawn",
        or_(
            EnrollmentLead.assigned_advisor_id.is_(None),
            EnrollmentLead.assigned_advisor_id == context.user_id,
        ),
    ]
    if destination:
        conditions.append(EnrollmentLead.destination == destination)
    total = session.scalar(
        select(func.count()).select_from(EnrollmentLead).where(*conditions)
    ) or 0
    items = list(session.scalars(
        select(EnrollmentLead)
        .where(*conditions)
        .order_by(EnrollmentLead.updated_at.desc(), EnrollmentLead.id.desc())
        .limit(limit)
        .offset(offset)
    ))
    return LeadPage(items=items, total=total)


def get_advisor_lead(
    session: Session, context: AccessContext, lead_id: str, *, lock: bool = False
) -> EnrollmentLead:
    """按最小顾问范围读取线索；越权与不存在统一表现。"""

    if not can_manage_leads(context):
        raise LeadNotFoundError("线索不存在")
    statement = select(EnrollmentLead).where(EnrollmentLead.id == lead_id)
    if lock:
        statement = statement.with_for_update()
    lead = session.scalar(statement)
    if lead is None or lead.status == "withdrawn" or not can_follow_up_lead(context, lead):
        raise LeadNotFoundError("线索不存在")
    return lead


def learner_name_for_lead(session: Session, lead: EnrollmentLead) -> str | None:
    """顾问响应使用显示名，不把内部学员 ID 暴露给页面。"""

    if not lead.learner_id:
        return None
    return session.scalar(select(Learner.display_name).where(Learner.id == lead.learner_id))


def follow_ups_for_lead(session: Session, lead_id: str) -> list[LeadFollowUp]:
    return list(session.scalars(
        select(LeadFollowUp)
        .where(LeadFollowUp.lead_id == lead_id)
        .order_by(LeadFollowUp.created_at.asc(), LeadFollowUp.id.asc())
    ))


def reveal_lead_contact(
    session: Session,
    context: AccessContext,
    lead_id: str,
    protector: ContactProtector,
) -> tuple[EnrollmentLead, str]:
    """仅向已领取该线索的顾问短暂解密已授权联系方式。"""

    lead = get_advisor_lead(session, context, lead_id, lock=True)
    if not lead.contact_type or not lead.contact_ciphertext or not lead.contact_consent_at:
        raise LeadConflictError("家长尚未授权提供联系方式")
    if lead.assigned_advisor_id != context.user_id:
        # GET 揭示接口不能隐式改变线索归属，顾问必须先通过受控动作领取。
        raise LeadConflictError("请先领取该线索")
    try:
        plaintext = protector.decrypt(lead.contact_ciphertext, lead.contact_type)
    except ContactProtectionError:
        session.rollback()
        raise
    write_audit_log(
        session,
        actor_user_id=context.user_id,
        action="lead.contact.reveal",
        resource_type="enrollment_lead",
        resource_id=lead.id,
        outcome="success",
        metadata={"contact_type": lead.contact_type},
    )
    session.commit()
    return lead, plaintext


_FOLLOW_UP_TRANSITIONS = {
    ("claim", "claimed"): None,
    ("contact", "reached"): "contacted",
    ("contact", "unreachable"): None,
    ("contact", "declined"): "closed_lost",
    ("schedule_trial", "scheduled"): "trial_scheduled",
    ("schedule_trial", "cancelled"): "closed_lost",
    ("confirm_enrollment", "enrolled"): "enrolled",
    ("close", "won"): "closed_won",
    ("close", "lost"): "closed_lost",
}


def add_lead_follow_up(
    session: Session,
    context: AccessContext,
    lead_id: str,
    *,
    action: str,
    result: str,
    note: str | None,
    next_follow_up_at: datetime | None,
) -> tuple[EnrollmentLead, LeadFollowUp]:
    """原子领取线索并追加跟进历史，不允许修改既有历史记录。"""

    transition = _FOLLOW_UP_TRANSITIONS.get((action, result), "invalid")
    if transition == "invalid":
        raise LeadConflictError("跟进动作和结果不匹配")
    lead = get_advisor_lead(session, context, lead_id, lock=True)
    if action == "claim":
        if lead.assigned_advisor_id not in {None, context.user_id}:
            raise LeadNotFoundError("线索不存在")
    elif lead.assigned_advisor_id != context.user_id:
        raise LeadConflictError("请先领取该线索")
    if lead.status in CLOSED_STATUSES:
        raise LeadConflictError("已关闭线索不能继续跟进")
    lead.assigned_advisor_id = context.user_id
    if transition is not None:
        lead.status = transition
    lead.updated_at = datetime.utcnow()
    record = LeadFollowUp(
        lead_id=lead.id,
        advisor_id=context.user_id,
        action=action,
        result=result,
        note=note,
        next_follow_up_at=next_follow_up_at,
    )
    session.add(record)
    write_audit_log(
        session,
        actor_user_id=context.user_id,
        action="lead.follow_up",
        resource_type="enrollment_lead",
        resource_id=lead.id,
        outcome="success",
        metadata={"action": action, "result": result},
    )
    session.commit()
    session.refresh(record)
    return lead, record
