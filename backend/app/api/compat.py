"""拆分期间的旧入口兼容桥。

历史测试和少量内部调用方会对 backend.app.main 的符号做 monkeypatch。
路由已经迁出后，运行时从入口模块读取这些符号，可以保持旧覆盖点有效；
正式业务代码不应依赖这个桥，新代码应直接导入自己的模块依赖。
"""

import sys
from typing import Any


def main_symbol(name: str, fallback: Any) -> Any:
    """读取旧入口上的可替换符号，入口尚未完成初始化时返回默认值。"""

    module = sys.modules.get("backend.app.main")
    return getattr(module, name, fallback) if module is not None else fallback
