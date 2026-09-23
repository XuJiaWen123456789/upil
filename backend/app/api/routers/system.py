"""健康检查、前端启动信息和会话路由。"""

import asyncio

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.compat import main_symbol
from backend.app.api.dependencies import settings
from backend.app.schemas import (
    DependencyHealthResponse,
    FrontendBootstrapResponse,
    HealthResponse,
    SessionResponse,
    ActorRole,
)
from backend.app.db import get_session
from backend.app.services.authentication import resolve_access_context
from backend.app.services.access_control import can_manage_leads
from backend.app.services.dependency_health import (
    check_dependencies,
    check_ragflow_business_dependencies,
    overall_status,
)
from backend.app.services.report_runtime import report_pdf_runtime_available


router = APIRouter()


@router.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """返回服务存活状态。"""

    return HealthResponse(status="ok", service=settings.app_name, environment=settings.app_env)


@router.get("/api/v1/health/dependencies", response_model=DependencyHealthResponse)
async def dependency_health() -> DependencyHealthResponse:
    """返回脱敏依赖状态，不阻塞异步事件循环。"""

    probe = main_symbol("check_dependencies", check_dependencies)
    dependencies = await asyncio.to_thread(probe, settings)
    return DependencyHealthResponse(
        status=overall_status(dependencies),
        service=settings.app_name,
        environment=settings.app_env,
        dependencies=dependencies,
    )


@router.get(
    "/api/v1/health/dependencies/deep", response_model=DependencyHealthResponse
)
async def deep_dependency_health() -> DependencyHealthResponse:
    """显式执行 RAGFlow 业务深探针，覆盖检索和 Embedding 完整链路。

    该接口可能触发模型冷启动，不供负载均衡器高频轮询。响应只包含稳定状态，
    不返回测试问题、知识库正文、来源、Chat ID、模型名称或异常信息。
    """

    dependencies = await asyncio.to_thread(
        check_ragflow_business_dependencies, settings
    )
    return DependencyHealthResponse(
        status=overall_status(dependencies),
        service=settings.app_name,
        environment=settings.app_env,
        dependencies=dependencies,
    )


@router.get("/api/v1/frontend/bootstrap", response_model=FrontendBootstrapResponse)
async def frontend_bootstrap() -> FrontendBootstrapResponse:
    """返回浏览器启动所需的安全功能开关，不返回内部连接配置。"""

    return FrontendBootstrapResponse(
        app_name=settings.app_name,
        environment=settings.app_env,
        demo_mode=settings.auth_mode == "demo",
        features={
            "chat": True,
            "parent_learning": True,
            "parent_reports": True,
            "teacher_class_summary": True,
            "teacher_lead_workspace": True,
            # 配置开关和原生渲染依赖都正常时才允许前端发起报告任务。
            # 这可避免 Windows 仅安装 Python 包却缺少 Pango/GLib 时，
            # 页面仍显示可用按钮并持续产生必然失败的报告任务。
            "pdf_reports": (
                settings.report_pdf_enabled and report_pdf_runtime_available()
            ),
        },
    )


@router.get("/api/v1/session", response_model=SessionResponse)
async def current_session(
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> SessionResponse:
    """返回当前认证请求可使用的最小前端能力集合。"""

    context = await resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=actor_role,
        requested_user_id=actor_user_id,
    )
    capabilities = {"chat_access", "learning_read"}
    if context.role == "parent":
        capabilities.add("report_read")
    elif context.role == "teacher":
        # 销售顾问老师虽然沿用 teacher 认证角色，但属于独立的最小权限工作画像。
        # 顾问只承接家长授权后的招生线索，不应因为底层角色相同而获得班级统计能力。
        if can_manage_leads(context):
            capabilities.add("lead_followup")
        else:
            capabilities.add("class_summary_read")
    return SessionResponse(
        role=context.role,
        permissions=sorted(context.permissions),
        capabilities=sorted(capabilities),
        demo_user_id=context.user_id if settings.auth_mode == "demo" else None,
    )
