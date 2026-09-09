"""MinIO 媒体对象存储适配器。

MinIO 只保存图片、PDF 和其他非结构化文件原件；可检索的标题、替代文本、
来源和权限信息由 RAGFlow 与 PostgreSQL 分别承担。适配器使用可选 minio
依赖，未安装依赖时不会影响不使用媒体上传功能的核心 API 启动。
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from backend.app.config import Settings, get_settings
from backend.app.schemas import MediaAssetSummary, MediaVisibility


# 上传接口只接受明确的图片类型；正式环境还应检查文件魔数，不能只信任请求头。
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/svg+xml"}


class MinioMediaStore:
    """使用 S3 兼容的 MinIO 保存和读取媒体对象。"""

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        """创建存储实例；client 参数用于离线测试注入假的 MinIO 客户端。"""

        self.settings = settings or get_settings()
        if client is None:
            try:
                from minio import Minio
            except ImportError as exc:
                raise RuntimeError(
                    "MinIO 媒体存储需要可选依赖，请执行 uv pip install -e \".[media]\""
                ) from exc
            client = Minio(
                self.settings.minio_endpoint,
                access_key=self.settings.minio_access_key,
                secret_key=self.settings.minio_secret_key,
                secure=self.settings.minio_secure,
                region=self.settings.minio_region,
            )
        self.client = client

    def ensure_bucket(self) -> None:
        """按需创建媒体桶；生产环境也可通过部署脚本预创建并设置最小权限。"""

        if not self.client.bucket_exists(self.settings.minio_bucket):
            self.client.make_bucket(self.settings.minio_bucket, location=self.settings.minio_region)

    def put_image(
        self,
        content: bytes,
        *,
        filename: str,
        media_type: str,
        title: str,
        alt_text: str,
        source_document: str,
        visibility: MediaVisibility = "public_faq",
        review_status: str = "pending",
    ) -> MediaAssetSummary:
        """校验并上传图片，返回可写入 PostgreSQL 的媒体元数据摘要。"""

        self._validate_image(content, media_type)
        # 上传前按需创建私有桶，首次联调无需手工登录 MinIO Console 建桶。
        self.ensure_bucket()
        asset_id = uuid.uuid4().hex
        safe_name = self._safe_filename(filename)
        object_key = f"images/{asset_id}/{safe_name}"
        digest = hashlib.sha256(content).hexdigest()
        metadata = {
            # S3 用户元数据最终会进入 HTTP Header；中文必须先编码成 ASCII。
            "x-amz-meta-title": self._encode_metadata(title[:200]),
            "x-amz-meta-alt-text": self._encode_metadata(alt_text[:500]),
            "x-amz-meta-source-document": self._encode_metadata(source_document[:300]),
            "x-amz-meta-visibility": self._encode_metadata(visibility),
            "x-amz-meta-review-status": self._encode_metadata(review_status),
            "x-amz-meta-sha256": digest,
        }
        self.client.put_object(
            self.settings.minio_bucket,
            object_key,
            io.BytesIO(content),
            length=len(content),
            content_type=media_type,
            metadata=metadata,
        )
        return MediaAssetSummary(
            asset_id=asset_id,
            object_key=object_key,
            filename=safe_name,
            media_type=media_type,
            title=title[:200],
            alt_text=alt_text[:500],
            source_document=source_document[:300],
            visibility=visibility,
            sha256=digest,
            size_bytes=len(content),
            review_status=review_status,
        )

    def delete_object(self, object_key: str) -> None:
        """删除对象，用于数据库写入失败时清理孤儿文件。"""

        if not object_key.startswith("images/") or ".." in object_key:
            return
        self.client.remove_object(self.settings.minio_bucket, object_key)

    def create_presigned_url(self, object_key: str, expires_seconds: int | None = None) -> str:
        """生成短时访问地址；调用方必须先完成登录态和可见范围校验。"""

        seconds = expires_seconds or self.settings.minio_presigned_url_seconds
        return self.client.presigned_get_object(
            self.settings.minio_bucket,
            object_key,
            expires=timedelta(seconds=seconds),
        )

    def get_image(self, object_key: str) -> tuple[bytes, dict[str, Any]] | None:
        """读取对象内容和 MinIO 元数据；非法键或对象不存在时返回 None。"""

        if not object_key.startswith("images/") or ".." in object_key:
            return None
        try:
            response = self.client.get_object(self.settings.minio_bucket, object_key)
            try:
                return response.read(), dict(getattr(response, "headers", {}) or {})
            finally:
                response.close()
                response.release_conn()
        except Exception:
            # 对外隐藏存储服务细节，具体异常应由调用层记录结构化日志。
            return None

    def _validate_image(self, content: bytes, media_type: str) -> None:
        """执行大小、类型和基础文件签名校验，避免把任意文件写入媒体桶。"""

        if not isinstance(content, bytes) or not content:
            raise ValueError("图片内容不能为空")
        if len(content) > self.settings.media_max_bytes:
            raise ValueError("图片大小超过配置上限")
        if media_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError(f"不支持的图片类型：{media_type}")

        # Content-Type 来自客户端，必须结合文件头校验，避免把脚本或其他文件伪装成图片。
        signatures = {
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        }
        if media_type in signatures and not signatures[media_type]:
            raise ValueError("图片内容与声明类型不匹配")

        if media_type == "image/svg+xml":
            # SVG 可包含脚本和外链资源；当前阶段只接受简单静态 SVG，后续还应接入专业消毒器。
            try:
                svg_text = content.decode("utf-8").lower()
            except UnicodeDecodeError as exc:
                raise ValueError("SVG 文件必须使用 UTF-8 编码") from exc
            if "<svg" not in svg_text:
                raise ValueError("SVG 内容无效")
            if re.search(r"<script|javascript:|<iframe|<object|<foreignobject|\son[a-z]+\s*=", svg_text):
                raise ValueError("SVG 包含不允许的脚本或事件属性")

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """只保留文件名部分和安全字符，避免用户输入形成路径穿越。"""

        name = filename.replace("\\", "/").split("/")[-1]
        name = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]", "_", name)
        return name[:180] or "upload.bin"

    @staticmethod
    def _encode_metadata(value: str) -> str:
        """将用户元数据编码为可安全放入 HTTP Header 的 ASCII 字符串。"""

        # quote 使用 UTF-8 百分号编码；对象元数据是辅助信息，权威中文原文保存在 PostgreSQL。
        return quote(value, safe="-_.~")
