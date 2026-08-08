"""Provider-neutral contract for one security research acquisition."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from marketsieve.data.daily import Adjustment, DailyBar
from marketsieve.domain import Instrument

from .equity import EquityAcquisitionFailure


@dataclass(frozen=True, slots=True)
class SecurityResearchRequest:
    source_profile: str
    instrument: Instrument
    provider_symbol: str
    start: date
    end: date
    adjustment: Adjustment
    timeout_seconds: int
    max_retries: int
    retry_base_seconds: float
    settings: Mapping[str, str]
    evidence: tuple[str, ...] = ("benchmarks", "company", "events", "financials", "price")

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_profile, str)
            or not isinstance(self.provider_symbol, str)
            or not self.source_profile
            or not self.provider_symbol
        ):
            raise ValueError("research source identity must not be empty")
        if not isinstance(self.instrument, Instrument):
            raise TypeError("research instrument must use Instrument")
        if type(self.start) is not date or type(self.end) is not date:
            raise TypeError("research request dates must use datetime.date")
        if self.start > self.end:
            raise ValueError("research date range must be ascending")
        if not isinstance(self.adjustment, Adjustment):
            raise TypeError("research adjustment must use Adjustment")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in (self.timeout_seconds, self.max_retries)
        ):
            raise ValueError("research limits must be positive integers")
        if (
            not isinstance(self.retry_base_seconds, (int, float))
            or isinstance(self.retry_base_seconds, bool)
            or not math.isfinite(self.retry_base_seconds)
            or self.retry_base_seconds < 0
        ):
            raise ValueError("research retry wait must be finite and non-negative")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.settings.items()
        ):
            raise TypeError("research settings must map strings to strings")
        allowed = {"benchmarks", "company", "events", "financials", "price"}
        if (
            not self.evidence
            or self.evidence != tuple(sorted(set(self.evidence)))
            or set(self.evidence) - allowed
        ):
            raise ValueError("research evidence must be unique, sorted, and supported")


@dataclass(frozen=True, slots=True)
class ResearchFinancialFact:
    concept: str
    statement: str
    period: str
    fiscal_period_end: date
    currency: str
    value: Decimal

    def __post_init__(self) -> None:
        if any(not value for value in (self.concept, self.statement, self.period, self.currency)):
            raise ValueError("research financial identity must not be empty")
        if self.period not in {"annual", "quarterly"}:
            raise ValueError("research financial period must be annual or quarterly")
        if not self.value.is_finite():
            raise ValueError("research financial value must be finite")


@dataclass(frozen=True, slots=True)
class ResearchEvent:
    event_type: str
    effective_date: date
    values: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.event_type not in {"dividend", "split", "earnings"}:
            raise ValueError("research event type is unsupported")
        keys = tuple(key for key, _ in self.values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("research event values must be unique and sorted")


@dataclass(frozen=True, slots=True)
class ImportedSecurityResearch:
    request: SecurityResearchRequest
    source_name: str
    source_version: str
    retrieved_at: datetime
    bars: tuple[DailyBar, ...]
    company: tuple[tuple[str, str], ...]
    financials: tuple[ResearchFinancialFact, ...]
    events: tuple[ResearchEvent, ...]
    failures: tuple[EquityAcquisitionFailure, ...]
    response_hash: str

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("research retrieval time must include a UTC offset")
        if not self.source_name or not self.source_version:
            raise ValueError("research source identity must not be empty")
        dates = tuple(value.trading_date for value in self.bars)
        if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("research bars must have unique ascending dates")
        if any(not self.request.start <= value <= self.request.end for value in dates):
            raise ValueError("research bars must remain inside the requested range")
        if any(value.adjustment != self.request.adjustment for value in self.bars):
            raise ValueError("research bars must preserve the requested adjustment")
        keys = tuple(key for key, _ in self.company)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("research company keys must be unique and sorted")
        financial_keys = tuple(
            (value.fiscal_period_end, value.period, value.statement, value.concept)
            for value in self.financials
        )
        if financial_keys != tuple(sorted(financial_keys)) or len(financial_keys) != len(
            set(financial_keys)
        ):
            raise ValueError("research financial facts must be unique and sorted")
        event_keys = tuple((value.effective_date, value.event_type) for value in self.events)
        if event_keys != tuple(sorted(event_keys)) or len(event_keys) != len(set(event_keys)):
            raise ValueError("research events must be unique and sorted")
        if any(value.instrument != self.request.instrument for value in self.failures):
            raise ValueError("research failure was not requested")
        if len(self.response_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.response_hash
        ):
            raise ValueError("research response hash must be a lowercase SHA-256 digest")


@runtime_checkable
class SecurityResearchFetcher(Protocol):
    def fetch_research(self, request: SecurityResearchRequest) -> ImportedSecurityResearch: ...
