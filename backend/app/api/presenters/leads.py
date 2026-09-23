"""销售线索的安全响应投影。"""

from sqlalchemy.orm import Session

from backend.app.models import EnrollmentLead
from backend.app.schemas import LeadFollowUpResponse, LeadSummaryResponse
from backend.app.services.access_control import AccessContext
from backend.app.services.enrollment_leads import learner_name_for_lead


def lead_summary_response(
    session: Session, context: AccessContext, lead: EnrollmentLead
) -> LeadSummaryResponse:
    """不暴露家长编号、证据码和联系方式密文。"""

    return LeadSummaryResponse(
        lead_id=lead.id,
        learner_name=learner_name_for_lead(session, lead),
        course_name=lead.course_name,
        interest_type=lead.interest_type,
        strength=lead.strength,
        destination=lead.destination,
        status=lead.status,
        contact_available=bool(
            lead.contact_type and lead.contact_ciphertext and lead.contact_consent_at
        ),
        contact_masked=lead.contact_masked,
        assigned_to_me=lead.assigned_advisor_id == context.user_id,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


def lead_follow_up_response(record) -> LeadFollowUpResponse:
    """只投影顾问可见的跟进记录。"""

    return LeadFollowUpResponse(
        follow_up_id=record.id,
        action=record.action,
        result=record.result,
        note=record.note,
        next_follow_up_at=record.next_follow_up_at,
        created_at=record.created_at,
    )
