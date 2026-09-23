"""应用配置模块。

配置统一从环境变量或项目根目录的 .env 文件读取，避免把环境差异
硬编码到业务代码中。
"""

from functools import lru_cache
from pathlib import Path
import base64
import binascii
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.configuration.validation import validate_runtime_contract


class Settings(BaseSettings):
    """uPil 服务运行所需的配置项。"""

    # 应用基础信息用于 FastAPI 元数据和健康检查响应。
    app_name: str = "uPil API"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    # 身份认证分为本地身份、可信网关和直接 OIDC JWT 三种模式。本地身份仅用于开发联调；
    # trusted_headers 要求反向代理在完成登录后注入身份；oidc_jwt 由 API 验证 Bearer Token。
    # 业务代码永远不能根据 app_env 自动降级认证，模式必须由部署配置显式选择。
    auth_mode: Literal["demo", "trusted_headers", "oidc_jwt"] = "demo"
    auth_trusted_proxy_secret: str = ""
    auth_user_header: str = "X-Authenticated-User-ID"
    auth_role_header: str = "X-Authenticated-Role"
    auth_proxy_secret_header: str = "X-Auth-Proxy-Secret"
    # issuer、audience 和 JWKS 地址由 OIDC 身份提供方给出。角色和校区不信任
    # Token 声明，验签后仍回查本地 users 表，保持认证与业务授权解耦。
    auth_oidc_issuer: str = ""
    auth_oidc_audience: str = ""
    auth_oidc_jwks_uri: str = ""
    auth_oidc_algorithms: str = "RS256"
    # 默认使用 OIDC 标准 sub 作为外部主体标识；它会经过映射表转换成本地 user_id。
    auth_oidc_subject_claim: str = "sub"
    auth_oidc_jwks_cache_seconds: int = Field(default=300, ge=30, le=86400)
    auth_oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    auth_oidc_http_timeout_seconds: float = Field(default=3.0, gt=0, le=15)

    # 依赖健康检查默认只按请求触发，不在开发环境启动时阻塞 API。
    # 预发布环境可以显式开启启动检查，但检查失败不能让主服务无限等待。
    dependency_check_on_startup: bool = False
    dependency_check_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    # 正式环境默认连接 PostgreSQL；本地测试可通过环境变量切换到 SQLite。
    database_url: str = "postgresql+psycopg://upil:upil@localhost:5432/upil"

    # 学情报告 PDF 使用 MinIO 私有对象存储；数据库只保存完整性元数据和对象键。
    # Windows/Hyper-V 会动态保留部分 18xxx-19xxx 端口，默认使用稳定的 29xxx 映射。
    minio_endpoint: str = "localhost:29000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_region: str = "us-east-1"
    minio_secure: bool = False
    # 健康检查是否探测 MinIO；关闭报告 PDF 时本地开发不被强制依赖。
    minio_enabled: bool = False

    # 家长学情报告使用独立私有桶。PDF 默认关闭以兼容尚未配置字体和 MinIO
    # 的开发环境；staging/production 模板会显式开启，开启后字体缺失必须失败关闭。
    report_pdf_enabled: bool = False
    report_pdf_font_path: str = ""
    report_pdf_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    report_pdf_max_pages: int = Field(default=20, ge=1, le=100)
    report_pdf_template_version: str = Field(
        # v2 表示共享 MarkdownIt + WeasyPrint 转换器；v1 留给历史
        # ReportLab 产物，避免两种渲染实现共用同一个缓存业务键。
        default="learning-report-pdf-v2", min_length=3, max_length=64
    )
    report_pdf_bucket: str = Field(default="upil-reports", min_length=3, max_length=63)

    # RAGFlow 配置先保留在配置层，后续 FAQ 智能体通过服务适配器使用它。
    # RAGFlow 通过 Docker 映射到主机 29380；容器内部仍使用 9380。
    ragflow_base_url: str = "http://localhost:29380"
    ragflow_api_key: str = ""
    # 公开咨询和服务规则使用不同的 Assistant，避免不同权限范围的文档互相召回。
    ragflow_public_chat_id: str = ""
    ragflow_service_rules_chat_id: str = ""
    ragflow_timeout_seconds: float = 15.0
    # 来源用于后台审计；公开家长端默认不返回文档名、片段和检索分数。
    expose_sources: bool = False

    # 大模型默认关闭，保证没有密钥或外部服务时本地仍可运行和测试。
    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    # Supervisor 和旁路 Agent 可以按任务特点选择不同模型；空值继续复用
    # LLM_MODEL，保证现有单模型部署无需修改即可运行。
    llm_router_model: str = ""
    lead_intent_model: str = ""
    llm_temperature: float = 0.2
    # 意图识别属于在线入口能力，必须限制等待时间和自动重试次数，避免模型
    # 服务限流时阻塞整个客服请求或形成不可控的重试流量。
    llm_timeout_seconds: float = 20.0
    llm_max_retries: int = 1

    # 报课意向 Agent 与主回答并行运行；等待上限只约束旁路结果，超时后使用
    # 确定性规则，不允许招生分析拖慢正常咨询。联系方式密钥必须由生产部署
    # 平台注入，开发和自动化测试使用代码内明确标记的 Demo 派生值。
    lead_intent_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    lead_contact_encryption_key: str = ""
    lead_contact_fingerprint_key: str = ""

    # 外部渠道只承担线索提醒，PostgreSQL 线索池仍是唯一业务事实源。
    # 默认关闭可确保未配置飞书的开发环境和既有部署不受影响。
    lead_notification_enabled: bool = False
    lead_notification_channel: Literal["feishu"] = "feishu"
    lead_notification_min_level: Literal["medium", "high"] = "high"
    feishu_webhook_url: str = ""
    lead_notification_max_retries: int = Field(default=3, ge=1, le=10)
    lead_notification_retry_seconds: int = Field(default=60, ge=1, le=3600)
    lead_notification_poll_seconds: float = Field(default=5.0, ge=1, le=300)
    lead_notification_timeout_seconds: float = Field(default=3.0, gt=0, le=15)
    lead_notification_detail_base_url: str = "http://127.0.0.1:18001"

    # 短期会话通过 TTL 控制保留时间；容量上限只用于进程内测试实现，Redis
    # 依靠独立实例、TTL 和部署侧容量监控治理。
    conversation_ttl_seconds: int = 1800
    conversation_max_entries: int = 10000
    # 上下文压缩只保留少量最近有效轮次，较早内容进入滚动摘要；这些值
    # 约束的是本地状态体积，不等于把完整历史无限拼接进模型 Prompt。
    conversation_recent_turns: int = Field(default=8, ge=2, le=30)
    conversation_summary_token_budget: int = Field(default=300, ge=64, le=2000)
    conversation_context_token_budget: int = Field(default=1200, ge=128, le=8000)
    # Settings 的无环境默认值保留 memory，保证单元测试和离线工具不隐式访问
    # 外部服务；仓库环境模板与当前本地运行配置显式选择 redis。
    conversation_store_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    redis_timeout_seconds: float = Field(default=0.5, gt=0, le=10)
    # 结构化长期记忆由环境显式开启；仅保存低敏感白名单偏好，情景向量记忆
    # 仍是独立开关。正式部署必须先执行 007 增量迁移。
    memory_write_enabled: bool = False
    # 当前版本不启用情景向量记忆；没有明确嵌入模型时直接返回空召回，
    # 不为了理论上的完整性引入一个隐含的本地检索实现。
    episodic_memory_enabled: bool = False
    episodic_embedding_model: str = ""

    @model_validator(mode="after")
    def validate_production_authentication(self) -> "Settings":
        """阻止生产环境因漏配变量而继承不可信的开发身份模式。

        示例模板中的密钥故意留空，因此不能被直接当作可运行的生产配置。
        部署平台必须在进程启动前注入随机密钥；校验失败时应用直接拒绝
        启动，比收到业务请求后再暴露认证配置故障更容易被发布系统发现。
        """

        production = self.app_env.strip().lower() == "production"
        # 先校验所有环境都适用的能力依赖，并对 staging/production 启用
        # 完整业务门禁，避免遗漏环境变量后静默关闭记忆或会话能力。
        validate_runtime_contract(self)
        if self.lead_notification_enabled:
            webhook = urlsplit(self.feishu_webhook_url.strip())
            detail_base = urlsplit(self.lead_notification_detail_base_url.strip())
            if webhook.scheme not in {"http", "https"} or not webhook.netloc:
                raise ValueError("启用招生线索通知时必须配置有效的飞书 Webhook")
            if detail_base.scheme not in {"http", "https"} or not detail_base.netloc:
                raise ValueError("招生线索通知处理入口必须是有效的 HTTP(S) URL")
            if production and (webhook.scheme != "https" or detail_base.scheme != "https"):
                raise ValueError("生产环境招生线索通知地址必须使用 HTTPS")
        # WeasyPrint 不应在找不到中文字体时静默回退，否则中文可能变成方框。
        # 这里只校验可部署配置；字体读取和 PDF 文本复核由转换服务再次执行。
        if self.report_pdf_enabled:
            font_path = Path(self.report_pdf_font_path).expanduser()
            if not self.report_pdf_font_path.strip() or not font_path.is_file():
                raise ValueError("启用学情报告 PDF 时必须配置存在的中文字体文件")
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.report_pdf_bucket):
                raise ValueError("学情报告 PDF Bucket 名称不合法")
        if production and self.auth_mode == "demo":
            raise ValueError("生产环境必须使用 trusted_headers 或 oidc_jwt 认证模式")
        encryption_key = self.lead_contact_encryption_key.strip()
        try:
            decoded_encryption_key = base64.b64decode(
                encryption_key.encode("ascii"), altchars=b"-_", validate=True
            )
        except (UnicodeEncodeError, binascii.Error, ValueError):
            decoded_encryption_key = b""
        if production and (
            len(decoded_encryption_key) != 32
            or len(self.lead_contact_fingerprint_key.strip().encode("utf-8")) < 32
        ):
            # 生产环境绝不能使用开发代码中的固定派生密钥。加密密钥必须
            # 是 Fernet 规定的 URL-safe Base64 编码 32 字节随机值；HMAC
            # 指纹密钥也至少需要 32 字节，空值或伪造长字符串都会启动失败。
            raise ValueError("生产环境必须注入有效的招生联系方式加密和指纹密钥")

        if self.auth_mode == "trusted_headers":
            if production and len(self.auth_trusted_proxy_secret.strip()) < 32:
                raise ValueError("生产环境代理共享密钥至少需要 32 个字符")
            return self

        if self.auth_mode != "oidc_jwt":
            return self

        required_values = {
            "AUTH_OIDC_ISSUER": self.auth_oidc_issuer,
            "AUTH_OIDC_AUDIENCE": self.auth_oidc_audience,
            "AUTH_OIDC_JWKS_URI": self.auth_oidc_jwks_uri,
        }
        missing = [name for name, value in required_values.items() if not value.strip()]
        if missing:
            raise ValueError(f"OIDC JWT 认证缺少配置：{', '.join(missing)}")

        # 固定允许非对称算法，拒绝 none 和 HS*，避免把公开 JWKS 密钥误当 HMAC Secret。
        allowed_asymmetric_algorithms = {
            "RS256", "RS384", "RS512",
            "PS256", "PS384", "PS512",
            "ES256", "ES384", "ES512",
        }
        configured_algorithms = {
            value.strip() for value in self.auth_oidc_algorithms.split(",") if value.strip()
        }
        if not configured_algorithms or not configured_algorithms <= allowed_asymmetric_algorithms:
            raise ValueError("OIDC JWT 只允许受支持的非对称签名算法")

        if not self.auth_oidc_subject_claim.strip():
            raise ValueError("OIDC 主体标识声明不能为空")
        if production:
            for name, value in (
                ("AUTH_OIDC_ISSUER", self.auth_oidc_issuer),
                ("AUTH_OIDC_JWKS_URI", self.auth_oidc_jwks_uri),
            ):
                parsed = urlsplit(value)
                if parsed.scheme != "https" or not parsed.netloc:
                    raise ValueError(f"生产环境 {name} 必须是有效的 HTTPS URL")
        return self

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
