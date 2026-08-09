from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from marketsieve.model import Adjustment, DailyBar, Instrument, Provenance

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
