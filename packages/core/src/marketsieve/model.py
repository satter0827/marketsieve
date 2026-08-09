"""Stable public market-evidence model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
MIC = re.compile(r"^[A-Z0-9]{4}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Instrument:
    """An unambiguous exchange-qualified equity."""

    symbol: str
    mic: str
    currency: str
    exchange_timezone: ZoneInfo

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in (self.symbol, self.mic, self.currency)):
            raise TypeError("symbol, mic, and currency must be strings")
        if SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError(
                "symbol must start with an uppercase letter or digit and contain only "
                "uppercase letters, digits, dots, or hyphens"
            )
        if MIC.fullmatch(self.mic) is None:
            raise ValueError("mic must be a four-character ISO 10383 code")
        if CURRENCY.fullmatch(self.currency) is None:
            raise ValueError("currency must be a three-letter uppercase code")
        if not isinstance(self.exchange_timezone, ZoneInfo):
            raise TypeError("exchange_timezone must be zoneinfo.ZoneInfo")

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        mic: str,
        currency: str,
        exchange_timezone: str,
    ) -> Instrument:
        """Create an instrument while validating the IANA timezone name."""

        try:
            timezone = ZoneInfo(exchange_timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown exchange timezone: {exchange_timezone}") from error
        return cls(symbol, mic, currency, timezone)


class Adjustment(StrEnum):
    """Price adjustment semantics."""

    RAW = "raw"
    ADJUSTED = "adjusted"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Identity of the immutable input dataset."""

    source: str
    dataset: str
    version: str

    def __post_init__(self) -> None:
        if not self.source or not self.dataset or not self.version:
            raise ValueError("provenance fields must not be empty")


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One time-correct OHLCV observation."""

    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adjustment: Adjustment
    available_at: datetime
    provenance: Provenance

    def __post_init__(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if type(self.trading_date) is not date:
            raise TypeError("trading_date must be datetime.date")
        if any(not isinstance(value, Decimal) for value in prices):
            raise TypeError("OHLC prices must use decimal.Decimal")
        if any(not value.is_finite() or value <= 0 for value in prices):
            raise ValueError("OHLC prices must be finite and positive")
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        if not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
            raise ValueError("open and close must be inside the low-high range")
        if not isinstance(self.volume, int) or isinstance(self.volume, bool):
            raise TypeError("volume must be an integer")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")
        if not isinstance(self.adjustment, Adjustment):
            raise TypeError("adjustment must be Adjustment")
        if not isinstance(self.provenance, Provenance):
            raise TypeError("provenance must be Provenance")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("available_at must include a UTC offset")


__all__ = ["Adjustment", "DailyBar", "Instrument", "Provenance"]
