"""Small deterministic bounded runner for independent development tasks."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Task:
    """One named independent operation."""

    name: str
    operation: Callable[[], object]


class TaskGroupError(RuntimeError):
    """Stable aggregate failure with completed task timing evidence."""

    def __init__(self, message: str, results: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.results = results


def worker_count(requested: int, *, cap: int = 4) -> int:
    """Resolve zero as automatic and enforce a conservative bounded range."""

    if requested < 0 or requested > cap:
        raise ValueError(f"jobs must be from 0 through {cap}")
    return min(cap, max(1, os.cpu_count() or 1)) if requested == 0 else requested


def run_tasks(tasks: Sequence[Task], *, jobs: int) -> list[dict[str, Any]]:
    """Run independent tasks concurrently and report failures in declaration order."""

    if not tasks:
        return []
    names = [task.name for task in tasks]
    if len(set(names)) != len(names):
        raise ValueError("task names must be unique")
    resolved_jobs = min(worker_count(jobs), len(tasks))
    started = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    start_counter = 0
    start_lock = threading.Lock()

    def execute(task: Task) -> None:
        nonlocal start_counter
        with start_lock:
            start_order = start_counter
            start_counter += 1
        task_started = time.monotonic()
        try:
            task.operation()
        except Exception as error:
            results[task.name] = {
                "name": task.name,
                "start_order": start_order,
                "status": "failed",
                "duration_seconds": round(time.monotonic() - task_started, 6),
                "error_type": type(error).__name__,
                "error": str(error),
            }
            return
        results[task.name] = {
            "name": task.name,
            "start_order": start_order,
            "status": "passed",
            "duration_seconds": round(time.monotonic() - task_started, 6),
        }

    with ThreadPoolExecutor(
        max_workers=resolved_jobs, thread_name_prefix="marketsieve-gate"
    ) as pool:
        futures = [pool.submit(execute, task) for task in tasks]
        for future in as_completed(futures):
            future.result()
    ordered = [results[task.name] for task in tasks]
    failures = [result for result in ordered if result["status"] == "failed"]
    if failures:
        detail = "; ".join(
            f"{result['name']}: {result['error_type']}: {result['error']}" for result in failures
        )
        raise TaskGroupError(detail, ordered)
    ordered.append(
        {
            "name": "parallel_group",
            "status": "passed",
            "duration_seconds": round(time.monotonic() - started, 6),
            "worker_count": resolved_jobs,
        }
    )
    return ordered
