from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext

from marketsieve.analysis.sma20 import AnalysisStatus, SmaState, analyze, average
from marketsieve.data.daily import Adjustment, DailyBarRequest, DailyBarSeries
from marketsieve.synthetic.daily import JP_INSTRUMENT, fixture_bars


def series(closes: tuple[str, ...]) -> DailyBarSeries:
    bars = fixture_bars(JP_INSTRUMENT, closes, dataset="analysis-test")
    request = DailyBarRequest(
        JP_INSTRUMENT, bars[0].trading_date, bars[-1].trading_date, Adjustment.RAW
    )
    return DailyBarSeries(request, bars, bars[-1].available_at, 0)


def test_sma20_handles_19_20_and_21_observation_boundaries() -> None:
    insufficient = analyze(series(("100",) * 19))
    assert insufficient.status is AnalysisStatus.INSUFFICIENT_HISTORY
    assert insufficient.current_state is None

    current_only = analyze(series(("100",) * 20))
    assert current_only.current_state is SmaState.EQUAL
    assert current_only.previous_state is None
    assert current_only.transition is None

    transition = analyze(series(("100",) * 19 + ("99", "102")))
    assert transition.previous_state is SmaState.BELOW
    assert transition.current_state is SmaState.ABOVE
    assert transition.transition == "below_to_above"


def test_sma20_reports_above_below_equal_and_no_transition() -> None:
    assert analyze(series(("100",) * 19 + ("101",))).current_state is SmaState.ABOVE
    assert analyze(series(("100",) * 19 + ("99",))).current_state is SmaState.BELOW
    assert analyze(series(("100",) * 20)).current_state is SmaState.EQUAL
    no_transition = analyze(series(("100",) * 19 + ("102", "103")))
    assert no_transition.previous_state is SmaState.ABOVE
    assert no_transition.current_state is SmaState.ABOVE
    assert no_transition.transition is None


def test_sma20_result_and_evidence_are_reproducible() -> None:
    input_series = series(("100.123456789",) * 19 + ("99.987654321", "102.000000001"))
    first = analyze(input_series)
    with localcontext() as context:
        context.prec = 2
        second = analyze(input_series)
    assert first == second
    assert len(first.evidence_id) == 64


def test_sma20_exact_average_supports_large_decimal_exponents() -> None:
    value = Decimal("1e+5000")
    bars = tuple(
        replace(bar, open=value, high=value, low=value, close=value)
        for bar in series(("100",) * 20).bars
    )

    assert average(bars) == value
