"""阶段 13-E：任务幂等、TTL、容量治理和并发安全测试。"""

from __future__ import annotations

import threading
import time

import pytest

from backend.app.a2a.contracts import (
    A2AArtifact,
    A2AQualityResult,
    A2ATaskConstraints,
    A2ATaskRequest,
    A2ATaskResult,
    LearningAnalysisInput,
)
from backend.app.a2a.task_store import A2ATaskStore, TaskConflictError


def make_task(task_id: str = "task_store_001", *, hours: int = 8) -> A2ATaskRequest:
    """构造不含真实身份的固定测试任务。"""

    return A2ATaskRequest(
        task_id=task_id,
        correlation_id=f"req_{task_id}",
        skill="learning_summary",
        input=LearningAnalysisInput(
            learner_ref="learner_ref_demo_001",
            period="recent_30_days",
            metrics=["completed_hours"],
            attendance_rate=0.9,
            completed_hours=hours,
        ),
        constraints=A2ATaskConstraints(
            max_runtime_seconds=10,
            output_format="markdown_report",
            no_external_network=True,
            no_side_effects=True,
        ),
    )


def make_result(task: A2ATaskRequest) -> A2ATaskResult:
    """构造最小合法结果，避免测试依赖真实 Agent。"""

    artifact = A2AArtifact(
        artifact_id=f"artifact_{task.task_id}",
        media_type="text/markdown",
        name="learning-summary.md",
        content_ref=f"artifact://{task.task_id}",
        content="# 演示学情摘要\n\n仅用于自动化测试。",
    )
    return A2ATaskResult(
        task_id=task.task_id,
        correlation_id=task.correlation_id,
        status="completed",
        message="任务已完成",
        artifacts=[artifact],
        quality=A2AQualityResult(passed=True),
    )


def test_same_task_is_executed_once_and_returns_cached_result() -> None:
    """相同 task_id 和内容重复提交时，处理器只能执行一次。"""

    store = A2ATaskStore(ttl_seconds=60, max_entries=10)
    calls = 0

    def processor(task: A2ATaskRequest) -> A2ATaskResult:
        nonlocal calls
        calls += 1
        return make_result(task)

    first, first_deduplicated = store.execute(make_task(), processor)
    second, second_deduplicated = store.execute(make_task(), processor)

    assert first.task_id == second.task_id
    assert first_deduplicated is False
    assert second_deduplicated is True
    assert calls == 1
    assert store.metrics()["executed"] == 1
    assert store.metrics()["deduplicated"] == 1


def test_same_task_id_with_different_content_is_conflict() -> None:
    """同一 task_id 不能被不同任务内容覆盖。"""

    store = A2ATaskStore(ttl_seconds=60, max_entries=10)
    calls = 0

    def processor(task: A2ATaskRequest) -> A2ATaskResult:
        nonlocal calls
        calls += 1
        return make_result(task)

    store.execute(make_task(hours=8), processor)
    with pytest.raises(TaskConflictError):
        store.execute(make_task(hours=9), processor)

    assert calls == 1
    assert store.get("task_store_001") is not None
    assert store.metrics()["conflicts"] == 1


def test_expired_task_is_not_returned() -> None:
    """超过 TTL 的结果不可继续作为幂等缓存使用。"""

    store = A2ATaskStore(ttl_seconds=0.01, max_entries=10)
    store.execute(make_task(), make_result)
    time.sleep(0.03)

    assert store.get("task_store_001") is None
    assert store.metrics()["stored"] == 0


def test_capacity_evicts_oldest_task() -> None:
    """容量达到上限时淘汰最早记录，避免内存无限增长。"""

    store = A2ATaskStore(ttl_seconds=60, max_entries=2)
    store.execute(make_task("task_store_001"), make_result)
    time.sleep(0.005)
    store.execute(make_task("task_store_002"), make_result)
    time.sleep(0.005)
    store.execute(make_task("task_store_003"), make_result)

    assert store.get("task_store_001") is None
    assert store.get("task_store_002") is not None
    assert store.get("task_store_003") is not None
    assert store.metrics()["stored"] == 2


def test_metrics_are_redacted_and_clear_resets_state() -> None:
    """指标只暴露计数，clear 后不残留任务或历史计数。"""

    store = A2ATaskStore(ttl_seconds=60, max_entries=10)
    store.execute(make_task(), make_result)
    metrics = store.metrics()

    assert set(metrics) == {
        "received",
        "executed",
        "deduplicated",
        "conflicts",
        "completed",
        "failed",
        "stored",
    }
    assert all(isinstance(value, int) for value in metrics.values())
    assert "learner_ref_demo_001" not in str(metrics)
    assert "task_store_001" not in str(metrics)

    store.clear()
    assert store.metrics() == {
        "received": 0,
        "executed": 0,
        "deduplicated": 0,
        "conflicts": 0,
        "completed": 0,
        "failed": 0,
        "stored": 0,
    }


def test_concurrent_same_task_executes_once() -> None:
    """并发重复提交同一 task_id 时，锁保证处理器只执行一次。"""

    store = A2ATaskStore(ttl_seconds=60, max_entries=10)
    calls = 0
    calls_lock = threading.Lock()
    results: list[A2ATaskResult] = []

    def processor(task: A2ATaskRequest) -> A2ATaskResult:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.01)
        return make_result(task)

    def submit() -> None:
        result, _ = store.execute(make_task(), processor)
        results.append(result)

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls == 1
    assert len(results) == 8
    assert {result.task_id for result in results} == {"task_store_001"}
    assert store.metrics()["deduplicated"] == 7
