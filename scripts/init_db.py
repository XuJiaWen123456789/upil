"""创建数据库表并写入本地开发演示数据。"""

import argparse
from pathlib import Path

from sqlalchemy import inspect

from backend.app.db import Base, build_engine, build_session_factory
from backend.app.services.seed import seed_demo_data

# 显式导入模型，确保所有表都注册到 Base.metadata 后再 create_all。
from backend.app import models as _models  # noqa: F401


def parse_args() -> argparse.Namespace:
    """解析数据库初始化脚本参数。"""

    parser = argparse.ArgumentParser(description="初始化 uPil 数据库")
    parser.add_argument(
        "--database-url",
        default="sqlite:///D:/uPil/data/upil.db",
        help="SQLAlchemy 数据库地址，默认使用 D:/uPil/data/upil.db",
    )
    return parser.parse_args()


def main() -> None:
    """创建表结构并写入幂等的开发数据。"""

    args = parse_args()
    if args.database_url.startswith("sqlite:///"):
        # SQLite 文件库的父目录需要提前创建，SQLite 不会自动创建多级目录。
        database_path = Path(args.database_url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)
    table_count = len(inspect(engine).get_table_names())

    session_factory = build_session_factory(args.database_url)
    with session_factory() as session:
        added = seed_demo_data(session)

    print(f"数据库初始化完成：{args.database_url}")
    print(f"已发现表数量：{table_count}，本次新增演示记录：{added}")


if __name__ == "__main__":
    main()
