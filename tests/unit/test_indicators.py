from __future__ import annotations

from decimal import localcontext

import pytest

from marketsieve.indicators import (
    IndicatorName,
    IndicatorSpec,
    IndicatorStatus,
    calculate,
)
from marketsieve.model import DailyBar
from marketsieve_extension_api.testing import JP_INSTRUMENT, fixture_bars


def bars(*closes: str) -> tuple[DailyBar, ...]:
    return fixture_bars(JP_INSTRUMENT, tuple(closes), dataset="indicator-reference-v1")


def value(name: IndicatorName, closes: tuple[str, ...], **parameters: int) -> dict[str, str]:
    result = calculate(IndicatorSpec.create(name, **parameters), bars(*closes))
    assert result.status is IndicatorStatus.OK
    return dict(result.values)


def test_reference_vectors_for_the_seven_indicators() -> None:
    assert value(IndicatorName.SMA, ("10", "20", "30"), period=3) == {"sma": "20"}
    assert value(IndicatorName.EMA, ("10", "20", "30", "40"), period=3) == {"ema": "30"}
    assert value(IndicatorName.RSI, ("10", "20", "30", "40"), period=3) == {"rsi": "100"}
    assert value(
        IndicatorName.MACD,
        ("10", "20", "30", "40"),
        fast_period=2,
        slow_period=3,
        signal_period=2,
    ) == {"macd": "5", "signal": "5", "histogram": "0"}
    assert value(IndicatorName.ATR, ("10", "11", "12"), period=3) == {"atr": "2"}
    assert value(IndicatorName.PERIOD_RETURN, ("10", "20", "30", "40"), period=3) == {"return": "3"}
    assert value(IndicatorName.MAX_DRAWDOWN, ("10", "8", "9", "7"), period=4) == {
        "maximum_drawdown": "-0.3"
    }


def test_rsi_flat_seed_is_explicitly_neutral() -> None:
    assert value(IndicatorName.RSI, ("5", "5", "5", "5"), period=3) == {"rsi": "50"}


@pytest.mark.parametrize(
    ("name", "parameters", "required"),
    [
        (IndicatorName.SMA, {"period": 3}, 3),
        (IndicatorName.EMA, {"period": 3}, 3),
        (IndicatorName.RSI, {"period": 3}, 4),
        (IndicatorName.ATR, {"period": 3}, 3),
        (IndicatorName.PERIOD_RETURN, {"period": 3}, 4),
        (IndicatorName.MAX_DRAWDOWN, {"period": 3}, 3),
        (
            IndicatorName.MACD,
            {"fast_period": 2, "slow_period": 3, "signal_period": 2},
            4,
        ),
    ],
)
def test_insufficient_history_is_an_explicit_result(
    name: IndicatorName, parameters: dict[str, int], required: int
) -> None:
    input_bars = fixture_bars(
        JP_INSTRUMENT, tuple("10" for _ in range(required - 1)), dataset="short"
    )

    result = calculate(IndicatorSpec.create(name, **parameters), input_bars)

    assert result.status is IndicatorStatus.INSUFFICIENT_HISTORY
    assert result.values == ()
    assert result.observation_count == required - 1


def test_results_and_evidence_ignore_ambient_decimal_context() -> None:
    input_bars = fixture_bars(
        JP_INSTRUMENT,
        ("100.123456789", "101.987654321", "99.333333333", "104.000000001"),
        dataset="precision",
    )
    specs = (
        IndicatorSpec.create(IndicatorName.SMA, period=3),
        IndicatorSpec.create(IndicatorName.EMA, period=3),
        IndicatorSpec.create(IndicatorName.RSI, period=3),
        IndicatorSpec.create(IndicatorName.MACD, fast_period=2, slow_period=3, signal_period=2),
        IndicatorSpec.create(IndicatorName.ATR, period=3),
        IndicatorSpec.create(IndicatorName.PERIOD_RETURN, period=3),
        IndicatorSpec.create(IndicatorName.MAX_DRAWDOWN, period=4),
    )
    expected = tuple(calculate(spec, input_bars) for spec in specs)

    with localcontext() as context:
        context.prec = 2
        actual = tuple(calculate(spec, input_bars) for spec in specs)

    assert actual == expected
    assert all(len(result.evidence_id) == 64 for result in actual)


def test_invalid_or_extra_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="positive integers"):
        IndicatorSpec.create(IndicatorName.SMA, period=0)
    with pytest.raises(ValueError, match="exactly"):
        calculate(
            IndicatorSpec.create(IndicatorName.SMA, period=3, seed=1),
            fixture_bars(JP_INSTRUMENT, ("10", "20", "30"), dataset="invalid"),
        )
    with pytest.raises(ValueError, match="less than"):
        calculate(
            IndicatorSpec.create(IndicatorName.MACD, fast_period=3, slow_period=3, signal_period=2),
            fixture_bars(JP_INSTRUMENT, ("10", "20", "30", "40"), dataset="invalid"),
        )
