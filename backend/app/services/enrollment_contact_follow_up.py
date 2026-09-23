"""处理高意向线索的联系方式补全轮。

联系方式补全不是普通课程问答：家长已经看到线索卡后，下一条消息可能只有
手机号、邮箱或授权说明。这里在主 Agent 之前做一个很小的确定性门禁，避免
这类消息重新进入欢迎语/FAQ；真正的授权、加密保存和状态迁移仍统一交给
enrollment_leads.apply_enrollment_intent，本模块不写数据库。
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import EnrollmentLead
from backend.app.services.access_control import AccessContext
from backend.app.services.enrollment_intent import deterministic_enrollment_intent
from backend.app.services.lead_contacts import ContactExtraction


@dataclass(frozen=True, slots=True)
class ContactFollowUpDecision:
    """联系方式补全轮的安全投影。"""

    answer: str


# 只有当前会话已经存在活动高意向线索时，才允许把这种极短回复解释为对
# 试听/报名流程的继续补全。除了首次等待授权，还要覆盖跨会话复用后已经
# 登记过联系方式的线索：家长重新提供或更正联系方式时同样不能掉回普通
# FAQ。该规则不能加入全局意图词表，否则普通问答中的“同意”会被误判。
_ISOLATED_CONSENT_PATTERN = re.compile(r"^(?:我\s*)?同意[。！!]*$")
_CONTACT_FOLLOW_UP_STATUSES = (
    "open",
    "awaiting_contact_consent",
    "ready_for_followup",
    "contacted",
    "trial_scheduled",
)


def _active_contact_lead(
    session: Session, context: AccessContext, conversation_ref: str
) -> EnrollmentLead | None:
    """读取当前家长、当前会话中仍可补充联系方式的高意向线索。

    ``conversation_ref`` 仍是必要边界，防止一个会话中的孤立手机号误更新
    家长在其他课程、其他会话下的线索；状态范围排除已报名和所有终态，
    避免已完成业务被一条普通消息重新打开。
    """

    if context.role != "parent":
        return None
    return session.scalar(
        select(EnrollmentLead)
        .where(
            EnrollmentLead.parent_id == context.user_id,
            EnrollmentLead.conversation_ref == conversation_ref,
            EnrollmentLead.strength == "high",
            EnrollmentLead.status.in_(_CONTACT_FOLLOW_UP_STATUSES),
        )
        .order_by(EnrollmentLead.updated_at.desc(), EnrollmentLead.id.desc())
        .limit(1)
    )


def resolve_contact_follow_up(
    session: Session,
    context: AccessContext,
    *,
    conversation_ref: str,
    safe_message: str,
    contact_extraction: ContactExtraction,
) -> ContactFollowUpDecision | None:
    """判断当前消息是否应由联系方式补全门禁直接承接。

    没有联系方式、授权或撤回信号时返回 None，这样家长仍可继续问课程
    或请假；孤立联系方式在没有既有高意向线索时也返回 None，不会凭空
    创建线索。
    """

    lead = _active_contact_lead(session, context, conversation_ref)
    if lead is None:
        return None

    evidence = set(deterministic_enrollment_intent(safe_message).evidence_codes)
    isolated_consent = bool(_ISOLATED_CONSENT_PATTERN.fullmatch(safe_message.strip()))
    has_follow_up_signal = bool(
        contact_extraction.contacts
        or contact_extraction.has_invalid_contact_candidate
        or "contact_consent" in evidence
        or isolated_consent
        or "explicit_decline" in evidence
    )
    if not has_follow_up_signal:
        return None
    if "explicit_decline" in evidence:
        return ContactFollowUpDecision(
            "好的，已撤回本次试听或报名意向；如果之后需要了解课程，随时可以继续咨询。"
        )
    if contact_extraction.has_invalid_contact_candidate:
        return ContactFollowUpDecision(
            "这个号码格式似乎不正确。请提供11位中国大陆手机号或有效邮箱，"
            "并在同一条消息中明确说明同意由销售顾问老师联系您。"
        )
    if contact_extraction.contacts and "contact_consent" in evidence:
        return ContactFollowUpDecision(
            "好的，已收到您的联系方式和明确授权。我会安全登记，并由销售顾问老师继续确认试听或报名安排。"
        )
    if contact_extraction.contacts:
        return ContactFollowUpDecision(
            "我已识别到您提供了联系方式，但还没有收到明确授权，因此不会保存。"
            "请在同一条消息中重新提供联系方式，并明确同意由销售顾问老师联系您。"
        )
    # 单独回复“同意”仍不满足保存条件，因为当前轮没有联系方式。这里明确
    # 要求联系方式与授权出现在同一条消息中，既承接上下文又避免歧义。
    return ContactFollowUpDecision(
        "可以，请在同一条消息中提供手机号或邮箱，并明确说明同意由销售顾问老师联系您。"
    )
