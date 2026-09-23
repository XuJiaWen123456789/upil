"""外部依赖健康检查。

健康检查与业务请求解耦：它只验证依赖是否可达，不执行写入、不返回第三方
响应正文，也不把 URL、密码、Token 或 API Key 放入对外响应。开发和测试可以
通过 probe 参数注入假的探针，避免单元测试依赖 Docker 或真实网络。
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
from sqlalchemy import text

from backend.app.config import Settings, get_settings
from backend.app.db import build_engine
from backend.app.integrations.ragflow import RagflowClient
from backend.app.services.report_runtime import report_pdf_runtime_available


Probe = Callable[[], bool]


def check_ragflow_business_dependencies(
    settings: Settings | None = None,
    *,
    public_probe: Probe | None = None,
    service_rules_probe: Probe | None = None,
) -> dict[str, str]:
    """真实验证两个 RAGFlow 知识域，而不返回问答正文或内部配置。

    普通依赖检查只回答“RAGFlow 网关是否可达”，适合频繁存活监控；本函数
    会分别发起一条极短只读问题，因此还能覆盖 Assistant 配置、检索索引、
    Embedding 和回答模型。它仅供显式深度健康接口及发布验收调用，不能放进
    高频浅探针，以免放大模型费用和冷启动延迟。
    """

    current = settings or get_settings()
    if not (
        current.ragflow_api_key
        and current.ragflow_public_chat_id
        and current.ragflow_service_rules_chat_id
    ):
        return {
            "ragflow_public_query": "not_configured",
            "ragflow_service_rules_query": "not_configured",
        }
    return {
        "ragflow_public_query": _run_probe(
            public_probe
            or (
                lambda: _probe_ragflow_assistant(
                    current, current.ragflow_public_chat_id, "编程项目实践班主要学什么？"
                )
            )
        ),
        "ragflow_service_rules_query": _run_probe(
            service_rules_probe
            or (
                lambda: _probe_ragflow_assistant(
                    current, current.ragflow_service_rules_chat_id, "临时请假应如何办理？"
                )
            )
        ),
    }


def check_dependencies(
    settings: Settings | None = None,
    *,
    database_probe: Probe | None = None,
    redis_probe: Probe | None = None,
    minio_probe: Probe | None = None,
    ragflow_probe: Probe | None = None,
    structured_memory_probe: Probe | None = None,
) -> dict[str, str]:
    """检查数据库、短期会话 Redis、MinIO 和 RAGFlow。

    自定义 probe 只用于测试注入；生产调用使用下方的最小真实探针。每个依赖
    独立捕获异常，一个服务失败不会阻止其他依赖继续检查。
    """

    current = settings or get_settings()
    result = {
        "database": _run_probe(database_probe or (lambda: _probe_database(current))),
        "redis": _redis_status(current, redis_probe),
        "minio": _minio_status(current, minio_probe),
        "pdf_renderer": _pdf_renderer_status(current),
        "ragflow": _ragflow_status(current, ragflow_probe),
        "structured_memory": _structured_memory_status(
            current, structured_memory_probe
        ),
        "lead_notifications": _lead_notification_status(current),
    }
    return result


def _pdf_renderer_status(settings: Settings) -> str:
    """报告关闭时不探测；开启后必须验证 Python 包和原生动态库。"""

    if not settings.report_pdf_enabled:
        return "disabled"
    return _run_probe(report_pdf_runtime_available)


def overall_status(dependencies: dict[str, str]) -> str:
    """只要已配置的依赖失败，整体状态就标记为 degraded。"""

    failed = {"unavailable", "error"}
    return "degraded" if any(value in failed for value in dependencies.values()) else "ok"


def _run_probe(probe: Probe) -> str:
    """执行探针并将所有内部异常折叠为稳定状态。"""

    try:
        return "ok" if probe() else "unavailable"
    except Exception:
        # 对外不返回异常类型、连接地址或第三方响应，避免内部信息泄露。
        return "error"


def _minio_status(settings: Settings, probe: Probe | None) -> str:
    """只有显式开启 MinIO 健康检查时才探测，避免开发环境产生无意义故障。"""

    if not settings.minio_enabled or not settings.minio_endpoint.strip():
        return "disabled"
    return _run_probe(probe or (lambda: _probe_minio(settings)))


def _redis_status(settings: Settings, probe: Probe | None) -> str:
    """只有选择 Redis 会话后端时才探测，响应中不返回连接字符串。"""

    if settings.conversation_store_backend != "redis":
        return "disabled"
    return _run_probe(probe or (lambda: _probe_redis(settings)))


def _ragflow_status(settings: Settings, probe: Probe | None) -> str:
    """只有两个知识域都完整配置后才探测 RAGFlow。"""

    if not (
        settings.ragflow_api_key
        and settings.ragflow_public_chat_id
        and settings.ragflow_service_rules_chat_id
    ):
        return "not_configured"
    return _run_probe(probe or (lambda: _probe_http(settings.ragflow_base_url, settings)))


def _structured_memory_status(settings: Settings, probe: Probe | None) -> str:
    """检查结构化长期记忆开关和数据库表，不读取任何用户记忆。"""

    if not settings.memory_write_enabled:
        return "disabled"
    return _run_probe(probe or (lambda: _probe_structured_memory(settings)))


def _lead_notification_status(settings: Settings) -> str:
    """只检查通知配置是否启用，不向飞书发送探测消息。"""

    if not settings.lead_notification_enabled:
        return "disabled"
    # Settings 已验证 URL 结构；健康响应只暴露能力状态，不返回地址。
    return "configured"


def _probe_database(settings: Settings) -> bool:
    """执行只读 SELECT 1，连接失败时由上层统一转换为安全状态。"""

    engine = build_engine(settings.database_url)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def _probe_structured_memory(settings: Settings) -> bool:
    """只确认长期记忆表存在，避免“数据库通、业务表没迁移”的误报。"""

    engine = build_engine(settings.database_url)
    with engine.connect() as connection:
        # 使用 SQLAlchemy inspector 兼容 PostgreSQL 与本地 SQLite 测试。
        from sqlalchemy import inspect

        return bool(inspect(connection).has_table("agent_structured_memories"))


def _probe_minio(settings: Settings) -> bool:
    """通过列举桶验证 MinIO 连通性；不会创建桶或上传对象。

    MinIO 的标准健康端点不要求 S3 凭据，因此这里先探测存活端点，再用
    已配置凭据执行只读 S3 操作。这样可以区分“服务可达”和“凭据可用”，
    避免把错误的账号密码误报成 Docker 网络故障。
    """

    live_url = f"http://{settings.minio_endpoint}/minio/health/live"
    live_response = httpx.get(
        live_url,
        timeout=settings.dependency_check_timeout_seconds,
        follow_redirects=False,
    )
    if live_response.status_code >= 500:
        return False

    from minio import Minio

    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region=settings.minio_region,
    )
    client.list_buckets()
    return True


def _probe_redis(settings: Settings) -> bool:
    """使用短连接执行只读 Ping，不读取会话 Key，也不输出 Redis URL。"""

    import redis

    client = redis.Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_timeout_seconds,
        socket_connect_timeout=settings.redis_timeout_seconds,
        decode_responses=True,
    )
    return bool(client.ping())


def _probe_http(url: str, settings: Settings) -> bool:
    """使用短超时探测 HTTP 服务，只依据状态码判断可达性。"""

    response = httpx.get(
        url.rstrip("/"),
        timeout=settings.dependency_check_timeout_seconds,
        follow_redirects=False,
    )
    # 4xx 说明服务可达但路径/鉴权不适配；5xx 和网络错误才视为不可用。
    return response.status_code < 500


def _probe_ragflow_assistant(
    settings: Settings, chat_id: str, question: str
) -> bool:
    """执行不写业务数据的知识问答，并只判断是否得到非空结果。"""

    result = RagflowClient(settings, chat_id=chat_id).ask_result(question)
    return bool(result and result.provider == "ragflow" and result.answer.strip())
