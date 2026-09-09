"""独立运行的本地 Mock A2A 学情分析子服务。

启动示例：
    python -m uvicorn backend.app.a2a.mock_server:app --host 127.0.0.1 --port 8101

该服务只接受固定 A2A 协议任务，不连接数据库、RAGFlow、MinIO 或 Docker
Socket，也不执行用户代码。它仅用于本地跨进程联调和答辩演示。
"""

from __future__ import annotations

import hmac

from fastapi import FastAPI, Header, HTTPException

from backend.app.a2a.contracts import A2ATaskRequest, A2ATaskResult
from backend.app.a2a.mock_learning_agent import MockLearningAnalysisAgent
from backend.app.a2a.task_store import A2ATaskStore, TaskConflictError
from backend.app.config import get_settings


app = FastAPI(
    title="uPil Local A2A Learning Agent",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)
agent = MockLearningAnalysisAgent()
# 任务仓库的治理参数由配置统一控制，避免不同启动方式使用不一致的 TTL。
_settings = get_settings()
task_store = A2ATaskStore(
    ttl_seconds=_settings.a2a_learning_task_ttl_seconds,
    max_entries=_settings.a2a_learning_task_max_entries,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """返回不含配置和凭据的最小健康状态。"""

    return {
        "status": "ok",
        "service": "uPil Local A2A Learning Agent",
        "protocol_version": "upil-a2a/1.0",
    }


@app.post("/internal/a2a/tasks", response_model=A2ATaskResult)
async def create_task(
    task: A2ATaskRequest,
    x_a2a_service_token: str | None = Header(default=None),
) -> A2ATaskResult:
    """校验内部服务令牌后处理固定的只读学情摘要任务。

    请求模型拒绝未知字段，因此 command、SQL、URL 等任意执行参数会在
    到达处理器前被 FastAPI/Pydantic 以 422 拒绝。
    """

    # 创建、查询和指标端点统一使用同一鉴权逻辑，避免出现安全策略漂移。
    _require_service_token(x_a2a_service_token)

    try:
        result, _deduplicated = task_store.execute(task, agent.process)
    except TaskConflictError as exc:
        # 同一个 task_id 携带不同内容时返回冲突，不执行第二份任务。
        raise HTTPException(status_code=409, detail="task_id 与任务内容冲突") from exc
    return result


@app.get("/internal/a2a/tasks/{task_id}", response_model=A2ATaskResult)
async def get_task(
    task_id: str,
    x_a2a_service_token: str | None = Header(default=None),
) -> A2ATaskResult:
    """按任务 ID 查询已完成的 A2A 结果，不返回原始请求快照。"""

    _require_service_token(x_a2a_service_token)
    result = task_store.get(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return result


@app.get("/internal/a2a/metrics")
async def get_metrics(
    x_a2a_service_token: str | None = Header(default=None),
) -> dict[str, int]:
    """返回内部计数指标；指标中不包含问题、学员标识或 Artifact 正文。"""

    _require_service_token(x_a2a_service_token)
    return task_store.metrics()


def _require_service_token(token: str | None) -> None:
    """统一校验内部端点的环境、令牌长度和令牌值。"""

    settings = get_settings()
    if settings.app_env.lower() not in {"development", "test", "local", "staging"}:
        raise HTTPException(status_code=404, detail="接口不存在")
    expected_token = settings.a2a_learning_service_token
    if len(expected_token) < 16:
        raise HTTPException(status_code=503, detail="A2A 子服务尚未完成安全配置")
    if token is None or not hmac.compare_digest(token, expected_token):
        raise HTTPException(status_code=401, detail="A2A 服务认证失败")
