"""FastAPI 应用装配。

该模块只负责把中间件、生命周期、业务路由和 Vue 静态资源组装成应用，
不承载具体 HTTP 处理或领域逻辑。部署入口仍由 backend.app.main 提供。
"""

import asyncio
import json
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.compat import main_symbol
from backend.app.api.middleware import attach_request_id
from backend.app.api.routers import chat, conversations, demo, leads, learning, reports, system
from backend.app.api.runtime import settings
from backend.app.api.static_files import STATIC_DIR, SpaStaticFiles
from backend.app.integrations.notifications.dispatcher import notification_dispatch_loop
from backend.app.services.dependency_health import check_dependencies


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """创建完整 HTTP 应用，并保持原有路由和部署契约。"""

    application = FastAPI(title=settings.app_name, version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # 浏览器需要读取追踪 ID，以便联调和故障反馈时关联服务端日志。
        expose_headers=["X-Request-ID"],
    )
    application.middleware("http")(attach_request_id)
    notification_task: asyncio.Task[None] | None = None

    @application.on_event("startup")
    async def start_lead_notification_dispatcher() -> None:
        """按配置启动轻量 Outbox 派发器，不影响未启用通知的环境。"""

        nonlocal notification_task
        if not settings.lead_notification_enabled:
            return
        notification_task = asyncio.create_task(
            notification_dispatch_loop(settings),
            name="lead-notification-dispatcher",
        )

    @application.on_event("shutdown")
    async def stop_lead_notification_dispatcher() -> None:
        """优雅停止后台循环，避免测试或服务关闭后遗留异步任务。"""

        if notification_task is None:
            return
        notification_task.cancel()
        try:
            await notification_task
        except asyncio.CancelledError:
            pass

    @application.on_event("startup")
    async def optional_dependency_startup_check() -> None:
        """按配置执行非阻断依赖探测，失败状态只写入脱敏日志。"""

        if not settings.dependency_check_on_startup:
            return
        # 兼容旧入口测试替换点；探测包含网络访问，因此在线程中执行。
        probe = main_symbol("check_dependencies", check_dependencies)
        dependencies = await asyncio.to_thread(probe, settings)
        logger.info(
            "dependency_startup_health %s",
            json.dumps(dependencies, ensure_ascii=False),
        )

    # 根路径静态挂载必须最后注册，否则会吞掉后续 API 路由。
    application.include_router(system.router)
    application.include_router(learning.router)
    application.include_router(reports.router)
    application.include_router(leads.router)
    application.include_router(conversations.router)
    application.include_router(chat.router)
    application.include_router(demo.router)
    application.mount(
        "/", SpaStaticFiles(directory=STATIC_DIR, html=True), name="frontend"
    )
    return application
