"""Vue SPA 静态文件托管。"""

from pathlib import Path

from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class SpaStaticFiles(StaticFiles):
    """为 Vue history 路由提供安全的 index.html 回退。"""

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        request_path = scope.get("path", "")
        # 所有已注册 API 都会在静态挂载之前匹配。走到这里的 /api/ 请求一定是
        # 未知或已退役接口，应统一返回 404；不能让 StaticFiles 对 POST 等方法
        # 返回 405，否则调用方可能误以为同一路径仍存在其他可用方法。
        if request_path.startswith("/api/"):
            raise HTTPException(status_code=404, detail="资源不存在")
        path_name = Path(path).name
        is_frontend_route = (
            scope.get("method") in {"GET", "HEAD"}
            and not request_path.startswith("/api/")
            and "." not in path_name
        )
        if is_frontend_route:
            return await super().get_response("index.html", scope)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and is_frontend_route:
                return await super().get_response("index.html", scope)
            raise
