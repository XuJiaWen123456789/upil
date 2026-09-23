"""受限 Markdown 到 PDF 的共享转换工具。

家长报告和教师班级报告都使用本模块。本地模板先组织受控 Markdown，
转换工具再完成语法白名单校验、HTML 包装、WeasyPrint 渲染
和 pypdf 复核。转换期间不执行子进程，也不允许加载任何网络资源。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path
import hmac
import re

from markdown_it import MarkdownIt
from pypdf import PdfReader


PDF_MEDIA_TYPE = "application/pdf"
_MAX_MARKDOWN_BYTES = 128 * 1024
_PDF_MAGIC = b"%PDF-"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN_SOURCE = re.compile(
    r"<[^>]*>|```|~~~|!\[|\[[^]\n]*\]\(|(?:https?|ftp|file|javascript|data):",
    flags=re.IGNORECASE,
)
_ALLOWED_BLOCK_TOKENS = frozenset(
    {
        "heading_open", "heading_close", "paragraph_open", "paragraph_close",
        "blockquote_open", "blockquote_close", "bullet_list_open",
        "bullet_list_close", "ordered_list_open", "ordered_list_close",
        "list_item_open", "list_item_close", "inline",
    }
)
_ALLOWED_INLINE_TOKENS = frozenset(
    {
        "text", "softbreak", "hardbreak", "strong_open", "strong_close",
        "em_open", "em_close", "code_inline",
    }
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:bearer\s+|api[_-]?key|access[_-]?token|password|secret|"
    r"minio://|s3://|https?://|(?:postgres(?:ql)?|mysql)://)"
)


class ReportPdfError(ValueError):
    """报告 Markdown、字体或 PDF 不满足安全与完整性契约。"""


@dataclass(frozen=True)
class ReportPdfDocument:
    """可上传私有对象存储的 PDF 及其权威元数据。"""

    content: bytes
    checksum: str
    size_bytes: int
    page_count: int
    media_type: str
    filename: str


def _markdown_parser() -> MarkdownIt:
    """创建禁用原始 HTML、自动链接和排版扩展的最小解析器。"""

    return MarkdownIt(
        "commonmark", {"html": False, "linkify": False, "typographer": False}
    )


def validate_safe_markdown(markdown: str) -> None:
    """按 token 白名单验证 Markdown，禁止外链、图片、HTML 和代码块。"""

    if not isinstance(markdown, str) or not markdown.strip():
        raise ReportPdfError("报告 Markdown 不能为空")
    if len(markdown.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
        raise ReportPdfError("报告 Markdown 超过安全上限")
    if _FORBIDDEN_SOURCE.search(markdown):
        raise ReportPdfError("报告 Markdown 包含不允许的富文本或资源引用")

    tokens = _markdown_parser().parse(markdown)
    if not tokens or any(token.type not in _ALLOWED_BLOCK_TOKENS for token in tokens):
        raise ReportPdfError("报告 Markdown 包含白名单以外的块结构")
    for token in tokens:
        if any(
            child.type not in _ALLOWED_INLINE_TOKENS
            for child in (token.children or [])
        ):
            raise ReportPdfError("报告 Markdown 包含白名单以外的行内结构")


def markdown_to_pdf(
    markdown: str,
    *,
    title: str,
    template_version: str,
    font_path: str,
    max_bytes: int,
    max_pages: int,
    filename: str,
    generated_at: datetime,
    forbidden_values: tuple[str, ...] = (),
) -> ReportPdfDocument:
    """将已校验 Markdown 渲染为 PDF，并在返回前执行纵深复核。"""

    validate_safe_markdown(markdown)
    font = Path(font_path).expanduser().resolve()
    if not font_path.strip() or not font.is_file():
        raise ReportPdfError("中文字体文件不存在")

    # WeasyPrint 在 Windows 上还依赖 Pango/GLib 原生运行库。延迟导入可以
    # 保证缺少这些 DLL 时，应用的查询、鉴权和 Markdown 校验能力仍能启动；
    # 真正生成 PDF 时则失败关闭，绝不回退为未经校验的其他文件格式。
    try:
        from weasyprint import CSS, HTML
    except (ImportError, OSError) as exc:
        raise ReportPdfError("报告 PDF 渲染运行库不可用") from exc

    # MarkdownIt 关闭 HTML 后才执行渲染；外层模板中的动态值全部转义。
    body = _markdown_parser().render(markdown)
    local_time = generated_at + timedelta(hours=8)
    document_html = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title></head><body><main class='report'>"
        f"<div class='meta'>生成时间：{local_time:%Y-%m-%d %H:%M}（北京时间）</div>"
        f"{body}"
        "<section class='privacy'><h2>数据来源与隐私说明</h2>"
        "<p>本报告基于已授权的主系统确定性统计生成，智能体只负责归纳和表达。"
        "报告不包含内部数据库编号、访问凭据、对象存储地址或服务地址。</p></section>"
        f"<footer>{escape(template_version)}</footer></main></body></html>"
    )
    font_uri = font.as_uri()
    stylesheet = CSS(
        string=_stylesheet(font_uri),
        url_fetcher=_local_font_fetcher(font_uri, font),
    )
    try:
        content = HTML(
            string=document_html, base_url=None, url_fetcher=_reject_all_resources
        ).write_pdf(stylesheets=[stylesheet])
    except ReportPdfError:
        raise
    except Exception as exc:
        raise ReportPdfError("报告 PDF 渲染失败") from exc

    page_count, _ = inspect_report_pdf(
        content,
        max_bytes=max_bytes,
        max_pages=max_pages,
        template_version=template_version,
        required_title=title,
        forbidden_values=forbidden_values,
    )
    return ReportPdfDocument(
        content=content,
        checksum=sha256(content).hexdigest(),
        size_bytes=len(content),
        page_count=page_count,
        media_type=PDF_MEDIA_TYPE,
        filename=_safe_pdf_filename(filename),
    )


def inspect_report_pdf(
    content: bytes,
    *,
    max_bytes: int,
    max_pages: int,
    template_version: str,
    required_title: str | None = None,
    expected_checksum: str | None = None,
    expected_size: int | None = None,
    expected_pages: int | None = None,
    forbidden_values: tuple[str, ...] = (),
) -> tuple[int, str]:
    """复核 PDF 魔数、边界、摘要、页数、文本和敏感信息。"""

    if not isinstance(content, bytes) or not content.startswith(_PDF_MAGIC):
        raise ReportPdfError("报告文件不是有效 PDF")
    if not content or len(content) > max_bytes:
        raise ReportPdfError("报告 PDF 大小不符合配置上限")
    if expected_size is not None and len(content) != expected_size:
        raise ReportPdfError("报告 PDF 大小与元数据不一致")
    digest = sha256(content).hexdigest()
    if expected_checksum is not None and (
        not _SHA256_PATTERN.fullmatch(expected_checksum)
        or not hmac.compare_digest(digest, expected_checksum)
    ):
        raise ReportPdfError("报告 PDF 摘要与元数据不一致")
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ReportPdfError("报告 PDF 不应加密")
        page_count = len(reader.pages)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except ReportPdfError:
        raise
    except Exception as exc:
        raise ReportPdfError("报告 PDF 结构解析失败") from exc

    if page_count < 1 or page_count > max_pages:
        raise ReportPdfError("报告 PDF 页数不符合配置上限")
    if expected_pages is not None and page_count != expected_pages:
        raise ReportPdfError("报告 PDF 页数与元数据不一致")
    if any(value not in text for value in ("数据来源与隐私说明", template_version)):
        raise ReportPdfError("报告 PDF 缺少必要说明")
    if required_title and required_title not in text:
        raise ReportPdfError("报告 PDF 缺少报告标题")
    if _SENSITIVE_TEXT.search(text):
        raise ReportPdfError("报告 PDF 包含敏感字段或服务地址")
    if any(value and value in text for value in forbidden_values):
        raise ReportPdfError("报告 PDF 包含内部标识")
    return page_count, text


def _local_font_fetcher(font_uri: str, font_path: Path):
    """只允许 CSS 读取配置指定的一个本地字体文件。"""

    def fetch(url: str) -> dict[str, object]:
        if url != font_uri:
            raise ReportPdfError("报告样式尝试读取未授权资源")
        return {"file_obj": font_path.open("rb"), "mime_type": "font/ttf"}

    return fetch


def _reject_all_resources(url: str) -> dict[str, object]:
    """拒绝报告正文中的全部外部资源请求。"""

    raise ReportPdfError("报告正文不允许加载外部资源")


def _safe_pdf_filename(filename: str) -> str:
    """把内部生成的下载文件名限制为安全 ASCII。"""

    name = filename.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:180]
    if not name.lower().endswith(".pdf"):
        name = f"{name or 'learning-report'}.pdf"
    return name


def _stylesheet(font_uri: str) -> str:
    """返回通用中文报告样式，业务内容仍完全来自受控 Markdown。"""

    return f"""
        @font-face {{ font-family: uPilReport; src: url('{font_uri}'); }}
        @page {{
          size: A4; margin: 20mm 18mm 22mm;
          @bottom-center {{ content: "第 " counter(page) " 页";
            font-family: uPilReport; font-size: 8pt; color: #64748b; }}
        }}
        html {{ font-family: uPilReport, sans-serif; color: #1f2937; font-size: 10.5pt; }}
        body {{ margin: 0; line-height: 1.75; }}
        .report {{ max-width: 100%; }}
        .meta {{ color: #64748b; font-size: 9pt; text-align: right; margin-bottom: 8mm; }}
        h1 {{ color: #172554; font-size: 22pt; margin: 0 0 8mm; }}
        h2 {{ color: #0f766e; font-size: 14pt; margin: 7mm 0 2mm; break-after: avoid; }}
        h3 {{ color: #334155; font-size: 12pt; margin: 5mm 0 2mm; break-after: avoid; }}
        p {{ margin: 0 0 3mm; overflow-wrap: anywhere; }}
        ul, ol {{ margin: 0 0 4mm; padding-left: 7mm; }}
        li {{ margin: 1.2mm 0; break-inside: avoid; }}
        blockquote {{ margin: 0 0 5mm; padding: 3mm 4mm; color: #475569;
          background: #f8fafc; border-left: 1.2mm solid #0f766e; }}
        .privacy {{ margin-top: 9mm; padding-top: 4mm; border-top: 0.3mm solid #cbd5e1; }}
        .privacy p, footer {{ color: #64748b; font-size: 8.5pt; }}
        footer {{ margin-top: 6mm; text-align: right; }}
    """
