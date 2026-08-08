from __future__ import annotations

import threading

import pytest
from scripts.parallel import Task, TaskGroupError, run_tasks, worker_count


def test_worker_count_is_bounded_and_supports_serial_fallback() -> None:
    assert worker_count(1) == 1
    assert 1 <= worker_count(0) <= 4
    with pytest.raises(ValueError, match="0 through 4"):
        worker_count(5)


def test_parallel_tasks_start_together_and_report_in_declaration_order() -> None:
    barrier = threading.Barrier(2, timeout=2)

    def first() -> None:
        barrier.wait()

    def second() -> None:
        barrier.wait()

    results = run_tasks((Task("first", first), Task("second", second)), jobs=2)

    assert [result["name"] for result in results] == ["first", "second", "parallel_group"]
    assert {result["start_order"] for result in results[:-1]} == {0, 1}
    assert results[-1]["worker_count"] == 2


def test_parallel_failures_are_aggregated_in_declaration_order() -> None:
    def fail(message: str) -> None:
        raise ValueError(message)

    with pytest.raises(TaskGroupError) as caught:
        run_tasks(
            (
                Task("first", lambda: fail("one")),
                Task("second", lambda: fail("two")),
            ),
            jobs=2,
        )

    assert str(caught.value).startswith("first: ValueError: one; second: ValueError: two")
    assert [result["name"] for result in caught.value.results] == ["first", "second"]


def test_parallel_tasks_require_unique_names() -> None:
    with pytest.raises(ValueError, match="task names must be unique"):
        run_tasks((Task("same", lambda: None), Task("same", lambda: None)), jobs=2)
