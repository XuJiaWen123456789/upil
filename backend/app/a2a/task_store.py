"""本地 A2A 任务状态、幂等和基础指标存储。

该模块使用线程安全内存存储，只适合阶段 13-E 的单机演示和自动化测试。
生产环境应替换为 Redis 或 PostgreSQL，并保留相同的幂等语义和查询接口。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from threading import RLock
from typing import Callable

from backend.app.a2a.contracts import A2ATaskRequest, A2ATaskResult


class TaskConflictError(ValueError):
    """同一 task_id 被不同任务内容复用。"""


@dataclass(slots=True)
class StoredTask:
    """任务仓库内部记录，不直接暴露输入快照。"""

    fingerprint: str
    result: A2ATaskResult
    created_at: float
    updated_at: float


class A2ATaskStore:
    """带 TTL、容量上限和幂等校验的进程内任务仓库。"""

    def __init__(self, *, ttl_seconds: int = 1800, max_entries: int = 1000) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("任务 TTL 和容量必须为正数")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, StoredTask] = {}
        self._lock = RLock()
        self._metrics = {
            "received": 0,
            "executed": 0,
            "deduplicated": 0,
            "conflicts": 0,
            "completed": 0,
            "failed": 0,
        }

    @staticmethod
    def fingerprint(task: A2ATaskRequest) -> str:
        """对规范化任务计算摘要，不保存原始学情快照作为指标。"""

        encoded = json.dumps(
            task.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _prune_locked(self, now: float, *, make_room: bool = False) -> None:
        """删除过期任务；新增任务前可按需为容量上限腾出位置。"""

        expired = [
            task_id
            for task_id, entry in self._entries.items()
            if now - entry.updated_at >= self.ttl_seconds
        ]
        for task_id in expired:
            self._entries.pop(task_id, None)
        # 只有确认要写入新任务时才腾位置，不能在 get/metrics 时误删当前缓存。
        if make_room:
            while len(self._entries) >= self.max_entries:
                oldest = min(
                    self._entries, key=lambda key: self._entries[key].updated_at
                )
                self._entries.pop(oldest, None)

    def execute(
        self,
        task: A2ATaskRequest,
        processor: Callable[[A2ATaskRequest], A2ATaskResult],
    ) -> tuple[A2ATaskResult, bool]:
        """按 task_id 执行一次任务；返回结果和是否命中幂等缓存。"""

        now = time.monotonic()
        digest = self.fingerprint(task)
        with self._lock:
            self._metrics["received"] += 1
            self._prune_locked(now)
            existing = self._entries.get(task.task_id)
            if existing is not None:
                existing.updated_at = now
                if existing.fingerprint != digest:
                    self._metrics["conflicts"] += 1
                    raise TaskConflictError("task_id 已绑定其他任务内容")
                self._metrics["deduplicated"] += 1
                return existing.result, True

            # 仅在确定是新 task_id 时淘汰最旧记录，保留重复任务的幂等缓存。
            self._prune_locked(now, make_room=True)

            # 持有锁执行固定 Mock 任务，确保同一 task_id 不会并发重复执行。
            result = processor(task)
            self._prune_locked(now)
            self._entries[task.task_id] = StoredTask(
                fingerprint=digest,
                result=result,
                created_at=now,
                updated_at=time.monotonic(),
            )
            self._metrics["executed"] += 1
            self._metrics[result.status] = self._metrics.get(result.status, 0) + 1
            return result, False

    def get(self, task_id: str) -> A2ATaskResult | None:
        """按 task_id 获取尚未过期的任务结果。"""

        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            entry = self._entries.get(task_id)
            if entry is None:
                return None
            entry.updated_at = now
            return entry.result

    def metrics(self) -> dict[str, int]:
        """返回不含任务正文、学员标识和服务令牌的计数指标。"""

        with self._lock:
            self._prune_locked(time.monotonic())
            return {**self._metrics, "stored": len(self._entries)}

    def clear(self) -> None:
        """测试或本地重启时清空任务状态。"""

        with self._lock:
            self._entries.clear()
            for key in self._metrics:
                self._metrics[key] = 0
