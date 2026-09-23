"""预发布和生产环境的运行时配置契约。

开发与自动化测试允许关闭外部能力；staging/production 则代表完整业务部署，
关键能力不能因为漏写一个环境变量而静默退回默认值。这里仅校验字段间关系，
不执行网络请求，也不会把 URL、密码、Token 或 Chat ID 写入错误信息。
"""

from typing import Protocol


class RuntimeSettings(Protocol):
    """配置契约校验所需的最小 Settings 视图。"""

    app_env: str
    conversation_store_backend: str
    redis_url: str
    memory_write_enabled: bool
    minio_enabled: bool
    report_pdf_enabled: bool
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    ragflow_api_key: str
    ragflow_public_chat_id: str
    ragflow_service_rules_chat_id: str
    llm_enabled: bool
    llm_api_key: str
    llm_model: str
    episodic_memory_enabled: bool
    episodic_embedding_model: str


def validate_runtime_contract(settings: RuntimeSettings) -> None:
    """校验当前环境必须显式满足的业务能力依赖。

    staging 和 production 均会承载多轮会话、长期偏好与 PDF 报告，因此要求
    Redis、结构化记忆和 MinIO 明确开启。开发环境仍可使用内存、SQLite 和关闭
    外部服务的离线模式，保证单元测试及本地脚本不被生产依赖绑死。
    """

    environment = settings.app_env.strip().lower()
    managed_environment = environment in {"staging", "production"}

    if managed_environment:
        if settings.conversation_store_backend != "redis":
            raise ValueError("预发布和生产环境必须使用 Redis 会话存储")
        if not settings.redis_url.strip():
            raise ValueError("启用 Redis 会话存储时必须配置 REDIS_URL")
        if not settings.memory_write_enabled:
            raise ValueError("预发布和生产环境必须开启结构化长期记忆写入")
    # PDF 二进制始终保存到私有 MinIO，而不是进程本地磁盘。这个依赖关系
    # 与环境无关，开发机显式开启 PDF 时同样不能漏开对象存储。
    if settings.report_pdf_enabled and not settings.minio_enabled:
        raise ValueError("启用学情报告 PDF 时必须同时启用 MinIO")

    if settings.minio_enabled:
        if not all(
            value.strip()
            for value in (
                settings.minio_endpoint,
                settings.minio_access_key,
                settings.minio_secret_key,
            )
        ):
            raise ValueError("启用 MinIO 时必须完整配置访问地址和凭据")

    ragflow_values = (
        settings.ragflow_api_key.strip(),
        settings.ragflow_public_chat_id.strip(),
        settings.ragflow_service_rules_chat_id.strip(),
    )
    if any(ragflow_values) and not all(ragflow_values):
        raise ValueError(
            "RAGFlow 必须同时配置 API Key、公开咨询 Chat ID 和服务规则 Chat ID"
        )

    if settings.llm_enabled and not (
        settings.llm_api_key.strip() and settings.llm_model.strip()
    ):
        raise ValueError("启用大模型时必须同时配置 API Key 和模型名称")

    # 当前仓库仅保留情景记忆协议和 Noop 实现。禁止把开关打开后继续返回
    # 空召回，否则健康检查会显示“已启用”，实际功能却没有任何效果。
    if settings.episodic_memory_enabled:
        if not settings.episodic_embedding_model.strip():
            raise ValueError("启用情景记忆时必须配置嵌入模型")
        raise ValueError("当前版本尚未配置可用的情景记忆存储后端")
