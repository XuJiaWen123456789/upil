"""HTTP 请求身份认证服务。

该模块只负责把不可信 HTTP 输入转换为可信 ``AccessContext``。业务接口和
LangGraph 节点只消费认证结果，不再各自解释 Header、查询参数或请求体中的身份。
"""

import hmac
import logging
import re
from typing import Protocol

from fastapi import HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models import User
from backend.app.services.access_control import AccessContext


logger = logging.getLogger(__name__)
SUPPORTED_ROLES = frozenset({"parent", "teacher", "admin"})
DEMO_ACTOR_IDS = {"parent": "P1001", "teacher": "T1001", "admin": "A1001"}
# Header 值会参与数据库查询和审计。先限定字符与长度，避免控制字符和日志注入。
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")


class AuthenticationSettings(Protocol):
    """认证服务所需的最小配置协议，便于测试注入而不耦合完整 Settings。"""

    auth_mode: str
    auth_trusted_proxy_secret: str
    auth_user_header: str
    auth_role_header: str
    auth_proxy_secret_header: str


def resolve_access_context(
    request: Request,
    session: Session,
    settings: AuthenticationSettings,
    *,
    requested_role: str | None = None,
    requested_user_id: str | None = None,
) -> AccessContext:
    """根据认证模式生成一次请求唯一可信的权限上下文。

    ``requested_role`` 和 ``requested_user_id`` 只服务于 demo 模式。可信网关模式
    完全忽略这两个客户端可控字段，并使用数据库中的角色和校区作为最终权限来源。
    """

    if settings.auth_mode == "demo":
        return _resolve_demo_context(requested_role, requested_user_id)
    if settings.auth_mode == "trusted_headers":
        return _resolve_trusted_header_context(request, session, settings)

    # Literal 通常会在配置加载时阻止该分支；保留失败关闭以防替代配置对象失误。
    logger.error("authentication_rejected reason=unsupported_auth_mode")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="认证服务配置无效",
    )


def _resolve_demo_context(
    requested_role: str | None, requested_user_id: str | None
) -> AccessContext:
    """保持本地联调兼容；该模式不能用于生产或互联网入口。"""

    role = requested_role or "parent"
    if role not in SUPPORTED_ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前用户身份无效")
    user_id = requested_user_id or DEMO_ACTOR_IDS[role]
    if not IDENTIFIER_PATTERN.fullmatch(user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前用户身份无效")
    return AccessContext(user_id=user_id, role=role)


def _resolve_trusted_header_context(
    request: Request, session: Session, settings: AuthenticationSettings
) -> AccessContext:
    """校验可信代理 Header，并用数据库记录收敛角色和校区权限。"""

    configured_secret = settings.auth_trusted_proxy_secret
    # 空密钥属于服务端配置错误，不能退回 demo 或把空 Header 当作认证成功。
    if not configured_secret:
        logger.error("authentication_rejected reason=missing_proxy_configuration")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务尚未配置",
        )

    supplied_secret = request.headers.get(settings.auth_proxy_secret_header, "")
    if not supplied_secret or not hmac.compare_digest(supplied_secret, configured_secret):
        # 日志只记录固定原因码，绝不记录共享密钥或完整认证 Header。
        logger.warning("authentication_rejected reason=invalid_proxy_secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失败")

    user_id = request.headers.get(settings.auth_user_header, "").strip()
    claimed_role = request.headers.get(settings.auth_role_header, "").strip().lower()
    if not IDENTIFIER_PATTERN.fullmatch(user_id) or claimed_role not in SUPPORTED_ROLES:
        logger.warning("authentication_rejected reason=invalid_identity_headers")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失败")

    try:
        user = session.get(User, user_id)
    except SQLAlchemyError as exc:
        # 身份库不可用时必须失败关闭，不能退回请求体身份或 demo 账号。
        # 对外隐藏连接地址、表结构和 SQL，详细异常只由服务端异常链保留。
        logger.error("authentication_rejected reason=identity_store_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务暂时不可用",
        ) from exc
    if user is None or not user.is_active:
        # 不区分用户不存在和账号停用，避免对外形成账号枚举接口。
        logger.warning("authentication_rejected reason=unknown_or_inactive_user")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失败")
    if user.role not in SUPPORTED_ROLES or not hmac.compare_digest(claimed_role, user.role):
        logger.warning("authentication_rejected reason=role_mismatch")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失败")
    if user.role in {"teacher", "admin"} and not user.campus_id:
        # 当前 User 模型只支持一个授权校区。空校区不能被解释为“全局权限”，
        # 否则身份数据漏填就会演变成横向越权。后续如需集团管理员，应增加
        # 独立角色或显式权限关系表，而不是复用空值表达无限范围。
        logger.error("authentication_rejected reason=missing_staff_scope")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="账号权限配置不完整",
        )

    # 校区范围只从受控数据库生成。客户端即使附加任意校区 Header 也不会扩大权限。
    campus_ids = frozenset({user.campus_id}) if user.campus_id else frozenset()
    return AccessContext(user_id=user.id, role=user.role, campus_ids=campus_ids)
