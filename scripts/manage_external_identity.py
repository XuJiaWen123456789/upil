"""显式管理 OIDC 外部身份与 uPil 本地账号的绑定。

该脚本是部署运维入口，不是用户自助注册接口。OIDC Token 验证成功后只有
预先建立且启用的映射才能登录，从而防止首次登录自动创建高权限账号。
"""

import argparse
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError

from backend.app.config import get_settings
from backend.app.db import build_session_factory
from backend.app.models import ExternalIdentity, User


def parse_args() -> argparse.Namespace:
    """定义绑定和停用命令，敏感凭据仍只从环境变量读取。"""

    parser = argparse.ArgumentParser(description="管理 uPil OIDC 外部身份映射")
    parser.add_argument(
        "--database-url",
        default=None,
        help="数据库地址；默认读取 DATABASE_URL，不建议写入 Shell 历史",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    bind = subcommands.add_parser("bind", help="创建或重新启用一条身份映射")
    bind.add_argument("--issuer", required=True, help="Token 中经过验证的 iss 原值")
    bind.add_argument("--subject", required=True, help="Token 中经过验证的 sub 原值")
    bind.add_argument("--user-id", required=True, help="已存在的 uPil 本地用户编号")

    disable = subcommands.add_parser("disable", help="停用一条身份映射")
    disable.add_argument("--issuer", required=True)
    disable.add_argument("--subject", required=True)
    return parser.parse_args()


def validate_identity_values(issuer: str, subject: str) -> None:
    """在写库前检查字段边界，避免生成永远无法被认证链路匹配的数据。"""

    parsed = urlsplit(issuer)
    if len(issuer) > 512 or parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("issuer 必须是长度不超过 512 的 HTTP(S) URL")
    if not 1 <= len(subject) <= 255 or any(character.isspace() for character in subject):
        raise ValueError("subject 必须为 1 至 255 个不含空白的字符")


def bind_identity(database_url: str, issuer: str, subject: str, user_id: str) -> str:
    """创建或启用映射，拒绝把既有外部身份静默换绑到另一用户。"""

    validate_identity_values(issuer, subject)
    session_factory = build_session_factory(database_url)
    with session_factory() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("本地用户不存在，请先通过受控账号流程创建用户")
        if not user.is_active:
            raise ValueError("本地用户已停用，不能创建新的登录映射")
        # 外部身份只能映射到当前产品支持的业务角色。历史管理员记录即使尚未
        # 完成数据库迁移停用，也不能通过运维脚本重新取得登录入口。
        if user.role not in {"parent", "teacher"}:
            raise ValueError("只能为家长或教师账号建立外部身份映射")

        identity = session.get(ExternalIdentity, (issuer, subject))
        if identity is not None:
            if identity.user_id != user_id:
                raise ValueError("该外部身份已绑定其他本地用户，拒绝自动换绑")
            identity.is_active = True
            action = "重新启用"
        else:
            # 同一 issuer 下的一个本地账号只允许一个主体，数据库唯一约束承担
            # 最终并发保护；脚本把约束失败转换为明确的运维错误。
            session.add(
                ExternalIdentity(issuer=issuer, subject=subject, user_id=user_id, is_active=True)
            )
            action = "创建"
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("该本地用户在此身份提供方下已有其他绑定") from exc
    return f"外部身份映射已{action}：user_id={user_id}"


def disable_identity(database_url: str, issuer: str, subject: str) -> str:
    """停用映射而不删除审计关联，重复执行保持幂等。"""

    validate_identity_values(issuer, subject)
    session_factory = build_session_factory(database_url)
    with session_factory() as session:
        identity = session.get(ExternalIdentity, (issuer, subject))
        if identity is None:
            raise ValueError("外部身份映射不存在")
        # 重复停用保持幂等。保留记录而不是物理删除，便于审计用户曾经拥有的
        # 外部身份关系，也避免重新绑定时丢失历史关联。
        identity.is_active = False
        session.commit()
        user_id = identity.user_id
    return f"外部身份映射已停用：user_id={user_id}"


def main() -> None:
    """执行运维命令，只输出结果状态，不回显数据库凭据。"""

    args = parse_args()
    database_url = args.database_url or get_settings().database_url
    try:
        if args.command == "bind":
            result = bind_identity(
                database_url,
                args.issuer,
                args.subject,
                args.user_id,
            )
        else:
            result = disable_identity(
                database_url,
                args.issuer,
                args.subject,
            )
    except ValueError as exc:
        raise SystemExit(f"操作失败：{exc}") from exc

    # 输出只包含操作结果和本地业务编号，不回显数据库 URL、JWT 或客户端密钥。
    print(result)


if __name__ == "__main__":
    main()
