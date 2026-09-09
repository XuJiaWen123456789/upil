"""通过本机 HTTP 调用独立 A2A 学情分析子服务的受控客户端。"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from backend.app.a2a.contracts import A2AQualityResult, A2ATaskRequest, A2ATaskResult
from backend.app.integrations.a2a_client import (
    A2AResultValidationError,
    build_class_learning_report_task,
    build_learning_task,
    build_learning_report_task,
    validate_a2a_result,
)
from backend.app.class_learning_contracts import ClassLearningSummary
from backend.app.learning_contracts import LearningReportSnapshot, LearningSummary


class HttpA2ALearningClient:
    """仅连接本机固定端点的同步 HTTP 客户端。

    LangGraph 当前使用同步节点，因此本阶段选择 httpx.Client。后续将图节点
    全面异步化时，可保持协议不变并替换为 AsyncClient。
    """

    provider = "a2a_http"

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        max_retries: int = 2,
        timeout_seconds: int = 10,
        allowed_hosts: set[str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if max_retries < 0 or max_retries > 2:
            raise ValueError("本阶段最多允许 2 次重试")
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("A2A 超时时间必须在 1 至 60 秒之间")
        if len(service_token) < 16:
            raise ValueError("local_http 模式必须配置至少 16 个字符的服务令牌")
        self.base_url = self._validate_local_base_url(
            base_url,
            allowed_hosts=allowed_hosts or {"127.0.0.1", "localhost", "::1"},
        )
        self.service_token = service_token
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @staticmethod
    def _validate_local_base_url(base_url: str, *, allowed_hosts: set[str]) -> str:
        """只允许 HTTP 地址和显式主机白名单，防止配置被用于 SSRF。"""

        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("A2A local_http 地址必须是无凭据的本机 HTTP 回环地址")
        return base_url.rstrip("/")

    def analyze(self, snapshot: LearningSummary, *, request_id: str) -> A2ATaskResult:
        """发送学情摘要任务；只对网络超时重试，其他失败立即安全降级。"""

        task = build_learning_task(
            snapshot, request_id=request_id, timeout_seconds=self.timeout_seconds
        )
        return self._execute_task(task)

    def generate_report(
        self, snapshot: LearningReportSnapshot, *, request_id: str
    ) -> A2ATaskResult:
        """发送家长报告任务；与摘要任务共用同一 A2A HTTP 端点。"""

        task = build_learning_report_task(
            snapshot, request_id=request_id, timeout_seconds=self.timeout_seconds
        )
        return self._execute_task(task)

    def generate_class_report(
        self, snapshot: ClassLearningSummary, *, request_id: str
    ) -> A2ATaskResult:
        """通过受控 HTTP 端点请求班级报表。"""

        task = build_class_learning_report_task(
            snapshot, request_id=request_id, timeout_seconds=self.timeout_seconds
        )
        return self._execute_task(task)

    def _execute_task(self, task: A2ATaskRequest) -> A2ATaskResult:
        """发送一个标准 A2A 任务，并统一处理超时、校验与安全降级。"""

        attempts = 0
        while True:
            attempts += 1
            try:
                with httpx.Client(
                    base_url=self.base_url,
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                    headers={"X-A2A-Service-Token": self.service_token},
                ) as client:
                    response = client.post(
                        "/internal/a2a/tasks",
                        json=task.model_dump(mode="json"),
                    )
                # 401、422、500 等状态不是可恢复超时，不能形成重试风暴。
                response.raise_for_status()
                result = A2ATaskResult.model_validate(response.json())
                validated = validate_a2a_result(result, task)
                if validated.status == "failed":
                    return validated.model_copy(
                        update={
                            "quality": A2AQualityResult(
                                passed=False, issues=["远程子节点返回失败状态"]
                            )
                        }
                    )
                return validated.model_copy(
                    update={"quality": A2AQualityResult(passed=True, issues=[])}
                )
            except httpx.TimeoutException:
                if attempts <= self.max_retries:
                    continue
                return self._failed_result(task, "学情分析 HTTP 服务超时，已达到重试上限")
            except (
                httpx.HTTPError,
                ValueError,
                ValidationError,
                A2AResultValidationError,
            ):
                # 不记录响应正文和请求体，避免脱敏快照或服务信息进入日志。
                return self._failed_result(task, "学情分析 HTTP 服务不可用或响应校验失败")

    @staticmethod
    def _failed_result(task: A2ATaskRequest, message: str) -> A2ATaskResult:
        """构造可被 LangGraph 识别的安全失败结果。"""

        return A2ATaskResult(
            task_id=task.task_id,
            correlation_id=task.correlation_id,
            status="failed",
            message=message,
            quality=A2AQualityResult(passed=False, issues=[message]),
            handoff_required=True,
            retryable=False,
        )
