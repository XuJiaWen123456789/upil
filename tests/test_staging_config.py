"""阶段 13-H：staging 容器配置的静态安全回归测试。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGING_DIR = PROJECT_ROOT / "infra" / "staging"


def read_staging_file(name: str) -> str:
    """读取 staging 配置文件，不读取真实 .env，避免凭据进入断言输出。"""

    return (STAGING_DIR / name).read_text(encoding="utf-8")


def test_staging_files_exist() -> None:
    """容器化联调所需的三个构建文件必须存在。"""

    for name in ("Dockerfile", "docker-compose.staging.yml", ".dockerignore"):
        assert (STAGING_DIR / name).is_file()


def test_dockerfile_uses_python_311_and_non_root_user() -> None:
    """镜像使用项目 Python 基线，并声明非 root 运行用户。"""

    dockerfile = read_staging_file("Dockerfile")
    assert "FROM python:3.11-slim" in dockerfile
    assert "USER upil" in dockerfile
    assert "docker.sock" not in dockerfile.lower()


def test_staging_compose_uses_external_network_and_safe_ports() -> None:
    """staging 只连接既有网络，A2A 不映射宿主机端口，API 仅绑定回环地址。"""

    compose = read_staging_file("docker-compose.staging.yml")
    assert "external: true" in compose
    assert "name: upil_network" in compose
    assert '"127.0.0.1:18000:8000"' in compose
    assert '"8101:8101"' not in compose
    assert "docker.sock" not in compose.lower()


def test_staging_compose_uses_internal_a2a_service_name() -> None:
    """主 API 必须通过 Compose 服务名访问 A2A，而不是宿主机回环地址。"""

    compose = read_staging_file("docker-compose.staging.yml")
    assert "A2A_LEARNING_BASE_URL: http://upil-a2a-learning:8101" in compose
    assert "A2A_LEARNING_ALLOWED_HOSTS: upil-a2a-learning" in compose
    assert "condition: service_healthy" in compose


def test_staging_template_does_not_contain_real_credentials() -> None:
    """示例模板只能包含占位值，真实密钥由用户本地文件注入。"""

    template = read_staging_file(".env.staging.example")
    assert "RAGFLOW_API_KEY=" in template
    assert "LLM_API_KEY=" in template
    assert "A2A_LEARNING_SERVICE_TOKEN=" in template
    # 只检查供应商密钥的通用前缀，测试代码不能保存任何历史真实密钥片段。
    assert "ragflow-1" not in template.lower()


def test_staging_template_declares_explicit_authentication_mode() -> None:
    """本地 staging 可保留 Demo，但必须显式列出切换可信网关所需变量。"""

    template = read_staging_file(".env.staging.example")
    assert "AUTH_MODE=demo" in template
    assert "AUTH_TRUSTED_PROXY_SECRET=" in template
    assert "AUTH_USER_HEADER=X-Authenticated-User-ID" in template
    assert "AUTH_ROLE_HEADER=X-Authenticated-Role" in template
    assert "AUTH_PROXY_SECRET_HEADER=X-Auth-Proxy-Secret" in template
    # 示例文件不允许内置一个看似可直接用于部署的共享密钥。
    assert "AUTH_TRUSTED_PROXY_SECRET=change-me" not in template


def test_dockerignore_excludes_local_secrets_and_runtime_data() -> None:
    """构建上下文不得携带本地环境、数据库、测试和 RAGFlow 数据。"""

    dockerignore = read_staging_file(".dockerignore")
    for entry in (".env.*", ".venv/", "tests/", "data/", "infra/ragflow/"):
        assert entry in dockerignore
