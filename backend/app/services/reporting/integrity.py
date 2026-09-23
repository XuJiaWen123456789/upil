"""报告正文、PDF 元数据和错误信息的安全校验。

本模块只处理纯数据，不发起数据库查询，也不访问 MinIO，便于在写入与
下载两个边界复用相同的安全口径。
"""

from hashlib import sha256
import hmac
import re

from backend.app.models import ReportArtifact, ReportTask

from .exceptions import ReportArtifactIntegrityError, ReportTaskError


PDF_OBJECT_KEY_PATTERN = re.compile(
    r"reports/[A-Za-z0-9][A-Za-z0-9_.:-]{2,63}/[0-9a-f]{64}\.pdf"
)
PDF_CHECKSUM_PATTERN = re.compile(r"[0-9a-f]{64}")
PDF_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,180}\.pdf", re.IGNORECASE)
_LEGACY_MARKDOWN_FORBIDDEN = ("#!/", "import os", "subprocess", "powershell", "cmd.exe")


def content_checksum(content: str) -> str:
    """使用 SHA-256 生成正文校验和，供幂等比对和下载审计使用。"""

    return sha256(content.encode("utf-8")).hexdigest()


def constant_time_checksum_matches(content: str, expected: str) -> bool:
    """恒定时间比较摘要，避免在最终下载边界使用普通字符串比较。"""

    return hmac.compare_digest(content_checksum(content), expected)

def validate_legacy_markdown_write(artifact_name: str, content: str) -> None:
    """校验旧 Markdown 兼容写入，防止历史接口绕过当前内容安全边界。

    新报告只保存 PDF，不会调用 complete_report_task；保留该函数是为了
    读取和兼容阶段 15-A-1 的旧数据。它仍然可能被迁移脚本或旧调用方使用，
    因此不能因为远程协议已移除就允许命令、脚本和本地路径落库。
    """

    if not isinstance(artifact_name, str) or not artifact_name.strip():
        raise ReportTaskError("历史 Markdown 产物名称不能为空")
    if not isinstance(content, str) or not content.strip():
        raise ReportTaskError("历史 Markdown 产物正文不能为空")
    lowered = content.lower()
    if any(token in lowered for token in _LEGACY_MARKDOWN_FORBIDDEN):
        raise ReportTaskError("历史 Markdown 产物不得包含可执行命令")
    if "\\" in content or re.search(
        r"(?i)(?<![a-z])(?:[a-z]:|/)(?:[^\n ]+/|[^\n ]+\\)", content
    ):
        raise ReportTaskError("历史 Markdown 产物不得暴露本地文件路径")
    try:
        from backend.app.services.markdown_pdf import validate_safe_markdown

        validate_safe_markdown(content)
    except Exception as exc:
        raise ReportTaskError("历史 Markdown 产物未通过内容安全校验") from exc


def safe_error_message(message: str) -> str:
    """生成可持久化的单行错误说明，并移除凭据与内部路径。"""

    safe_message = " ".join(message.split())
    safe_message = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret)"
        r"\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        safe_message,
    )
    safe_message = re.sub(
        r"(?i)\bbearer\s+[^\s,;]+", "Bearer [REDACTED]", safe_message
    )
    safe_message = re.sub(
        r"(?i)\b[A-Z]:\\[^\s,;]+", "[REDACTED_PATH]", safe_message
    )
    safe_message = re.sub(
        r"(?<!:)\/(?:home|tmp|var|opt|root|Users)\/[^\s,;]+",
        "[REDACTED_PATH]",
        safe_message,
        flags=re.IGNORECASE,
    )
    return safe_message[:500]


def validate_pdf_write_metadata(
    *,
    object_key: str,
    checksum: str,
    filename: str,
    size_bytes: int,
    page_count: int,
) -> None:
    """在 PDF 元数据写库前执行严格契约校验。"""

    if not PDF_OBJECT_KEY_PATTERN.fullmatch(object_key):
        raise ReportTaskError("PDF 对象键不符合报告契约")
    if not PDF_CHECKSUM_PATTERN.fullmatch(checksum):
        raise ReportTaskError("PDF 校验和不符合报告契约")
    if (
        not PDF_FILENAME_PATTERN.fullmatch(filename)
        or size_bytes <= 0
        or page_count <= 0
    ):
        raise ReportTaskError("PDF 元数据不符合报告契约")


def validate_downloadable_pdf(artifact: ReportArtifact) -> None:
    """在返回下载流前复核关系库中的 PDF 元数据。"""

    if (
        artifact.content is not None
        or artifact.media_type != "application/pdf"
        or not artifact.object_key
        or not PDF_OBJECT_KEY_PATTERN.fullmatch(artifact.object_key)
        or not artifact.checksum
        or not PDF_CHECKSUM_PATTERN.fullmatch(artifact.checksum)
        or not artifact.filename
        or not PDF_FILENAME_PATTERN.fullmatch(artifact.filename)
        or not isinstance(artifact.size_bytes, int)
        or artifact.size_bytes <= 0
        or not isinstance(artifact.page_count, int)
        or artifact.page_count <= 0
    ):
        raise ReportArtifactIntegrityError("报告 PDF 元数据异常")


def validate_downloadable_markdown(
    task: ReportTask, artifact: ReportArtifact
) -> None:
    """复核历史 Markdown 产物，保留旧任务的受控下载能力。"""

    if not artifact.content:
        raise ReportArtifactIntegrityError("报告 Markdown 正文异常")
    if (
        not artifact.checksum
        or not PDF_CHECKSUM_PATTERN.fullmatch(artifact.checksum)
    ):
        raise ReportArtifactIntegrityError("报告 Markdown 校验和异常")
    if not constant_time_checksum_matches(artifact.content, artifact.checksum):
        raise ReportArtifactIntegrityError("报告 Markdown 完整性校验失败")

    # 匿名 learner_ref 也是内部引用，不能因历史兼容而进入下载正文。
    learner_ref = task.scope.get("learner_ref") if isinstance(task.scope, dict) else None
    if isinstance(learner_ref, str) and learner_ref and learner_ref in artifact.content:
        raise ReportArtifactIntegrityError("报告产物包含内部学员引用")

    # 历史 Markdown 仍使用当前报告语法白名单复核，不再依赖已经移除的
    # 远程协议数据类型。延迟导入避免报告领域包形成循环依赖。
    try:
        from backend.app.services.markdown_pdf import validate_safe_markdown

        validate_safe_markdown(artifact.content)
    except Exception as exc:
        raise ReportArtifactIntegrityError("报告产物未通过内容安全校验") from exc
