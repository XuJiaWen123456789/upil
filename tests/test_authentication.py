"""HTTP 认证边界的单元测试。

这些测试只验证“请求身份如何变成可信 AccessContext”，不重复测试具体业务
权限。业务层仍由 access_control.py 和 API 回归测试验证家长、教师、管理员的
资源访问范围。
"""

import logging

from fastapi import HTTPException
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import Request

from backend.app.config import Settings
from backend.app.models import User
from backend.app.services.authentication import resolve_access_context
from tests.test_database import make_session, seed_session


PROXY_SECRET = "test-only-proxy-secret"


def make_request(headers: dict[str, str] | None = None) -> Request:
    """构造不经过网络的 Starlette 请求，保留真实 Header 解析行为。"""

    raw_headers = [
        (name.lower().encode("ascii"), value.encode("utf-8"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "headers": raw_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


def make_settings(**overrides: str) -> Settings:
    """返回完全使用测试占位值的认证配置，不读取项目 .env 文件。"""

    values = {
        "auth_mode": "trusted_headers",
        "auth_trusted_proxy_secret": PROXY_SECRET,
        "auth_user_header": "X-Authenticated-User-ID",
        "auth_role_header": "X-Authenticated-Role",
        "auth_proxy_secret_header": "X-Auth-Proxy-Secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def trusted_headers(user_id: str, role: str, *, secret: str = PROXY_SECRET) -> dict[str, str]:
    """生成模拟可信代理注入的最小认证 Header 集合。"""

    return {
        "X-Auth-Proxy-Secret": secret,
        "X-Authenticated-User-ID": user_id,
        "X-Authenticated-Role": role,
    }


def assert_http_error(status_code: int, call) -> HTTPException:
    """执行认证调用并返回 HTTPException，避免测试重复 try/except。"""

    with pytest.raises(HTTPException) as captured:
        call()
    assert captured.value.status_code == status_code
    return captured.value


def test_demo_mode_keeps_local_identity_compatibility() -> None:
    """Demo 模式保留默认家长身份，也允许现有本地页面显式切换角色。"""

    settings = Settings(_env_file=None, auth_mode="demo")
    with make_session() as session:
        default_context = resolve_access_context(make_request(), session, settings)
        teacher_context = resolve_access_context(
            make_request(),
            session,
            settings,
            requested_role="teacher",
            requested_user_id="T1001",
        )

    assert default_context.user_id == "P1001"
    assert default_context.role == "parent"
    assert teacher_context.user_id == "T1001"
    assert teacher_context.role == "teacher"


def test_trusted_headers_ignore_forged_request_identity() -> None:
    """可信模式不得使用客户端请求体或查询参数中伪造的管理员身份。"""

    with make_session() as session:
        seed_session(session)
        context = resolve_access_context(
            make_request(trusted_headers("P1001", "parent")),
            session,
            make_settings(),
            requested_role="admin",
            requested_user_id="A1001",
        )

    assert context.user_id == "P1001"
    assert context.role == "parent"
    assert context.campus_ids == frozenset()


@pytest.mark.parametrize("supplied_secret", ["", "wrong-test-secret"])
def test_trusted_headers_reject_missing_or_wrong_proxy_secret(supplied_secret: str) -> None:
    """没有代理认证或代理密钥不匹配时统一返回 401。"""

    headers = trusted_headers("P1001", "parent", secret=supplied_secret)
    with make_session() as session:
        seed_session(session)
        error = assert_http_error(
            401,
            lambda: resolve_access_context(
                make_request(headers), session, make_settings()
            ),
        )

    assert error.detail == "认证失败"


def test_trusted_headers_fail_closed_when_server_secret_is_not_configured() -> None:
    """服务端漏配共享密钥属于部署故障，不能降级成 Demo 身份。"""

    with make_session() as session:
        seed_session(session)
        error = assert_http_error(
            503,
            lambda: resolve_access_context(
                make_request(trusted_headers("P1001", "parent")),
                session,
                make_settings(auth_trusted_proxy_secret=""),
            ),
        )

    assert error.detail == "认证服务尚未配置"


@pytest.mark.parametrize("user_id", ["UNKNOWN1001", "P1001"])
def test_trusted_headers_reject_unknown_or_inactive_users(user_id: str) -> None:
    """不存在和停用账号使用相同响应，避免形成账号枚举接口。"""

    with make_session() as session:
        seed_session(session)
        if user_id == "P1001":
            session.get(User, user_id).is_active = False
            session.commit()

        error = assert_http_error(
            401,
            lambda: resolve_access_context(
                make_request(trusted_headers(user_id, "parent")),
                session,
                make_settings(),
            ),
        )

    assert error.detail == "认证失败"


def test_trusted_headers_reject_role_mismatch() -> None:
    """代理声明角色必须与身份库一致，Header 不能把家长提升为管理员。"""

    with make_session() as session:
        seed_session(session)
        error = assert_http_error(
            401,
            lambda: resolve_access_context(
                make_request(trusted_headers("P1001", "admin")),
                session,
                make_settings(),
            ),
        )

    assert error.detail == "认证失败"


def test_campus_scope_comes_only_from_identity_store() -> None:
    """客户端附加校区 Header 不能扩大数据库授予的校区范围。"""

    headers = trusted_headers("T1001", "teacher")
    headers["X-Authenticated-Campus-IDs"] = "C01,C02,ALL"
    with make_session() as session:
        seed_session(session)
        context = resolve_access_context(
            make_request(headers), session, make_settings()
        )

    assert context.user_id == "T1001"
    assert context.role == "teacher"
    assert context.campus_ids == frozenset({"C01"})


@pytest.mark.parametrize(
    ("user_id", "role"),
    [("T1001", "teacher"), ("A1001", "admin")],
)
def test_trusted_staff_without_campus_scope_fails_closed(
    user_id: str, role: str
) -> None:
    """教师或管理员漏配校区时拒绝认证，不能把空范围当作全局授权。"""

    with make_session() as session:
        seed_session(session)
        session.get(User, user_id).campus_id = None
        session.commit()

        error = assert_http_error(
            503,
            lambda: resolve_access_context(
                make_request(trusted_headers(user_id, role)),
                session,
                make_settings(),
            ),
        )

    assert error.detail == "账号权限配置不完整"


def test_identity_store_failure_returns_sanitized_503() -> None:
    """身份库故障必须失败关闭，并隐藏连接地址和底层异常。"""

    class BrokenSession:
        def get(self, model, user_id):
            raise SQLAlchemyError("database://internal-host/secret-path")

    error = assert_http_error(
        503,
        lambda: resolve_access_context(
            make_request(trusted_headers("P1001", "parent")),
            BrokenSession(),  # type: ignore[arg-type]
            make_settings(),
        ),
    )

    assert error.detail == "认证服务暂时不可用"
    assert "internal-host" not in str(error.detail)


def test_authentication_logs_do_not_expose_proxy_secret(caplog: pytest.LogCaptureFixture) -> None:
    """认证失败日志只保留固定原因码，不能记录客户端提供的 Secret。"""

    supplied_secret = "do-not-log-this-test-secret"
    with make_session() as session, caplog.at_level(logging.WARNING):
        seed_session(session)
        assert_http_error(
            401,
            lambda: resolve_access_context(
                make_request(
                    trusted_headers("P1001", "parent", secret=supplied_secret)
                ),
                session,
                make_settings(),
            ),
        )

    assert "reason=invalid_proxy_secret" in caplog.text
    assert supplied_secret not in caplog.text
    assert PROXY_SECRET not in caplog.text
