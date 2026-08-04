"""Validated daily-bar values and the daily-source contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from marketsieve._time import as_utc
from marketsieve.domain import Instrument


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


@dataclass(frozen=True, slots=True)
class DailyBarRequest:
    """An exact daily-bar request with no implicit market selection."""

    instrument: Instrument
    start: date
    end: date
    adjustment: Adjustment

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("instrument must be Instrument")
        if type(self.start) is not date or type(self.end) is not date:
            raise TypeError("daily-bar request boundaries must be dates")
        if not isinstance(self.adjustment, Adjustment):
            raise TypeError("adjustment must be Adjustment")
        if self.start > self.end:
            raise ValueError("daily-bar request start must not exceed end")


@dataclass(frozen=True, slots=True)
class DailyBarCapability:
    """Whether a source can satisfy a request without substitution."""

    supported: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.supported and self.reason is not None:
            raise ValueError("a supported capability must not include a rejection reason")
        if not self.supported and not self.reason:
            raise ValueError("an unsupported capability requires a reason")


@dataclass(frozen=True, slots=True)
class DailyBarSeries:
    """An ordered, validated response to one exact request."""

    request: DailyBarRequest
    bars: tuple[DailyBar, ...]
    as_of: datetime
    excluded_after_as_of: int

    def __post_init__(self) -> None:
        dates = tuple(bar.trading_date for bar in self.bars)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise ValueError("daily bars must have unique trading dates in ascending order")
        if any(not self.request.start <= value <= self.request.end for value in dates):
            raise ValueError("daily bars must remain inside the requested range")
        if any(bar.adjustment != self.request.adjustment for bar in self.bars):
            raise ValueError("daily bars must preserve the requested adjustment")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("series as_of must include a UTC offset")
        as_of_utc = as_utc(self.as_of)
        if any(as_utc(bar.available_at) > as_of_utc for bar in self.bars):
            raise ValueError("series contains an observation unavailable at as_of")
        if self.excluded_after_as_of < 0:
            raise ValueError("excluded observation count must be non-negative")


@runtime_checkable
class DailyBarSource(Protocol):
    """A source that either satisfies an exact request or rejects it."""

    def capability(self, request: DailyBarRequest) -> DailyBarCapability: ...

    def load(self, request: DailyBarRequest, *, as_of: datetime) -> DailyBarSeries: ...
