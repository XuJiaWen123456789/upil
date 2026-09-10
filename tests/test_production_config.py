"""生产配置模板的静态安全回归测试。

模板不证明系统已经上线，但可以阻止后续修改把 Demo 身份模式、示例密码或
可直接使用的共享密钥误带进生产部署基线。
"""

from pathlib import Path

from pydantic import ValidationError
import pytest

from backend.app.config import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_TEMPLATE = (
    PROJECT_ROOT / "infra" / "production" / ".env.production.example"
)


def read_production_template() -> str:
    """只读取可提交的示例模板，不读取任何真实生产环境变量。"""

    return PRODUCTION_TEMPLATE.read_text(encoding="utf-8")


def test_production_template_exists_and_selects_production_environment() -> None:
    """生产模板必须显式声明环境，避免部署时意外继承 development。"""

    assert PRODUCTION_TEMPLATE.is_file()
    template = read_production_template()
    assert "APP_ENV=production" in template


def test_production_template_requires_trusted_header_authentication() -> None:
    """生产基线必须选择可信代理认证，不能回退到客户端可控的 Demo 身份。"""

    template = read_production_template()
    assert "AUTH_MODE=trusted_headers" in template
    assert "AUTH_MODE=demo" not in template
    assert "AUTH_USER_HEADER=X-Authenticated-User-ID" in template
    assert "AUTH_ROLE_HEADER=X-Authenticated-Role" in template
    assert "AUTH_PROXY_SECRET_HEADER=X-Auth-Proxy-Secret" in template


def test_production_template_does_not_embed_deployable_credentials() -> None:
    """共享密钥和外部服务凭据必须为空，并由部署平台在运行时注入。"""

    template = read_production_template()
    for variable in (
        "AUTH_TRUSTED_PROXY_SECRET",
        "DATABASE_URL",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "RAGFLOW_API_KEY",
        "LLM_API_KEY",
        "A2A_LEARNING_SERVICE_TOKEN",
    ):
        assert f"{variable}=\n" in template

    lowered = template.lower()
    assert "minioadmin" not in lowered
    assert "change-me" not in lowered
    assert "ragflow-1" not in lowered


def test_unverified_a2a_runtime_is_disabled_in_production_template() -> None:
    """真实执行节点未接入前，生产模板不能默认启用受控 Mock A2A 服务。"""

    template = read_production_template()
    assert "A2A_LEARNING_ENABLED=false" in template


def test_production_runtime_rejects_demo_authentication() -> None:
    """即使部署者漏改模板，生产配置也不能回退到客户端模拟身份。"""

    with pytest.raises(ValidationError, match="trusted_headers"):
        Settings(
            _env_file=None,
            app_env="production",
            auth_mode="demo",
        )


@pytest.mark.parametrize("proxy_secret", ["short-secret", " " * 32])
def test_production_runtime_requires_strong_proxy_secret(proxy_secret: str) -> None:
    """生产进程必须在启动前取得足够长的随机代理共享密钥。"""

    with pytest.raises(ValidationError, match="至少需要 32 个字符"):
        Settings(
            _env_file=None,
            app_env="production",
            auth_mode="trusted_headers",
            auth_trusted_proxy_secret=proxy_secret,
        )


def test_production_runtime_accepts_explicit_trusted_authentication() -> None:
    """完整可信认证配置应通过启动校验，供认证代理后的服务使用。"""

    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_mode="trusted_headers",
        auth_trusted_proxy_secret="test-only-32-character-proxy-secret",
    )

    assert settings.auth_mode == "trusted_headers"
