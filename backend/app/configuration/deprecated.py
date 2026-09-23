"""已经退出 uPil 运行时的环境变量清单。

这里只列 uPil 自身配置，不能把 RAGFlow Compose 内部同名变量误判为废弃项。
审计脚本会按文件作用域检查这些键，并且只输出键名，不输出任何配置值。
"""

DEPRECATED_UPIL_ENV_KEYS = frozenset(
    {
        # 教师媒体工作台已经退役，报告存储改用 REPORT_PDF_BUCKET。
        "MEDIA_MAX_BYTES",
        "MINIO_BUCKET",
        "MINIO_PRESIGNED_URL_SECONDS",
        # 公开咨询和服务规则已经拆成两个独立 RAGFlow Assistant。
        "RAGFLOW_CHAT_ID",
    }
)

# 根目录 .env 还包含 Redis 容器启动密码；它不属于 Pydantic Settings，
# 但由 infra/docker-compose.yml 合法消费，配置审计必须显式放行。
INFRASTRUCTURE_ONLY_ENV_KEYS = frozenset({"UPIL_REDIS_PASSWORD"})
