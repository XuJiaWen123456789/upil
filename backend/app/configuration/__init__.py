"""应用配置治理入口。

配置对象本身仍定义在 :mod:`backend.app.config`，本包只承载环境契约、
废弃字段和模板审计规则，避免把部署治理继续堆进主配置文件。
"""

from backend.app.configuration.validation import validate_runtime_contract

__all__ = ["validate_runtime_contract"]
