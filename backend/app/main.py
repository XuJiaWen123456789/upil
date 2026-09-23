"""ASGI 部署入口和历史导入兼容门面。

生产实现已经按 HTTP、工作流和服务边界拆分。本文件保留稳定的 app 入口、
FastAPI 依赖函数以及既有测试的替换点，避免模块整理改变外部调用契约。
"""

from backend.app.api.dependencies import (
    get_conversation_store,
    get_intent_model,
    get_lead_intent_model,
    get_report_store,
)
from backend.app.api.runtime import conversation_store, settings
from backend.app.api.static_files import STATIC_DIR, SpaStaticFiles
from backend.app.services.access_control import can_access_class
from backend.app.services.conversation_state import plan_conversation
from backend.app.services.dependency_health import (
    check_dependencies,
    check_ragflow_business_dependencies,
)
from backend.app.services.faq import stream_faq_answer
from backend.app.services.report_pdf import inspect_report_pdf
from backend.app.services.reporting import list_requester_report_tasks
from backend.app.services.service_rules import stream_service_rules_answer
from backend.app.workflows.chat_stream import sse_event, stream_answer
from backend.app.application import create_app


# Uvicorn 继续使用 backend.app.main:app，不改变容器和运维启动命令。
app = create_app()


__all__ = [
    "STATIC_DIR",
    "SpaStaticFiles",
    "app",
    "can_access_class",
    "check_dependencies",
    "check_ragflow_business_dependencies",
    "conversation_store",
    "get_conversation_store",
    "get_intent_model",
    "get_lead_intent_model",
    "get_report_store",
    "inspect_report_pdf",
    "list_requester_report_tasks",
    "plan_conversation",
    "settings",
    "sse_event",
    "stream_answer",
    "stream_faq_answer",
    "stream_service_rules_answer",
]
