"""Typed, evidence-neutral acquisition progress notifications."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class AcquisitionProgressState(StrEnum):
    """Stable states emitted while a provider request is running."""

    STARTED = "started"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class AcquisitionProgress:
    """One bounded provider progress observation outside evidence identity."""

    phase: str
    state: AcquisitionProgressState
    completed: int
    total: int
    failure_count: int
    attempt: int | None = None
    max_attempts: int | None = None
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, str) or not self.phase:
            raise ValueError("progress phase must not be empty")
        if not isinstance(self.state, AcquisitionProgressState):
            raise TypeError("progress state must use AcquisitionProgressState")
        counts = (self.completed, self.total, self.failure_count)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in counts):
            raise TypeError("progress counts must be integers")
        if self.total <= 0 or not 0 <= self.completed <= self.total:
            raise ValueError("progress completed count must be inside the positive total")
        if not 0 <= self.failure_count <= self.completed:
            raise ValueError("progress failure count must not exceed completed work")
        retry_values = (self.attempt, self.max_attempts, self.retry_after_seconds)
        if self.state is not AcquisitionProgressState.RETRYING:
            if any(value is not None for value in retry_values):
                raise ValueError("retry fields are valid only for retrying progress")
            return
        if self.attempt is None or self.max_attempts is None or self.retry_after_seconds is None:
            raise ValueError("retrying progress requires every retry field")
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or not 2 <= self.attempt <= self.max_attempts
        ):
            raise ValueError("retry attempt must be between 2 and max attempts")
        if (
            not isinstance(self.retry_after_seconds, (int, float))
            or isinstance(self.retry_after_seconds, bool)
            or not math.isfinite(self.retry_after_seconds)
            or self.retry_after_seconds < 0
        ):
            raise ValueError("retry wait must be finite and non-negative")


@runtime_checkable
class ProgressSink(Protocol):
    """Receive progress without changing request or response semantics."""

    def __call__(self, progress: AcquisitionProgress, /) -> None: ...
