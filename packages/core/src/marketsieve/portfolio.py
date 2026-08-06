"""Brokerage-neutral portfolio observations and personal policy inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from marketsieve._time import as_utc
from marketsieve.domain import Instrument


def _finite_non_negative(value: Decimal, name: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must use decimal.Decimal")
    if not value.is_finite() or value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {qualifier}")


@dataclass(frozen=True, slots=True)
class Holding:
    """One brokerage-neutral position at a portfolio observation instant."""

    instrument: Instrument
    quantity: Decimal
    average_acquisition_price: Decimal
    account_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("holding instrument must be Instrument")
        _finite_non_negative(self.quantity, "holding quantity", positive=True)
        _finite_non_negative(
            self.average_acquisition_price, "average acquisition price", positive=True
        )
        if not isinstance(self.account_type, str):
            raise TypeError("holding account type must be a string")
        if not self.account_type.strip():
            raise ValueError("holding account type must not be empty")


@dataclass(frozen=True, slots=True)
class WatchItem:
    """One unheld instrument selected for routine observation."""

    instrument: Instrument

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("watch item instrument must be Instrument")


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """An immutable observation of holdings and watch items."""

    as_of: datetime
    holdings: tuple[Holding, ...]
    watch_items: tuple[WatchItem, ...]
    source: str

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("portfolio as_of must include a UTC offset")
        if any(not isinstance(item, Holding) for item in self.holdings):
            raise TypeError("portfolio holdings must use Holding")
        if any(not isinstance(item, WatchItem) for item in self.watch_items):
            raise TypeError("portfolio watch items must use WatchItem")
        if not isinstance(self.source, str):
            raise TypeError("portfolio source must be a string")
        if not self.source:
            raise ValueError("portfolio source must not be empty")
        holding_ids = tuple(_instrument_id(item.instrument) for item in self.holdings)
        watch_ids = tuple(_instrument_id(item.instrument) for item in self.watch_items)
        if holding_ids != tuple(sorted(holding_ids)) or watch_ids != tuple(sorted(watch_ids)):
            raise ValueError("portfolio instruments must be sorted by MIC and symbol")
        if len(set(holding_ids)) != len(holding_ids):
            raise ValueError("portfolio holdings must have unique instruments")
        if len(set(watch_ids)) != len(watch_ids):
            raise ValueError("portfolio watch items must have unique instruments")
        if set(holding_ids) & set(watch_ids):
            raise ValueError("held instruments must not also be watch items")

    @property
    def normalized_as_of(self) -> datetime:
        """Return the observation instant normalized to UTC."""

        return as_utc(self.as_of)


@dataclass(frozen=True, slots=True)
class PersonalInvestmentContext:
    """Small explicit set of personal inputs used by a decision policy."""

    maximum_position_weight: Decimal = Decimal("0.20")

    def __post_init__(self) -> None:
        _finite_non_negative(self.maximum_position_weight, "maximum position weight", positive=True)
        if self.maximum_position_weight > 1:
            raise ValueError("maximum position weight must not exceed one")


def _instrument_id(instrument: Instrument) -> tuple[str, str]:
    return instrument.mic, instrument.symbol
