"""MinIO 私有报告对象存储适配器。

当前产品只使用 MinIO 保存固定模板学情报告 PDF。数据库继续保存对象键、
摘要、大小和页数等可查询元数据，下载请求必须先经过后端业务鉴权，不能
向浏览器暴露存储服务凭据或可长期复用的对象地址。
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any
from urllib.parse import quote

from backend.app.config import Settings, get_settings


REPORT_PDF_MEDIA_TYPE = "application/pdf"


class MinioMediaStore:
    """使用 S3 兼容的 MinIO 保存和读取私有报告。

    类名为了兼容报告服务和既有测试的稳定导入路径暂不改动；该类已经不再
    提供图片上传、审核、预签名 URL 等教师媒体工作台能力。
    """

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        """创建报告存储实例；client 参数供离线测试注入假的 MinIO 客户端。"""

        self.settings = settings or get_settings()
        if client is None:
            try:
                from minio import Minio
            except ImportError as exc:
                raise RuntimeError(
                    "MinIO 报告存储需要可选依赖，请执行 uv pip install -e \".[storage]\""
                ) from exc
            client = Minio(
                self.settings.minio_endpoint,
                access_key=self.settings.minio_access_key,
                secret_key=self.settings.minio_secret_key,
                secure=self.settings.minio_secure,
                region=self.settings.minio_region,
            )
        self.client = client

    def ensure_report_bucket(self) -> None:
        """按需创建私有报告桶；生产也可由部署脚本预创建并设置最小权限。"""

        if not self.client.bucket_exists(self.settings.report_pdf_bucket):
            self.client.make_bucket(
                self.settings.report_pdf_bucket, location=self.settings.minio_region
            )

    def put_report_pdf(
        self,
        content: bytes,
        *,
        task_id: str,
        filename: str,
        checksum: str,
    ) -> str:
        """上传已生成并校验的 PDF，返回仅供数据库保存的私有对象键。

        对象键由安全任务 ID 和内容摘要确定，重试会覆盖同一个对象，不会产生
        无界孤儿文件。该方法不返回 URL，下载只能通过后端鉴权代理完成。
        """

        self._validate_report_pdf(content, checksum)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,63}", task_id):
            raise ValueError("报告任务 ID 不合法")
        safe_name = self._safe_filename(filename)
        if not safe_name.lower().endswith(".pdf"):
            raise ValueError("报告文件名必须使用 .pdf 扩展名")
        self.ensure_report_bucket()
        object_key = f"reports/{task_id}/{checksum}.pdf"
        self.client.put_object(
            self.settings.report_pdf_bucket,
            object_key,
            io.BytesIO(content),
            length=len(content),
            content_type=REPORT_PDF_MEDIA_TYPE,
            metadata={
                "x-amz-meta-sha256": checksum,
                "x-amz-meta-filename": self._encode_metadata(safe_name),
            },
        )
        return object_key

    def get_report_pdf(self, object_key: str) -> bytes | None:
        """从私有报告桶读取 PDF；非法键、对象缺失和故障统一返回 None。"""

        if not self._valid_report_object_key(object_key):
            return None
        try:
            response = self.client.get_object(self.settings.report_pdf_bucket, object_key)
            try:
                content = response.read(self.settings.report_pdf_max_bytes + 1)
                return content if isinstance(content, bytes) else bytes(content)
            finally:
                response.close()
                response.release_conn()
        except Exception:
            # 调用层只返回固定错误，不向客户端泄漏桶名、对象键或 MinIO 地址。
            return None

    def delete_report_pdf(self, object_key: str) -> None:
        """仅删除 reports/ 下的报告对象，用于数据库事务失败后的补偿。"""

        if not self._valid_report_object_key(object_key):
            return
        self.client.remove_object(self.settings.report_pdf_bucket, object_key)

    def _validate_report_pdf(self, content: bytes, checksum: str) -> None:
        """在对象存储边界再次检查 PDF 魔数、大小和调用方摘要。"""

        if not isinstance(content, bytes) or not content.startswith(b"%PDF-"):
            raise ValueError("报告内容不是有效 PDF")
        if len(content) > self.settings.report_pdf_max_bytes:
            raise ValueError("报告 PDF 大小超过配置上限")
        digest = hashlib.sha256(content).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", checksum) or digest != checksum:
            raise ValueError("报告 PDF 摘要不一致")

    @staticmethod
    def _valid_report_object_key(object_key: str) -> bool:
        """报告对象键必须匹配服务端固定结构，拒绝任意键和路径穿越。"""

        return bool(
            isinstance(object_key, str)
            and re.fullmatch(
                r"reports/[A-Za-z0-9][A-Za-z0-9_.:-]{2,63}/[0-9a-f]{64}\.pdf",
                object_key,
            )
        )

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """只保留文件名和安全字符，防止元数据中携带路径。"""

        name = filename.replace("\\", "/").split("/")[-1]
        name = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]", "_", name)
        return name[:180] or "learning-report.pdf"

    @staticmethod
    def _encode_metadata(value: str) -> str:
        """将中文元数据编码为可安全放入 HTTP Header 的 ASCII 字符串。"""

        return quote(value, safe="-_.~")
