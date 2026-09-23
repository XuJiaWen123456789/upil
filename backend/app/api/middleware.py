"""HTTP 中间件。"""

import re
from uuid import uuid4

from fastapi import Request


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


async def attach_request_id(request: Request, call_next):
    """透传合法追踪 ID，否则生成新 ID，并通过响应头返回。"""

    incoming = request.headers.get("X-Request-ID", "")
    request_id = (
        incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else f"req_{uuid4().hex}"
    )
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
