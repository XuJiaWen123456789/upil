"""报告 PDF 渲染运行时探针。

WeasyPrint 的 Python 包安装成功并不代表渲染能力可用；Windows 还需要
Pango、GLib 等原生动态库。此模块只做只读导入检查，不生成文件，也不把
动态库路径或底层异常暴露给健康接口和浏览器。
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def report_pdf_runtime_available() -> bool:
    """确认 WeasyPrint 及其原生依赖可以完整导入。"""

    try:
        from weasyprint import CSS, HTML  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


__all__ = ["report_pdf_runtime_available"]
