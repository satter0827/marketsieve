from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from marketsieve.data.daily import (
    Adjustment,
    DailyBar,
    DailyBarRequest,
    DailyBarSeries,
    Provenance,
)
from marketsieve.domain import Instrument
from marketsieve.synthetic.daily import JP_BARS, JP_INSTRUMENT

TOKYO = ZoneInfo("Asia/Tokyo")


def test_instrument_requires_explicit_exchange_identity_and_timezone() -> None:
    instrument = Instrument.create(
        symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
    )
    assert instrument.exchange_timezone.key == "Asia/Tokyo"

    for symbol in (".AAPL", "AAPL/US", "msft", ""):
        with pytest.raises(ValueError, match="symbol"):
            Instrument.create(
                symbol=symbol, mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
            )
    assert (
        Instrument.create(
            symbol="BRK.B", mic="XNYS", currency="USD", exchange_timezone="America/New_York"
        ).symbol
        == "BRK.B"
    )
    with pytest.raises(ValueError, match="timezone"):
        Instrument.create(
            symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Local/Unknown"
        )
    with pytest.raises(ValueError, match="mic"):
        Instrument.create(symbol="7203", mic="TKS", currency="JPY", exchange_timezone="Asia/Tokyo")
    with pytest.raises(ValueError, match="currency"):
        Instrument.create(symbol="7203", mic="XTKS", currency="jp", exchange_timezone="Asia/Tokyo")
    with pytest.raises(TypeError, match="InstrumentType"):
        Instrument(
            "7203",
            "XTKS",
            "JPY",
            TOKYO,
            "equity",  # type: ignore[arg-type]
        )


def test_daily_bar_rejects_invalid_ohlcv_and_naive_availability() -> None:
    def make_bar(
        *,
        close: Decimal = Decimal("100"),
        volume: int = 1,
        available_at: datetime = datetime(2026, 1, 6, tzinfo=TOKYO),
    ) -> DailyBar:
        return DailyBar(
            trading_date=date(2026, 1, 5),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=close,
            volume=volume,
            adjustment=Adjustment.RAW,
            available_at=available_at,
            provenance=Provenance("synthetic", "test", "1.0.0"),
        )

    valid = make_bar()

    with pytest.raises(ValueError, match="inside"):
        make_bar(close=Decimal("102"))
    with pytest.raises(ValueError, match="non-negative"):
        make_bar(volume=-1)
    with pytest.raises(ValueError, match="UTC offset"):
        make_bar(available_at=datetime(2026, 1, 6))
    with pytest.raises(ValueError, match="positive"):
        make_bar(close=Decimal("NaN"))
    with pytest.raises(TypeError, match="Decimal"):
        replace(valid, open=100)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer"):
        replace(valid, volume=1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Adjustment"):
        replace(valid, adjustment="raw")  # type: ignore[arg-type]


def test_daily_request_and_series_reject_contract_violations() -> None:
    with pytest.raises(ValueError, match="start"):
        DailyBarRequest(
            JP_INSTRUMENT,
            JP_BARS[-1].trading_date,
            JP_BARS[0].trading_date,
            Adjustment.RAW,
        )

    request = DailyBarRequest(
        JP_INSTRUMENT, JP_BARS[0].trading_date, JP_BARS[-1].trading_date, Adjustment.RAW
    )
    as_of = JP_BARS[-1].available_at
    with pytest.raises(ValueError, match="unique"):
        DailyBarSeries(request, (JP_BARS[0], JP_BARS[0]), as_of, 0)
    with pytest.raises(ValueError, match="ascending"):
        DailyBarSeries(request, (JP_BARS[1], JP_BARS[0]), as_of, 0)
    with pytest.raises(ValueError, match="requested range"):
        DailyBarSeries(
            request,
            (replace(JP_BARS[0], trading_date=request.start - timedelta(days=1)),),
            as_of,
            0,
        )
    with pytest.raises(ValueError, match="adjustment"):
        DailyBarSeries(request, (replace(JP_BARS[0], adjustment=Adjustment.ADJUSTED),), as_of, 0)
    with pytest.raises(ValueError, match="unavailable"):
        DailyBarSeries(request, (JP_BARS[-1],), JP_BARS[-1].available_at - timedelta(seconds=1), 1)
    with pytest.raises(ValueError, match="non-negative"):
        DailyBarSeries(request, (), as_of, -1)
