"""应用配置模块。

配置统一从环境变量或项目根目录的 .env 文件读取，避免把环境差异
硬编码到业务代码中。
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """uPil 服务运行所需的配置项。"""

    # 应用基础信息用于 FastAPI 元数据和健康检查响应。
    app_name: str = "uPil API"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    # 依赖健康检查默认只按请求触发，不在开发环境启动时阻塞 API。
    # 预发布环境可以显式开启启动检查，但检查失败不能让主服务无限等待。
    dependency_check_on_startup: bool = False
    dependency_check_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    # 正式环境默认连接 PostgreSQL；本地测试可通过环境变量切换到 SQLite。
    database_url: str = "postgresql+psycopg://upil:upil@localhost:5432/upil"

    # 图片和文档原文件统一使用 MinIO；数据库只保存媒体元数据和对象键。
    # Windows 本机 9000 可能处于保留端口范围，默认使用 Compose 映射的 19000。
    minio_endpoint: str = "localhost:19000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "upil-media"
    minio_region: str = "us-east-1"
    minio_secure: bool = False
    # 健康检查是否探测 MinIO；媒体接口仍可按需创建适配器，避免开发环境被强制依赖。
    minio_enabled: bool = False
    minio_presigned_url_seconds: int = 600
    media_max_bytes: int = 10 * 1024 * 1024

    # RAGFlow 配置先保留在配置层，后续 FAQ 智能体通过服务适配器使用它。
    # RAGFlow 通过 Docker 映射到主机 19380；容器内部仍使用 9380。
    ragflow_base_url: str = "http://localhost:19380"
    ragflow_api_key: str = ""
    # 公开咨询和服务规则使用不同的 Assistant，避免不同权限范围的文档互相召回。
    ragflow_public_chat_id: str = ""
    ragflow_service_rules_chat_id: str = ""
    # 兼容早期只有一个 Chat ID 的本地配置；新环境应优先填写上面两个字段。
    ragflow_chat_id: str = ""
    ragflow_timeout_seconds: float = 15.0
    # 来源用于后台审计；公开家长端默认不返回文档名、片段和检索分数。
    expose_sources: bool = False

    # 大模型默认关闭，保证没有密钥或外部服务时本地仍可运行和测试。
    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.2
    # 意图识别属于在线入口能力，必须限制等待时间和自动重试次数，避免模型
    # 服务限流时阻塞整个客服请求或形成不可控的重试流量。
    llm_timeout_seconds: float = 20.0
    llm_max_retries: int = 1

    # A2A 学情分析默认关闭，避免开发机未显式选择时改变现有数据库摘要链路。
    # local_http 仅允许访问回环地址，服务令牌只从环境变量读取，禁止写入日志。
    a2a_learning_enabled: bool = False
    a2a_learning_mode: Literal["mock", "local_http"] = "mock"
    a2a_learning_base_url: str = "http://127.0.0.1:8101"
    # A2A 默认只允许回环地址；容器化 staging 只有在显式白名单中加入
    # 服务名后，才允许通过 Docker 内部网络访问子服务，避免形成 SSRF 入口。
    a2a_learning_allowed_hosts: str = "127.0.0.1,localhost,::1"
    a2a_learning_service_token: str = ""
    a2a_learning_timeout_seconds: int = Field(default=10, gt=0, le=60)
    a2a_learning_max_retries: int = Field(default=2, ge=0, le=2)
    a2a_learning_task_ttl_seconds: int = Field(default=1800, gt=0, le=86400)
    a2a_learning_task_max_entries: int = Field(default=1000, gt=0, le=100000)

    # 开发期会话状态仅保存在单个 API 进程内，并通过 TTL 和容量限制内存占用。
    # 生产环境应替换为 Redis 或 PostgreSQL Checkpointer。
    conversation_ttl_seconds: int = 1800
    conversation_max_entries: int = 10000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """返回进程级缓存的配置对象，避免每个请求重复解析环境变量。"""

    return Settings()
