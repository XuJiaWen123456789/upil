"""按 Agent 职责裁剪只读上下文。"""

from backend.app.context.projectors.enrollment_intent import project_enrollment_intent
from backend.app.context.projectors.faq import build_memory_reference_answer, project_faq
from backend.app.context.projectors.handoff import project_handoff
from backend.app.context.projectors.learning_analysis import project_learning_analysis
from backend.app.context.projectors.service_rules import project_service_rules

__all__ = [
    "project_enrollment_intent",
    "build_memory_reference_answer",
    "project_faq",
    "project_handoff",
    "project_learning_analysis",
    "project_service_rules",
]
