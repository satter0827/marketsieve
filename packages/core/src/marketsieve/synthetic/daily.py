"""Fixed Japanese and U.S. daily-bar sources."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from marketsieve.data.daily import (
    Adjustment,
    DailyBar,
    DailyBarCapability,
    DailyBarRequest,
    DailyBarSeries,
    Provenance,
)
from marketsieve.domain import Instrument

JP_INSTRUMENT = Instrument.create(
    symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
)
US_INSTRUMENT = Instrument.create(
    symbol="MSFT", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
)


def trading_dates(start: date, count: int) -> tuple[date, ...]:
    """Return a fixed weekday-only date sequence."""

    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


def fixture_bars(
    instrument: Instrument, closes: tuple[str, ...], *, dataset: str
) -> tuple[DailyBar, ...]:
    """Build immutable bars from fixed literal closing prices."""

    dates = trading_dates(date(2026, 1, 5), len(closes))
    provenance = Provenance(source="synthetic", dataset=dataset, version="1.0.0")
    bars = []
    for index, (trading_date, close_text) in enumerate(zip(dates, closes, strict=True)):
        close = Decimal(close_text)
        bars.append(
            DailyBar(
                trading_date=trading_date,
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=1_000_000 + index * 10_000,
                adjustment=Adjustment.RAW,
                available_at=datetime.combine(
                    trading_date + timedelta(days=1),
                    time(hour=8),
                    tzinfo=instrument.exchange_timezone,
                ),
                provenance=provenance,
            )
        )
    return tuple(bars)


JP_BARS = fixture_bars(JP_INSTRUMENT, ("100",) * 19 + ("99", "102"), dataset="jp-v1")
US_BARS = fixture_bars(US_INSTRUMENT, ("200",) * 19 + ("202", "199"), dataset="us-v1")


class SyntheticDailySource:
    """Serve one complete fixed series without request substitution."""

    def __init__(self, instrument: Instrument, bars: tuple[DailyBar, ...]) -> None:
        if not bars:
            raise ValueError("a synthetic source requires at least one bar")
        request = DailyBarRequest(
            instrument=instrument,
            start=bars[0].trading_date,
            end=bars[-1].trading_date,
            adjustment=bars[0].adjustment,
        )
        if tuple(bar.trading_date for bar in bars) != trading_dates(
            bars[0].trading_date, len(bars)
        ):
            raise ValueError("synthetic fixture trading dates must be consecutive weekdays")
        DailyBarSeries(
            request=request,
            bars=bars,
            as_of=max(bar.available_at for bar in bars),
            excluded_after_as_of=0,
        )
        self._instrument = instrument
        self._bars = bars

    def capability(self, request: DailyBarRequest) -> DailyBarCapability:
        if request.instrument != self._instrument:
            return DailyBarCapability(False, "instrument_not_available")
        if request.adjustment != Adjustment.RAW:
            return DailyBarCapability(False, "adjustment_not_available")
        if request.start < self._bars[0].trading_date or request.end > self._bars[-1].trading_date:
            return DailyBarCapability(False, "range_not_available")
        return DailyBarCapability(True)

    def load(self, request: DailyBarRequest, *, as_of: datetime) -> DailyBarSeries:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a UTC offset")
        capability = self.capability(request)
        if not capability.supported:
            raise ValueError(f"unsupported daily-bar request: {capability.reason}")
        requested = tuple(
            bar for bar in self._bars if request.start <= bar.trading_date <= request.end
        )
        available = tuple(bar for bar in requested if bar.available_at <= as_of)
        return DailyBarSeries(
            request=request,
            bars=available,
            as_of=as_of,
            excluded_after_as_of=len(requested) - len(available),
        )


def jp_source() -> SyntheticDailySource:
    """Return the fixed XTKS source."""

    return SyntheticDailySource(JP_INSTRUMENT, JP_BARS)


def us_source() -> SyntheticDailySource:
    """Return the fixed XNAS source."""

    return SyntheticDailySource(US_INSTRUMENT, US_BARS)
