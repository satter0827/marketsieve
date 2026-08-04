from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from marketsieve.analysis.replay import replay_sma20
from marketsieve.data.daily import Adjustment, DailyBarRequest
from marketsieve.reporting.sma20 import build_sma20_replay_report
from marketsieve.synthetic.daily import JP_BARS, JP_INSTRUMENT, jp_source


def test_report_contains_latest_state_transitions_and_evidence() -> None:
    request = DailyBarRequest(
        JP_INSTRUMENT, JP_BARS[0].trading_date, JP_BARS[-1].trading_date, Adjustment.RAW
    )
    replay = replay_sma20(jp_source(), request, tuple(bar.available_at for bar in JP_BARS))

    first = build_sma20_replay_report(replay)
    second = build_sma20_replay_report(replay)

    assert first == second
    assert first.latest.current_state is not None
    assert len(first.transitions) == 1
    assert first.transitions[0].previous_state.value == "below"
    assert first.transitions[0].current_state.value == "above"
    assert first.provenance[0].dataset == "jp-v1"
    assert len(first.report_id) == 64
    assert first.replay_id == replay.replay_id

    with pytest.raises(ValueError, match="different states"):
        replace(first.transitions[0], current_state=first.transitions[0].previous_state)
    with pytest.raises(ValueError, match="positive"):
        replace(first, evaluation_count=0)
    with pytest.raises(ValueError, match="SHA-256"):
        replace(first, report_id="not-a-digest")


def test_report_transitions_compare_consecutive_valid_replay_points() -> None:
    request = DailyBarRequest(
        JP_INSTRUMENT, JP_BARS[0].trading_date, JP_BARS[-1].trading_date, Adjustment.RAW
    )
    sparse = replay_sma20(
        jp_source(), request, (JP_BARS[19].available_at, JP_BARS[20].available_at)
    )
    first_valid_only = replay_sma20(jp_source(), request, (JP_BARS[20].available_at,))
    repeated = replay_sma20(
        jp_source(),
        request,
        (JP_BARS[20].available_at, JP_BARS[20].available_at + timedelta(minutes=1)),
    )

    transition = build_sma20_replay_report(sparse).transitions
    assert [(item.previous_state.value, item.current_state.value) for item in transition] == [
        ("below", "above")
    ]
    assert build_sma20_replay_report(first_valid_only).transitions == ()
    assert build_sma20_replay_report(repeated).transitions == ()
