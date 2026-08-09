"""Acquisition termination types shared by orchestration and interfaces."""

from __future__ import annotations


class MarketSnapshotRunInterrupted(RuntimeError):
    """Report a persisted acquisition request that can be resumed exactly."""

    def __init__(self, run_id: str, error: Exception) -> None:
        self.resume_run_id = run_id
        self.resume_command = f"marketsieve market build --resume {run_id}"
        super().__init__(
            "market snapshot acquisition stopped before publication: "
            f"{error}; resume the exact saved request with {self.resume_command}"
        )


class MarketSnapshotRunCancelled(KeyboardInterrupt):
    """Preserve the exact persisted request when acquisition is cancelled."""

    def __init__(self, run_id: str) -> None:
        self.resume_run_id = run_id
        self.resume_command = f"marketsieve market build --resume {run_id}"
        super().__init__(
            "market snapshot acquisition was cancelled; resume the exact saved request with "
            f"{self.resume_command}"
        )
