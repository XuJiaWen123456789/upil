"""HTTP 请求身份认证服务。

该模块只负责把不可信 HTTP 输入转换为可信 ``AccessContext``。业务接口和
LangGraph 节点只消费认证结果，不再各自解释 Header、查询参数或请求体中的身份。
"""

import hmac
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Protocol

import httpx
import jwt
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError, PyJWK
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import ExternalIdentity, User, UserPermission
from backend.app.services.access_control import AccessContext


logger = logging.getLogger(__name__)
# 认证层和授权层共享同一份双角色边界。历史数据库中即使仍存在 admin
# 记录，也会在这里被拒绝，防止旧账号绕过产品范围收缩重新获得业务权限。
SUPPORTED_ROLES = frozenset({"parent", "teacher"})
# 认证上下文只接收应用已经实现并经过测试的能力。数据库中即使出现拼写错误
# 或未来权限名，也不会被当前版本静默解释为高权限。
SUPPORTED_PERMISSIONS = frozenset({"lead_followup"})
DEMO_ACTOR_IDS = {"parent": "P1001", "teacher": "T1001"}
# Header 值会参与数据库查询和审计。先限定字符与长度，避免控制字符和日志注入。
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")
# OIDC 厂商的 kid 可能是证书指纹、UUID 或 Base64 风格字符串。它不进入数据库，
# 因此允许可打印 ASCII，但禁止空白、控制字符和异常长度。
KEY_ID_PATTERN = re.compile(r"^[\x21-\x7E]{1,256}$")
# OIDC Core 将 sub 定义为大小写敏感且在 issuer 内唯一的字符串。它不必符合
# uPil 本地用户编号格式，因此使用独立上限，避免错误拒绝 IdP 生成的主体标识。
OIDC_SUBJECT_PATTERN = re.compile(r"^[\x21-\x7E]{1,255}$")


class AuthenticationSettings(Protocol):
    """认证服务所需的最小配置协议，便于测试注入而不耦合完整 Settings。"""

    auth_mode: str
    auth_trusted_proxy_secret: str
    auth_user_header: str
    auth_role_header: str
    auth_proxy_secret_header: str
    auth_oidc_issuer: str
    auth_oidc_audience: str
    auth_oidc_jwks_uri: str
    auth_oidc_algorithms: str
    auth_oidc_subject_claim: str
    auth_oidc_jwks_cache_seconds: int
    auth_oidc_clock_skew_seconds: int
    auth_oidc_http_timeout_seconds: float


@dataclass(frozen=True)
class _JwksCacheEntry:
    """缓存身份提供方公钥，减少每次请求都访问 OIDC 服务的延迟。"""

    keys: tuple[dict, ...]
    refreshed_at: float
    expires_at: float


# 缓存只保存公开 JWK，不包含用户令牌或业务身份。进程重启后可安全重建。
_JWKS_CACHE: dict[str, _JwksCacheEntry] = {}
# 强制刷新时间与普通缓存更新时间必须分开记录。普通缓存刚建立后仍可能恰逢 IdP
# 完成密钥轮换，此时未知 kid 应获准立即再拉取一次；只有由未知 kid 触发的出站
# 刷新才进入冷却窗口，避免攻击者不断伪造 kid 放大对身份提供方的请求。
_JWKS_FORCED_REFRESH_AT: dict[str, float] = {}
MAX_JWKS_RESPONSE_BYTES = 1024 * 1024
MAX_JWKS_KEYS = 100
JWKS_FORCED_REFRESH_COOLDOWN_SECONDS = 30


async def resolve_access_context(
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
        return _resolve_demo_context(session, requested_role, requested_user_id)
    if settings.auth_mode == "trusted_headers":
        return _resolve_trusted_header_context(request, session, settings)
    if settings.auth_mode == "oidc_jwt":
        return await _resolve_oidc_jwt_context(request, session, settings)

    # Literal 通常会在配置加载时阻止该分支；保留失败关闭以防替代配置对象失误。
    logger.error("authentication_rejected reason=unsupported_auth_mode")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="认证服务配置无效",
    )


def _resolve_demo_context(
    session: Session, requested_role: str | None, requested_user_id: str | None
) -> AccessContext:
    """从本地身份库生成权限上下文；该模式不能用于生产入口。

    Demo 模式允许前端选择家长或教师账号，但不能因此绕过正常的数据范围。
    特别是教师仍需从数据库取得校区范围，否则收缩管理员角色后，为了让
    本地页面可用而放宽 ``can_access_class`` 会重新引入跨校区越权风险。
    """

    role = requested_role or "parent"
    if role not in SUPPORTED_ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前用户身份无效")
    user_id = requested_user_id or DEMO_ACTOR_IDS[role]
    if not IDENTIFIER_PATTERN.fullmatch(user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前用户身份无效")

    # 本地身份也必须是数据库中已启用且角色匹配的业务用户。这样各环境与
    # trusted_headers/OIDC 共用同一授权数据源，不会形成只在本地模式存在的后门。
    user = _load_active_user(session, user_id)
    if user is None or not user.is_active or user.role not in SUPPORTED_ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前用户身份无效")
    if not hmac.compare_digest(role, user.role):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前用户身份无效")
    if user.role == "teacher" and not user.campus_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="账号权限配置不完整",
        )

    return _build_access_context(session, user)


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

    user = _load_active_user(session, user_id)
    if user is None or not user.is_active:
        # 不区分用户不存在和账号停用，避免对外形成账号枚举接口。
        logger.warning("authentication_rejected reason=unknown_or_inactive_user")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失败")
    if user.role not in SUPPORTED_ROLES or not hmac.compare_digest(claimed_role, user.role):
        logger.warning("authentication_rejected reason=role_mismatch")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失败")
    if user.role == "teacher" and not user.campus_id:
        # 教师的校区不是运营权限，而是授课数据的第二层隔离范围。空校区不能
        # 被解释为“不限校区”，否则身份数据漏填就会演变成横向越权。
        logger.error("authentication_rejected reason=missing_staff_scope")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="账号权限配置不完整",
        )

    # 校区范围只从受控数据库生成。客户端即使附加任意校区 Header 也不会扩大权限。
    return _build_access_context(session, user)


async def _resolve_oidc_jwt_context(
    request: Request, session: Session, settings: AuthenticationSettings
) -> AccessContext:
    """验证 OIDC Bearer JWT，并把外部 ``sub`` 映射为本地授权身份。

    JWT 负责证明用户由受信任身份提供方认证；数据库负责角色、启用状态和
    校区范围。即使 Token 额外携带未支持的高权限角色，也不会扩大本地权限。
    """

    token = _extract_bearer_token(request)
    try:
        header = jwt.get_unverified_header(token)
    except InvalidTokenError as exc:
        raise _authentication_failed("malformed_jwt") from exc

    algorithm = header.get("alg")
    key_id = header.get("kid")
    allowed_algorithms = _configured_algorithms(settings.auth_oidc_algorithms)
    if algorithm not in allowed_algorithms:
        raise _authentication_failed("disallowed_jwt_algorithm")
    if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
        raise _authentication_failed("invalid_jwt_key_id")

    # 先使用缓存；密钥轮换导致 kid 未命中时强制刷新一次，再决定是否拒绝。
    keys = await _get_jwks(settings, force_refresh=False)
    jwk = _select_jwk(keys, key_id, algorithm)
    if jwk is None:
        keys = await _get_jwks(settings, force_refresh=True)
        jwk = _select_jwk(keys, key_id, algorithm)
    if jwk is None:
        raise _authentication_failed("unknown_jwt_key")

    subject_claim = settings.auth_oidc_subject_claim.strip()
    try:
        public_key = PyJWK.from_dict(jwk).key
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=list(allowed_algorithms),
            audience=settings.auth_oidc_audience,
            issuer=settings.auth_oidc_issuer,
            leeway=settings.auth_oidc_clock_skew_seconds,
            options={
                # 明确要求生产授权所依赖的标准声明，不能只验证签名。
                "require": ["exp", "iat", "iss", "aud", subject_claim],
            },
        )
    except (InvalidTokenError, ValueError, TypeError) as exc:
        raise _authentication_failed("invalid_jwt_claims_or_signature") from exc

    subject = claims.get(subject_claim)
    if not isinstance(subject, str) or not OIDC_SUBJECT_PATTERN.fullmatch(subject):
        raise _authentication_failed("invalid_subject_claim")

    # 不假设 IdP 的 sub 等于业务用户编号，也不使用可变邮箱做授权主键。
    # 只有受控运维流程提前建立的 issuer + subject 映射可以进入本地授权链路。
    user = _load_user_by_external_identity(
        session,
        issuer=settings.auth_oidc_issuer,
        subject=subject,
    )
    if user is None or not user.is_active:
        # 外部身份存在不等于拥有 uPil 账号；必须完成本地账号映射且处于启用状态。
        raise _authentication_failed("unknown_or_inactive_user")
    if user.role not in SUPPORTED_ROLES:
        raise _authentication_failed("unsupported_database_role")
    if user.role == "teacher" and not user.campus_id:
        logger.error("authentication_rejected reason=missing_staff_scope")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="账号权限配置不完整",
        )

    return _build_access_context(session, user)


def _extract_bearer_token(request: Request) -> str:
    """提取单个 Bearer Token，拒绝歧义格式且不在日志中记录令牌。"""

    authorization = request.headers.get("Authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise _authentication_failed("missing_bearer_token")
    return parts[1]


def _configured_algorithms(raw_algorithms: str) -> frozenset[str]:
    """把已经过 Settings 门禁的算法字符串转换为 PyJWT 白名单。"""

    return frozenset(value.strip() for value in raw_algorithms.split(",") if value.strip())


async def _get_jwks(
    settings: AuthenticationSettings, *, force_refresh: bool
) -> tuple[dict, ...]:
    """读取并短期缓存 JWKS；网络或格式故障按认证依赖不可用处理。"""

    uri = settings.auth_oidc_jwks_uri
    now = time.monotonic()
    cached = _JWKS_CACHE.get(uri)
    if cached is not None and cached.expires_at > now:
        if not force_refresh:
            return cached.keys
        # 未知 kid 可能意味着身份提供方刚轮换密钥，但也可能是攻击者构造的值。
        # 只检查上次“强制”刷新时间，不能把普通缓存更新时间误当成冷却起点。
        last_forced_refresh = _JWKS_FORCED_REFRESH_AT.get(uri)
        if (
            last_forced_refresh is not None
            and now - last_forced_refresh < JWKS_FORCED_REFRESH_COOLDOWN_SECONDS
        ):
            return cached.keys

    if force_refresh:
        # 在发出请求前记录本次尝试，连 IdP 故障场景也要限制重复出站请求。当前请求
        # 仍会返回 503；冷却期内后续请求使用旧缓存并按未知 kid 返回统一 401。
        _JWKS_FORCED_REFRESH_AT[uri] = now

    try:
        document = await _fetch_jwks_document(settings)
        keys = _parse_jwks_document(document)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.error("authentication_rejected reason=jwks_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务暂时不可用",
        ) from exc

    _JWKS_CACHE[uri] = _JwksCacheEntry(
        keys=keys,
        refreshed_at=now,
        expires_at=now + settings.auth_oidc_jwks_cache_seconds,
    )
    return keys


async def _fetch_jwks_document(settings: AuthenticationSettings) -> bytes:
    """限量读取 JWKS 响应，避免异常身份服务返回无界正文占用内存。"""

    chunks: list[bytes] = []
    total_bytes = 0
    async with httpx.AsyncClient(
        timeout=settings.auth_oidc_http_timeout_seconds,
        follow_redirects=False,
    ) as client:
        async with client.stream(
            "GET",
            settings.auth_oidc_jwks_uri,
            headers={"Accept": "application/json"},
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                total_bytes += len(chunk)
                if total_bytes > MAX_JWKS_RESPONSE_BYTES:
                    raise ValueError("JWKS response is too large")
                chunks.append(chunk)
    return b"".join(chunks)


def _parse_jwks_document(document: bytes) -> tuple[dict, ...]:
    """校验 JWKS 顶层结构和 Key 数量，拒绝空集合及部分损坏数据。"""

    payload = json.loads(document)
    raw_keys = payload.get("keys") if isinstance(payload, dict) else None
    if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= MAX_JWKS_KEYS:
        raise ValueError("JWKS keys are missing or exceed the configured limit")
    keys = tuple(key for key in raw_keys if isinstance(key, dict))
    if len(keys) != len(raw_keys):
        raise ValueError("JWKS contains an invalid key")
    return keys


def _select_jwk(
    keys: tuple[dict, ...], key_id: str, algorithm: str
) -> dict | None:
    """按 kid、用途和算法唯一选择验证公钥，拒绝含糊的重复项。"""

    candidates = [
        key
        for key in keys
        if key.get("kid") == key_id
        and key.get("use", "sig") == "sig"
        and key.get("alg", algorithm) == algorithm
    ]
    return candidates[0] if len(candidates) == 1 else None


def _load_active_user(session: Session, user_id: str) -> User | None:
    """读取本地身份映射；数据库异常时失败关闭并返回脱敏 503。"""

    try:
        return session.get(User, user_id)
    except SQLAlchemyError as exc:
        logger.error("authentication_rejected reason=identity_store_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务暂时不可用",
        ) from exc


def _load_user_permissions(session: Session, user_id: str) -> frozenset[str]:
    """从本地授权库读取受支持权限，数据库故障时严格失败关闭。

    权限不读取 JWT Claim、可信 Header 或请求体。外部认证只证明“你是谁”，
    uPil 数据库才决定“你能做什么”，从而避免被客户端伪造权限字符串提权。
    """

    try:
        permissions = session.scalars(
            select(UserPermission.permission).where(UserPermission.user_id == user_id)
        ).all()
    except SQLAlchemyError as exc:
        logger.error("authentication_rejected reason=permission_store_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务暂时不可用",
        ) from exc
    return frozenset(
        permission for permission in permissions if permission in SUPPORTED_PERMISSIONS
    )


def _build_access_context(session: Session, user: User) -> AccessContext:
    """把数据库身份、数据范围和细粒度能力组装成不可变授权上下文。"""

    campus_ids = frozenset({user.campus_id}) if user.campus_id else frozenset()
    return AccessContext(
        user_id=user.id,
        role=user.role,
        campus_ids=campus_ids,
        permissions=_load_user_permissions(session, user.id),
    )


def _load_user_by_external_identity(
    session: Session, *, issuer: str, subject: str
) -> User | None:
    """通过启用的外部身份映射读取本地用户，数据库异常时失败关闭。

    该查询不会按邮箱、用户名或 Token 角色进行模糊匹配。映射缺失、映射停用、
    用户缺失和用户停用在 HTTP 层都统一表现为认证失败，防止账号枚举。
    """

    try:
        statement = (
            select(User)
            .join(ExternalIdentity, ExternalIdentity.user_id == User.id)
            .where(
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.subject == subject,
                ExternalIdentity.is_active.is_(True),
            )
        )
        return session.scalar(statement)
    except SQLAlchemyError as exc:
        logger.error("authentication_rejected reason=identity_store_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务暂时不可用",
        ) from exc


def _authentication_failed(reason: str) -> HTTPException:
    """生成统一 401，原因码只写服务日志，不泄露令牌校验细节。"""

    logger.warning("authentication_rejected reason=%s", reason)
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败",
        headers={"WWW-Authenticate": "Bearer"},
    )
