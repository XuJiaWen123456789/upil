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


Probe = Callable[[], bool]


def check_dependencies(
    settings: Settings | None = None,
    *,
    database_probe: Probe | None = None,
    minio_probe: Probe | None = None,
    ragflow_probe: Probe | None = None,
    a2a_probe: Probe | None = None,
) -> dict[str, str]:
    """检查数据库、MinIO、RAGFlow 和 A2A，并返回脱敏状态字典。

    自定义 probe 只用于测试注入；生产调用使用下方的最小真实探针。每个依赖
    独立捕获异常，一个服务失败不会阻止其他依赖继续检查。
    """

    current = settings or get_settings()
    result = {
        "database": _run_probe(database_probe or (lambda: _probe_database(current))),
        "minio": _minio_status(current, minio_probe),
        "ragflow": _ragflow_status(current, ragflow_probe),
        "a2a_learning": _a2a_status(current, a2a_probe),
    }
    return result


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


def _ragflow_status(settings: Settings, probe: Probe | None) -> str:
    """只有 RAGFlow 的 API Key 和至少一个 Chat ID 都配置后才探测。"""

    chat_configured = bool(
        settings.ragflow_public_chat_id
        or settings.ragflow_service_rules_chat_id
        or settings.ragflow_chat_id
    )
    if not settings.ragflow_api_key or not chat_configured:
        return "not_configured"
    return _run_probe(probe or (lambda: _probe_http(settings.ragflow_base_url, settings)))


def _a2a_status(settings: Settings, probe: Probe | None) -> str:
    """A2A 未显式开启时返回 disabled，不强制要求本机存在子服务。"""

    if not settings.a2a_learning_enabled:
        return "disabled"
    return _run_probe(probe or (lambda: _probe_http(f"{settings.a2a_learning_base_url}/health", settings)))


def _probe_database(settings: Settings) -> bool:
    """执行只读 SELECT 1，连接失败时由上层统一转换为安全状态。"""

    engine = build_engine(settings.database_url)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


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


def _probe_http(url: str, settings: Settings) -> bool:
    """使用短超时探测 HTTP 服务，只依据状态码判断可达性。"""

    response = httpx.get(
        url.rstrip("/"),
        timeout=settings.dependency_check_timeout_seconds,
        follow_redirects=False,
    )
    # 4xx 说明服务可达但路径/鉴权不适配；5xx 和网络错误才视为不可用。
    return response.status_code < 500
