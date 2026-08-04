"""Time-correct historical replay for SMA20 analysis."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime

from marketsieve._time import as_utc
from marketsieve.analysis.sma20 import Sma20Result, analyze
from marketsieve.data.daily import DailyBarRequest, DailyBarSource, Provenance


@dataclass(frozen=True, slots=True)
class ReplayPoint:
    """One analysis evaluated from data available at an exact instant."""

    as_of: datetime
    result: Sma20Result
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("replay point as_of must include a UTC offset")
        if not isinstance(self.result, Sma20Result):
            raise TypeError("replay point result must be Sma20Result")
        if any(not isinstance(item, Provenance) for item in self.provenance):
            raise TypeError("replay point provenance must contain Provenance values")


@dataclass(frozen=True, slots=True)
class Sma20Replay:
    """A deterministic ordered replay of one exact daily-bar request."""

    request: DailyBarRequest
    points: tuple[ReplayPoint, ...]
    replay_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, DailyBarRequest):
            raise TypeError("replay request must be DailyBarRequest")
        if not self.points:
            raise ValueError("a replay requires at least one point")
        if any(not isinstance(point, ReplayPoint) for point in self.points):
            raise TypeError("replay points must contain ReplayPoint values")
        instants = tuple(as_utc(point.as_of) for point in self.points)
        if instants != tuple(sorted(instants)) or len(set(instants)) != len(instants):
            raise ValueError("replay points must have unique as-of instants in ascending order")
        if re.fullmatch(r"[0-9a-f]{64}", self.replay_id) is None:
            raise ValueError("replay_id must be a SHA-256 hexadecimal digest")


def _validate_instants(instants: tuple[datetime, ...]) -> None:
    if not instants:
        raise ValueError("a replay requires at least one as-of instant")
    if any(value.tzinfo is None or value.utcoffset() is None for value in instants):
        raise ValueError("replay as-of instants must include a UTC offset")
    utc_instants = tuple(as_utc(value) for value in instants)
    if utc_instants != tuple(sorted(utc_instants)):
        raise ValueError("replay as-of instants must be in ascending order")
    if len(set(utc_instants)) != len(utc_instants):
        raise ValueError("replay as-of instants must not contain duplicates")


def _replay_id(request: DailyBarRequest, points: tuple[ReplayPoint, ...]) -> str:
    payload = {
        "request": {
            "symbol": request.instrument.symbol,
            "mic": request.instrument.mic,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "adjustment": request.adjustment.value,
        },
        "points": [
            {
                "as_of": as_utc(point.as_of).isoformat(),
                "evidence_id": point.result.evidence_id,
            }
            for point in points
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def replay_sma20(
    source: DailyBarSource,
    request: DailyBarRequest,
    as_ofs: tuple[datetime, ...],
) -> Sma20Replay:
    """Reload and analyze an exact request at every supplied instant."""

    _validate_instants(as_ofs)
    points = []
    for as_of in as_ofs:
        series = source.load(request, as_of=as_of)
        if series.request != request:
            raise RuntimeError("daily-bar source changed the replay request")
        if as_utc(series.as_of) != as_utc(as_of):
            raise RuntimeError("daily-bar source changed the replay as-of instant")
        provenance = tuple(dict.fromkeys(bar.provenance for bar in series.bars))
        points.append(ReplayPoint(as_of, analyze(series), provenance))
    replay_points = tuple(points)
    return Sma20Replay(request, replay_points, _replay_id(request, replay_points))
