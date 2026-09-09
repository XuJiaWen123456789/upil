"""MinIO 图片对象存储适配器的离线契约测试。"""

import pytest

from backend.app.config import Settings
from backend.app.integrations.minio import ALLOWED_IMAGE_TYPES, MinioMediaStore


# 最小 PNG 文件头用于离线验证类型契约，不需要把真实图片提交到测试目录。
# 控制在默认测试上限 10 字节以内；真实上传仍由大小和文件签名校验保护。
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"d"


def make_store(settings: Settings | None = None) -> MinioMediaStore:
    """绕过真实 MinIO 连接构造对象，只测试本地图片校验规则。"""

    store = MinioMediaStore.__new__(MinioMediaStore)
    store.settings = settings or Settings(media_max_bytes=10)
    return store


def test_allowed_image_types_are_explicit() -> None:
    """媒体白名单应明确限制为项目支持的图片类型。"""

    assert {"image/jpeg", "image/png", "image/webp", "image/svg+xml"} == ALLOWED_IMAGE_TYPES


def test_image_validation_accepts_non_empty_allowed_content() -> None:
    """符合大小和类型要求的图片字节应通过基础契约校验。"""

    make_store()._validate_image(PNG_BYTES, "image/png")


def test_image_validation_rejects_empty_content() -> None:
    """空文件不能进入媒体存储。"""

    with pytest.raises(ValueError, match="不能为空"):
        make_store()._validate_image(b"", "image/png")


def test_image_validation_rejects_unsupported_type() -> None:
    """媒体桶不接受任意文件类型。"""

    with pytest.raises(ValueError, match="不支持"):
        make_store()._validate_image(b"demo", "application/pdf")


def test_image_validation_rejects_oversized_content() -> None:
    """超过配置上限的内容应在上传前被拦截。"""

    with pytest.raises(ValueError, match="超过配置上限"):
        make_store(Settings(media_max_bytes=3))._validate_image(b"1234", "image/png")


def test_put_image_uses_private_object_key_and_hash() -> None:
    """上传摘要应包含对象键和哈希，但不把二进制放入业务响应。"""

    class FakeMinio:
        def __init__(self) -> None:
            self.calls = []

        def bucket_exists(self, bucket: str) -> bool:
            return True

        def put_object(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    client = FakeMinio()
    store = MinioMediaStore(Settings(media_max_bytes=100), client=client)
    summary = store.put_image(
        PNG_BYTES,
        filename="..\\teacher.png",
        media_type="image/png",
        title="演示教师",
        alt_text="教师演示图片",
        source_document="教师与校区环境.md",
    )
    assert summary.object_key.startswith("images/")
    assert ".." not in summary.object_key
    assert summary.filename == "teacher.png"
    assert summary.sha256
    assert len(client.calls) == 1
    metadata = client.calls[0][1]["metadata"]
    assert all(value.isascii() for value in metadata.values())
    assert "%E6%BC%94%E7%A4%BA%E6%95%99%E5%B8%88" in metadata["x-amz-meta-title"]
