from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from marketsieve.data.daily import Adjustment, DailyBarCapability, DailyBarRequest, DailyBarSource
from marketsieve.synthetic.daily import (
    JP_BARS,
    JP_INSTRUMENT,
    US_INSTRUMENT,
    SyntheticDailySource,
    jp_source,
)


def request() -> DailyBarRequest:
    return DailyBarRequest(
        JP_INSTRUMENT, JP_BARS[0].trading_date, JP_BARS[-1].trading_date, Adjustment.RAW
    )


def test_synthetic_source_satisfies_the_daily_source_contract_exactly() -> None:
    source = jp_source()
    assert isinstance(source, DailyBarSource)
    assert source.capability(request()).supported
    series = source.load(request(), as_of=JP_BARS[-1].available_at)
    assert series.bars == JP_BARS
    assert series.excluded_after_as_of == 0

    unsupported = DailyBarRequest(
        US_INSTRUMENT, JP_BARS[0].trading_date, JP_BARS[-1].trading_date, Adjustment.RAW
    )
    assert source.capability(unsupported).reason == "instrument_not_available"
    with pytest.raises(ValueError, match="instrument_not_available"):
        source.load(unsupported, as_of=JP_BARS[-1].available_at)


def test_synthetic_source_excludes_observations_not_available_as_of() -> None:
    cutoff = JP_BARS[-1].available_at - timedelta(seconds=1)
    series = jp_source().load(request(), as_of=cutoff)
    assert series.bars == JP_BARS[:-1]
    assert series.excluded_after_as_of == 1


def test_synthetic_source_excludes_the_later_dst_fold_instant() -> None:
    timezone = ZoneInfo("America/New_York")
    earlier = datetime(2026, 11, 1, 1, 30, tzinfo=timezone, fold=0)
    later = datetime(2026, 11, 1, 1, 30, tzinfo=timezone, fold=1)
    bars = (*JP_BARS[:-1], replace(JP_BARS[-1], available_at=later))

    series = SyntheticDailySource(JP_INSTRUMENT, bars).load(request(), as_of=earlier)

    assert series.bars == bars[:-1]
    assert series.excluded_after_as_of == 1


def test_synthetic_source_rejects_adjustment_and_range_substitution() -> None:
    adjusted = DailyBarRequest(
        JP_INSTRUMENT, JP_BARS[0].trading_date, JP_BARS[-1].trading_date, Adjustment.ADJUSTED
    )
    assert jp_source().capability(adjusted).reason == "adjustment_not_available"
    outside = DailyBarRequest(
        JP_INSTRUMENT,
        JP_BARS[0].trading_date - timedelta(days=1),
        JP_BARS[-1].trading_date,
        Adjustment.RAW,
    )
    assert jp_source().capability(outside).reason == "range_not_available"


def test_synthetic_source_rejects_incomplete_fixture_dates() -> None:
    incomplete = JP_BARS[:10] + JP_BARS[11:]
    with pytest.raises(ValueError, match="consecutive weekdays"):
        SyntheticDailySource(JP_INSTRUMENT, incomplete)


def test_daily_capability_and_as_of_are_explicit() -> None:
    with pytest.raises(ValueError, match="must not include"):
        DailyBarCapability(True, "unexpected")
    with pytest.raises(ValueError, match="requires a reason"):
        DailyBarCapability(False)
    with pytest.raises(ValueError, match="UTC offset"):
        jp_source().load(request(), as_of=datetime(2026, 2, 10))
