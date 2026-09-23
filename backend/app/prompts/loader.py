"""Prompt 文本资源加载器。"""

from functools import lru_cache
from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """读取并缓存白名单目录中的 UTF-8 Prompt。

    调用方只能传文件名，不能传相对路径或绝对路径，避免把 Prompt 加载器
    变成任意文件读取入口。动态业务 Schema 和白名单仍由 Python 追加。
    """

    if not name.endswith(".txt") or Path(name).name != name:
        raise ValueError("Prompt 名称格式无效")
    path = PROMPT_DIR / name
    if not path.is_file():
        raise ValueError(f"Prompt 资源不存在: {name}")
    return path.read_text(encoding="utf-8").strip()
