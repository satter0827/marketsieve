"""Fixed daily-bar values for deterministic tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from marketsieve.data.daily import Adjustment, DailyBar, Provenance
from marketsieve.domain import Instrument

JP_INSTRUMENT = Instrument.create(
    symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
)
US_INSTRUMENT = Instrument.create(
    symbol="MSFT", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
)


def trading_dates(start: date, count: int) -> tuple[date, ...]:
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
    dates = trading_dates(date(2026, 1, 5), len(closes))
    provenance = Provenance(source="synthetic", dataset=dataset, version="1.0.0")
    bars: list[DailyBar] = []
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
