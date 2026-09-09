"""数据库基础设施。

本模块只负责创建 SQLAlchemy 基础类、Engine、Session 工厂和 FastAPI
依赖，不放置具体业务查询，以保持数据访问边界清晰。
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型共享的声明式基类。"""

    # 所有业务模型都继承这个基类，Alembic 通过它读取统一的表元数据。
    pass


@lru_cache(maxsize=8)
def build_engine(database_url: str | None = None):
    """根据连接地址创建 SQLAlchemy Engine。

    database_url 参数主要服务于测试注入；未传入时使用应用配置。
    """

    url = database_url or get_settings().database_url
    # SQLite 只服务于本地测试；正式环境使用 PostgreSQL 连接池。
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    # Engine 是进程级资源，缓存后可复用连接池，避免每个请求重复创建连接池。
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


@lru_cache(maxsize=8)
def build_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """创建绑定到指定数据库的 Session 工厂。"""

    return sessionmaker(bind=build_engine(database_url), autoflush=False, expire_on_commit=False)


# 默认工厂在应用启动时创建，但只有实际执行查询时才会建立数据库连接。
SessionLocal = build_session_factory()


def get_session() -> Generator[Session, None, None]:
    """提供一个请求范围内的数据库会话，并在请求结束时关闭它。"""

    # 每个请求独立使用一个 Session，结束后无论成功失败都释放连接。
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
