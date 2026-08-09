"""Market-indicator acquisition contract independent from equity fundamentals."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from marketsieve.model import DailyBar

from .equity import SourceDiagnostic


class MarketIndicatorKind(StrEnum):
    EQUITY_INDEX = "equity_index"
    FX_RATE = "fx_rate"
    VOLATILITY_INDEX = "volatility_index"
    YIELD = "yield"
    COMMODITY = "commodity"


@dataclass(frozen=True, slots=True)
class MarketIndicatorSpec:
    indicator_id: str
    provider_symbol: str
    name: str
    kind: MarketIndicatorKind
    unit: str

    def __post_init__(self) -> None:
        if not all((self.indicator_id, self.provider_symbol, self.name, self.unit)):
            raise ValueError("market indicator strings must not be empty")
        if not isinstance(self.kind, MarketIndicatorKind):
            raise TypeError("market indicator kind must use MarketIndicatorKind")


@dataclass(frozen=True, slots=True)
class MarketIndicatorRequest:
    source_profile: str
    indicators: tuple[MarketIndicatorSpec, ...]
    start: date
    end: date
    timeout_seconds: int
    max_retries: int
    retry_base_seconds: float
    settings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.source_profile or not self.indicators:
            raise ValueError("market indicator request requires a profile and indicators")
        ids = tuple(item.indicator_id for item in self.indicators)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("market indicators must be unique and sorted")
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValueError("market indicator dates are invalid")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in (self.timeout_seconds, self.max_retries)
        ):
            raise ValueError("market indicator limits must be positive integers")
        if (
            not isinstance(self.retry_base_seconds, (int, float))
            or isinstance(self.retry_base_seconds, bool)
            or not math.isfinite(self.retry_base_seconds)
            or self.retry_base_seconds < 0
        ):
            raise ValueError("retry base seconds must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class MarketIndicatorObservation:
    requested: MarketIndicatorSpec
    retrieved_at: datetime
    bars: tuple[DailyBar, ...]
    source_hash: str


@dataclass(frozen=True, slots=True)
class MarketIndicatorFailure:
    indicator_id: str
    stage: str
    field: str
    reason: str


@dataclass(frozen=True, slots=True)
class ImportedMarketIndicators:
    request: MarketIndicatorRequest
    source_name: str
    source_version: str
    retrieved_at: datetime
    observations: tuple[MarketIndicatorObservation, ...]
    failures: tuple[MarketIndicatorFailure, ...]
    response_hash: str


@runtime_checkable
class MarketIndicatorFetcher(Protocol):
    def doctor(self) -> SourceDiagnostic: ...

    def fetch_market_indicators(
        self, request: MarketIndicatorRequest
    ) -> ImportedMarketIndicators: ...
