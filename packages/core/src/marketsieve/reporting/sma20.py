"""Channel-neutral reporting for an SMA20 historical replay."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime

from marketsieve.analysis.replay import ReplayPoint, Sma20Replay
from marketsieve.analysis.sma20 import Sma20Result, SmaState
from marketsieve.data.daily import DailyBarRequest, Provenance


@dataclass(frozen=True, slots=True)
class Sma20Transition:
    """One observed state change with its evidence reference."""

    as_of: datetime
    trading_date: date
    previous_state: SmaState
    current_state: SmaState
    evidence_id: str

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("transition as_of must include a UTC offset")
        if self.previous_state is self.current_state:
            raise ValueError("a transition requires different states")
        if re.fullmatch(r"[0-9a-f]{64}", self.evidence_id) is None:
            raise ValueError("transition evidence_id must be a SHA-256 hexadecimal digest")


@dataclass(frozen=True, slots=True)
class Sma20ReplayReport:
    """Concrete report containing the latest state and observed transitions."""

    request: DailyBarRequest
    first_as_of: datetime
    last_as_of: datetime
    evaluation_count: int
    latest: Sma20Result
    transitions: tuple[Sma20Transition, ...]
    provenance: tuple[Provenance, ...]
    replay_id: str
    report_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, DailyBarRequest):
            raise TypeError("report request must be DailyBarRequest")
        if (
            self.first_as_of.tzinfo is None
            or self.first_as_of.utcoffset() is None
            or self.last_as_of.tzinfo is None
            or self.last_as_of.utcoffset() is None
        ):
            raise ValueError("report as-of instants must include a UTC offset")
        if self.first_as_of > self.last_as_of:
            raise ValueError("report as-of instants must be in ascending order")
        if self.evaluation_count < 1:
            raise ValueError("report evaluation_count must be positive")
        if not isinstance(self.latest, Sma20Result):
            raise TypeError("report latest result must be Sma20Result")
        if any(not isinstance(item, Sma20Transition) for item in self.transitions):
            raise TypeError("report transitions must contain Sma20Transition values")
        if any(not isinstance(item, Provenance) for item in self.provenance):
            raise TypeError("report provenance must contain Provenance values")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (self.replay_id, self.report_id)
        ):
            raise ValueError("report identities must be SHA-256 hexadecimal digests")


def _transition(point: ReplayPoint) -> Sma20Transition | None:
    result = point.result
    if result.transition is None:
        return None
    if result.current_date is None or result.previous_state is None or result.current_state is None:
        raise RuntimeError("a transition requires complete SMA20 state evidence")
    return Sma20Transition(
        as_of=point.as_of,
        trading_date=result.current_date,
        previous_state=result.previous_state,
        current_state=result.current_state,
        evidence_id=result.evidence_id,
    )


def _report_id(replay: Sma20Replay, transitions: tuple[Sma20Transition, ...]) -> str:
    payload = {
        "replay_id": replay.replay_id,
        "latest_evidence_id": replay.points[-1].result.evidence_id,
        "transition_evidence_ids": [item.evidence_id for item in transitions],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def build_sma20_replay_report(replay: Sma20Replay) -> Sma20ReplayReport:
    """Project a replay into its latest state and observed transitions."""

    transitions = tuple(
        transition for point in replay.points if (transition := _transition(point)) is not None
    )
    provenance = tuple(dict.fromkeys(item for point in replay.points for item in point.provenance))
    return Sma20ReplayReport(
        request=replay.request,
        first_as_of=replay.points[0].as_of,
        last_as_of=replay.points[-1].as_of,
        evaluation_count=len(replay.points),
        latest=replay.points[-1].result,
        transitions=transitions,
        provenance=provenance,
        replay_id=replay.replay_id,
        report_id=_report_id(replay, transitions),
    )
