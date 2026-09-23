"""HTTP 响应层的公共时间契约。

数据库中的 ``TIMESTAMP WITHOUT TIME ZONE`` 字段统一保存 UTC 裸值。Python 读取后
得到的 ``datetime`` 因此没有 ``tzinfo``，但它的业务语义仍然是 UTC。响应层必须补全
这一语义，避免浏览器把无偏移时间误当成本地时间，造成北京时间显示少 8 小时。
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, field_serializer


def serialize_utc_datetime(value: datetime) -> str:
    """把业务时间规范化为带 ``Z`` 的 ISO 8601 UTC 字符串。

    无时区值来自项目现有 UTC 数据列，不能按服务器本地时区解释；带时区值则先换算
    为 UTC。这里只改变 HTTP 序列化结果，不改变数据库存储和 Python 领域对象。
    """

    utc_value = (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
    return utc_value.isoformat().replace("+00:00", "Z")


class UtcResponseModel(BaseModel):
    """所有包含业务时间的 HTTP 响应模型基类。"""

    @field_serializer("*", check_fields=False, when_used="json")
    def serialize_response_field(self, value: Any) -> Any:
        """只接管时间字段，其余字段继续使用 Pydantic 的标准序列化。"""

        if isinstance(value, datetime):
            return serialize_utc_datetime(value)
        return value
