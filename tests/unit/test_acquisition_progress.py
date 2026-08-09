from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest

from marketsieve_extension_api import AcquisitionProgress, AcquisitionProgressState


def progress() -> AcquisitionProgress:
    return AcquisitionProgress("price", AcquisitionProgressState.RUNNING, 2, 10, 1)


def test_acquisition_progress_accepts_bounded_counts() -> None:
    assert progress().completed == 2
    assert (
        AcquisitionProgress(
            "price",
            AcquisitionProgressState.RETRYING,
            2,
            10,
            1,
            attempt=2,
            max_attempts=3,
            retry_after_seconds=15.0,
        ).attempt
        == 2
    )


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"phase": ""}, ValueError),
        ({"state": cast(Any, "running")}, TypeError),
        ({"completed": -1}, ValueError),
        ({"completed": 11}, ValueError),
        ({"total": 0}, ValueError),
        ({"failure_count": 3}, ValueError),
        ({"completed": cast(Any, True)}, TypeError),
        ({"attempt": 2}, ValueError),
    ],
)
def test_acquisition_progress_rejects_invalid_values(
    changes: dict[str, Any], error: type[Exception]
) -> None:
    with pytest.raises(error):
        replace(progress(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt": None},
        {"attempt": 1},
        {"attempt": 4},
        {"max_attempts": None},
        {"retry_after_seconds": None},
        {"retry_after_seconds": -1},
        {"retry_after_seconds": float("nan")},
    ],
)
def test_retry_progress_requires_a_complete_valid_retry_tuple(changes: dict[str, Any]) -> None:
    value = AcquisitionProgress(
        "price",
        AcquisitionProgressState.RETRYING,
        2,
        10,
        1,
        attempt=2,
        max_attempts=3,
        retry_after_seconds=15,
    )
    with pytest.raises(ValueError):
        replace(value, **changes)
