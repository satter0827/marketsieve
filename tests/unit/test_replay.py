from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from marketsieve.analysis.replay import ReplayPoint, Sma20Replay, replay_sma20
from marketsieve.analysis.sma20 import AnalysisStatus
from marketsieve.data.daily import Adjustment, DailyBarRequest, DailyBarSeries
from marketsieve.synthetic.daily import JP_BARS, JP_INSTRUMENT, SyntheticDailySource, jp_source


def request() -> DailyBarRequest:
    return DailyBarRequest(
        JP_INSTRUMENT, JP_BARS[0].trading_date, JP_BARS[-1].trading_date, Adjustment.RAW
    )


class RecordingSource(SyntheticDailySource):
    def __init__(self) -> None:
        super().__init__(JP_INSTRUMENT, JP_BARS)
        self.calls: list[datetime] = []

    def load(self, request: DailyBarRequest, *, as_of: datetime) -> DailyBarSeries:
        self.calls.append(as_of)
        return super().load(request, as_of=as_of)


def test_replay_reloads_the_source_at_every_as_of() -> None:
    source = RecordingSource()
    as_ofs = tuple(bar.available_at for bar in JP_BARS)

    replay = replay_sma20(source, request(), as_ofs)

    assert tuple(source.calls) == as_ofs
    assert len(replay.points) == 21
    assert replay.points[18].result.status is AnalysisStatus.INSUFFICIENT_HISTORY
    assert replay.points[-1].result.transition == "below_to_above"
    assert len(replay.replay_id) == 64
    assert replay == replay_sma20(jp_source(), request(), as_ofs)


@pytest.mark.parametrize(
    "as_ofs, message",
    [
        ((), "at least one"),
        ((datetime(2026, 1, 1),), "UTC offset"),
        ((JP_BARS[1].available_at, JP_BARS[0].available_at), "ascending"),
        ((JP_BARS[0].available_at, JP_BARS[0].available_at), "duplicates"),
    ],
)
def test_replay_rejects_invalid_evaluation_schedules(
    as_ofs: tuple[datetime, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replay_sma20(jp_source(), request(), as_ofs)


def test_replay_rejects_a_source_that_changes_the_contract() -> None:
    class InvalidSource(RecordingSource):
        def load(self, request: DailyBarRequest, *, as_of: datetime) -> DailyBarSeries:
            series = super().load(request, as_of=as_of)
            return replace(series, as_of=as_of + timedelta(seconds=1))

    with pytest.raises(RuntimeError, match="changed the replay as-of"):
        replay_sma20(InvalidSource(), request(), (JP_BARS[-1].available_at,))


def test_public_replay_types_preserve_their_invariants() -> None:
    replay = replay_sma20(jp_source(), request(), (JP_BARS[-1].available_at,))

    with pytest.raises(ValueError, match="UTC offset"):
        ReplayPoint(datetime(2026, 2, 3), replay.points[0].result, replay.points[0].provenance)
    with pytest.raises(ValueError, match="SHA-256"):
        replace(replay, replay_id="not-a-digest")
    with pytest.raises(ValueError, match="ascending order"):
        Sma20Replay(request(), (replay.points[0], replace(replay.points[0])), "a" * 64)
