"""环境文件和部署模板的静态配置审计。

运行时配置校验只能发现“当前进程”加载到的问题，不能阻止示例模板漏字段、
旧变量长期残留或私有环境文件继续使用已经退出的兼容键。本模块只读取变量名
和少量非敏感布尔/枚举值，审计结果绝不包含密码、Token、URL 或 Chat ID 的值。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from backend.app.config import Settings
from backend.app.configuration.deprecated import (
    DEPRECATED_UPIL_ENV_KEYS,
    INFRASTRUCTURE_ONLY_ENV_KEYS,
)


@dataclass(frozen=True, slots=True)
class AuditIssue:
    """单条配置问题；只记录文件、变量名和安全说明。"""

    path: Path
    key: str
    message: str


def parse_env_file(path: Path) -> dict[str, str]:
    """解析简单 KEY=VALUE 文件，不展开变量，也不执行任何内容。"""

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip().upper()
        if normalized_key:
            values[normalized_key] = value.strip()
    return values


def audit_env_file(
    path: Path,
    *,
    require_all_settings: bool = False,
    allow_infrastructure_keys: bool = False,
) -> list[AuditIssue]:
    """审计一个环境文件的字段完整性、废弃键和关键能力开关。"""

    values = parse_env_file(path)
    issues: list[AuditIssue] = []
    settings_keys = {name.upper() for name in Settings.model_fields}
    allowed_extra = INFRASTRUCTURE_ONLY_ENV_KEYS if allow_infrastructure_keys else frozenset()

    for key in sorted(values):
        if key in DEPRECATED_UPIL_ENV_KEYS:
            issues.append(AuditIssue(path, key, "已废弃，请删除并使用当前业务配置"))
        elif key not in settings_keys and key not in allowed_extra:
            issues.append(AuditIssue(path, key, "未被 uPil Settings 或基础设施消费"))

    if require_all_settings:
        for key in sorted(settings_keys - values.keys()):
            issues.append(AuditIssue(path, key, "部署模板缺少 Settings 字段"))

    issues.extend(_audit_capability_contract(path, values))
    return issues


def audit_project_templates(project_root: Path) -> list[AuditIssue]:
    """审计仓库中的三份标准模板。"""

    targets = (
        (project_root / ".env.example", True),
        (project_root / "infra/staging/.env.staging.example", False),
        (project_root / "infra/production/.env.production.example", False),
    )
    issues: list[AuditIssue] = []
    for path, allow_infrastructure_keys in targets:
        issues.extend(
            audit_env_file(
                path,
                require_all_settings=True,
                allow_infrastructure_keys=allow_infrastructure_keys,
            )
        )
    return issues


def _audit_capability_contract(
    path: Path, values: Mapping[str, str]
) -> list[AuditIssue]:
    """检查可从静态文件安全判断的关键能力依赖。"""

    issues: list[AuditIssue] = []
    environment = values.get("APP_ENV", "").strip().lower()
    managed = environment in {"staging", "production"}

    if managed and values.get("CONVERSATION_STORE_BACKEND", "").lower() != "redis":
        issues.append(AuditIssue(path, "CONVERSATION_STORE_BACKEND", "受管环境必须使用 redis"))
    if managed and not values.get("REDIS_URL", "").strip() and environment != "production":
        # 生产模板允许把完整 Redis URL 留给 Secret Manager；staging 示例则应
        # 明确展示容器内连接格式，避免部署者漏配后静默回退。
        issues.append(AuditIssue(path, "REDIS_URL", "staging 模板必须声明 Redis 连接"))
    if managed and values.get("MEMORY_WRITE_ENABLED", "").lower() != "true":
        issues.append(AuditIssue(path, "MEMORY_WRITE_ENABLED", "受管环境必须开启结构化长期记忆"))
    if values.get("REPORT_PDF_ENABLED", "").lower() == "true" and values.get(
        "MINIO_ENABLED", ""
    ).lower() != "true":
        issues.append(AuditIssue(path, "MINIO_ENABLED", "启用 PDF 时必须启用 MinIO"))

    ragflow_keys = {
        "RAGFLOW_API_KEY",
        "RAGFLOW_PUBLIC_CHAT_ID",
        "RAGFLOW_SERVICE_RULES_CHAT_ID",
    }
    if any(key in values for key in ragflow_keys) and not ragflow_keys <= values.keys():
        for key in sorted(ragflow_keys - values.keys()):
            issues.append(AuditIssue(path, key, "RAGFlow 双知识域配置不完整"))
    return issues
