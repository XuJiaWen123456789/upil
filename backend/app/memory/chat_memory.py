"""聊天入口的记忆适配层。

本模块把聊天编排与记忆领域解耦：聊天流只需要调用“读取投影”和“写入消息”
两个稳定函数，不直接拼接 SQL、判断学员权限或处理事务。所有进入这里的消息
都应当已经完成联系方式脱敏；本模块也会把安全边界当作最后一道防线。
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.memory.exceptions import MemoryPolicyError, MemoryRepositoryError
from backend.app.memory.structured import MemoryScope, StructuredMemoryService
from backend.app.memory.structured.admission import is_explicit_memory_request
from backend.app.memory.structured.contracts import MemoryCommandResult
from backend.app.services.access_control import AccessContext, can_access_learner


logger = logging.getLogger(__name__)


class ChatMemorySettings(Protocol):
    """聊天记忆适配器需要的最小配置协议。"""

    memory_write_enabled: bool


def resolve_memory_scope(
    session: Session | None,
    context: AccessContext,
    learner_id: str | None,
) -> MemoryScope | None:
    """根据认证主体和学员权限生成长期记忆作用域。

    没有传入学员时，允许读写当前用户级偏好；传入学员时必须先走统一的
    can_access_learner 授权检查。这样家长不能通过任意 learner_id 读取或
    写入别人的偏好，教师也不能因为拥有线索跟进权限而扩大自己的学员范围。
    """

    if session is None:
        return None
    if learner_id:
        try:
            allowed = can_access_learner(session, context, learner_id)
        except SQLAlchemyError:
            # 授权查询失败时必须回滚当前事务。否则 PostgreSQL 会把本轮会话
            # 保留在 aborted 状态，后续主业务查询也会被一个可选记忆功能拖垮。
            session.rollback()
            logger.warning("structured_memory_scope_failed reason=authorization")
            return None
        if not allowed:
            # 不把具体 learner_id 写入日志，也不向调用方区分“无数据”和“无权限”。
            return None
    return MemoryScope(
        tenant_id=context.tenant_id,
        owner_user_id=context.user_id,
        owner_role=context.role,
        learner_id=learner_id,
    )


def read_structured_projection(
    session: Session | None,
    context: AccessContext,
    learner_id: str | None,
) -> tuple[dict[str, str], ...]:
    """读取当前请求可见的结构化偏好投影。

    读取失败不阻断主回答。数据库迁移尚未执行或记忆表暂时不可用时，聊天仍
    可以依靠当前消息、会话短期记忆和既有业务工具完成回答；日志只记录固定
    原因码，避免输出记忆值、用户消息或内部资源标识。
    """

    scope = resolve_memory_scope(session, context, learner_id)
    if scope is None:
        return ()
    try:
        return StructuredMemoryService(session).projections(scope)
    except (MemoryRepositoryError, SQLAlchemyError):
        # PostgreSQL 一条 SQL 失败后会把当前事务标记为 aborted。这里必须
        # 显式回滚，否则记忆表暂不可用会继续拖垮本轮主业务查询。
        session.rollback()
        logger.warning("structured_memory_read_failed reason=storage")
        return ()


def write_structured_memory(
    session: Session | None,
    context: AccessContext,
    learner_id: str | None,
    message: str,
    *,
    conversation_id: str | None,
    message_id: str | None,
    settings: ChatMemorySettings,
) -> bool:
    """按配置从一条已脱敏消息中固化结构化偏好。

    默认关闭写入是为了让部署者先完成迁移、保留周期和删除流程的确认。写入
    失败只回滚记忆事务，不影响已经发送给用户的主回答；显式的记忆策略拒绝
    也只记录固定原因码，不把候选值带入普通日志。
    """

    if (
        not settings.memory_write_enabled
        or session is None
        or not message
        or context.role != "parent"
    ):
        # 当前白名单描述的是家长侧孩子偏好。教师端不自动形成孩子档案，
        # 避免把课堂描述误保存为教师个人长期记忆。
        return False
    scope = resolve_memory_scope(session, context, learner_id)
    if scope is None:
        return False
    try:
        stored = StructuredMemoryService(session).remember_message(
            message,
            scope=scope,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        if stored is None:
            return False
        session.commit()
        return True
    except MemoryPolicyError:
        session.rollback()
        logger.info("structured_memory_write_skipped reason=policy")
        return False
    except (MemoryRepositoryError, SQLAlchemyError):
        session.rollback()
        logger.warning("structured_memory_write_failed reason=storage")
        return False


def handle_explicit_memory_command(
    session: Session | None,
    context: AccessContext,
    learner_id: str | None,
    message: str,
    *,
    conversation_id: str | None,
    message_id: str | None,
    settings: ChatMemorySettings,
) -> MemoryCommandResult:
    """处理明确的“请记住”命令，并返回可供用户确认的安全状态。

    该入口与普通消息的“回答后自主写入”分开：显式命令必须在 FAQ/RAGFlow
    之前完成准入和保存，只有保存成功才能回复“我记住了”，避免旧知识库文案
    覆盖新能力，也避免数据库失败时向用户虚假承诺。
    """

    if not is_explicit_memory_request(message):
        return MemoryCommandResult("rejected")
    # 当前长期记忆的业务边界是家长确认的孩子偏好。教师（包括销售顾问老师）
    # 可以使用各自的业务工作台，但不能通过“请记住”把课堂描述写入家长记忆，
    # 因此在任何候选抽取和数据库写入前明确返回未授权。
    if context.role != "parent":
        return MemoryCommandResult("unauthorized")
    if not settings.memory_write_enabled:
        return MemoryCommandResult("disabled")
    if session is None:
        return MemoryCommandResult("failed")

    scope = resolve_memory_scope(session, context, learner_id)
    if scope is None:
        return MemoryCommandResult("unauthorized")
    try:
        stored = StructuredMemoryService(session).remember_message(
            message,
            scope=scope,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        if stored is None:
            # 显式命令不等于无条件接受；动态、临时、不确定、否定和敏感内容
            # 仍由候选准入策略拒绝，不得把拒绝误报成“已记住”。
            session.rollback()
            return MemoryCommandResult("rejected")
        session.commit()
        return MemoryCommandResult("stored", stored)
    except MemoryPolicyError:
        session.rollback()
        logger.info("structured_memory_command_rejected reason=policy")
        return MemoryCommandResult("rejected")
    except (MemoryRepositoryError, SQLAlchemyError):
        session.rollback()
        logger.warning("structured_memory_command_failed reason=storage")
        return MemoryCommandResult("failed")
