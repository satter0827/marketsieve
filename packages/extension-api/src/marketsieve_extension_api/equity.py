"""Batch equity acquisition contract for broad deterministic analysis."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from marketsieve.data.daily import Adjustment, DailyBar
from marketsieve.domain import Instrument


@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    """Provider readiness without network acquisition."""

    ready: bool
    code: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.ready, bool) or not self.code or not self.message:
            raise ValueError("source diagnostic values must be valid")


@dataclass(frozen=True, slots=True)
class EquityBatchInstrument:
    """One exchange-qualified security and its provider symbol."""

    instrument: Instrument
    provider_symbol: str
    memberships: tuple[str, ...]
    is_benchmark: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("batch instrument must use Instrument")
        if not self.provider_symbol:
            raise ValueError("provider symbol must not be empty")
        if not isinstance(self.is_benchmark, bool):
            raise TypeError("benchmark marker must be boolean")
        if (
            not self.memberships
            or self.memberships != tuple(sorted(self.memberships))
            or len(self.memberships) != len(set(self.memberships))
            or any(not value for value in self.memberships)
        ):
            raise ValueError("memberships must be non-empty, unique, and sorted")


@dataclass(frozen=True, slots=True)
class EquityBatchRequest:
    """Complete bounded request for one broad equity observation run."""

    source_profile: str
    instruments: tuple[EquityBatchInstrument, ...]
    start: date
    end: date
    adjustment: Adjustment
    batch_size: int
    profile_workers: int
    timeout_seconds: int
    max_retries: int
    retry_base_seconds: float
    settings: Mapping[str, str]
    evidence: tuple[str, ...] = ("benchmarks", "company", "financials", "price")

    def __post_init__(self) -> None:
        if not self.source_profile:
            raise ValueError("source profile must not be empty")
        if not self.instruments:
            raise ValueError("batch request requires instruments")
        identities = tuple(
            (value.instrument.mic, value.instrument.symbol) for value in self.instruments
        )
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("batch instruments must be unique and sorted")
        if type(self.start) is not date or type(self.end) is not date:
            raise TypeError("batch request dates must use datetime.date")
        if self.start > self.end:
            raise ValueError("batch start must not exceed end")
        if not isinstance(self.adjustment, Adjustment):
            raise TypeError("batch adjustment must use Adjustment")
        positive = (
            self.batch_size,
            self.profile_workers,
            self.timeout_seconds,
            self.max_retries,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in positive
        ):
            raise ValueError("batch limits must be positive integers")
        if (
            not isinstance(self.retry_base_seconds, (int, float))
            or isinstance(self.retry_base_seconds, bool)
            or not math.isfinite(self.retry_base_seconds)
            or self.retry_base_seconds < 0
        ):
            raise ValueError("retry base seconds must be a finite non-negative number")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.settings.items()
        ):
            raise TypeError("batch settings must map strings to strings")
        allowed = {"benchmarks", "company", "financials", "price"}
        if (
            not self.evidence
            or self.evidence != tuple(sorted(set(self.evidence)))
            or set(self.evidence) - allowed
        ):
            raise ValueError("batch evidence must be unique, sorted, and supported")


@dataclass(frozen=True, slots=True)
class EquityAcquisitionFailure:
    """Stable field or acquisition failure without provider fallback."""

    instrument: Instrument
    stage: str
    field: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("failure instrument must use Instrument")
        if any(not value for value in (self.stage, self.field, self.reason)):
            raise ValueError("failure values must not be empty")


@dataclass(frozen=True, slots=True)
class EquityBatchObservation:
    """Normalized current and historical evidence for one security."""

    requested: EquityBatchInstrument
    retrieved_at: datetime
    bars: tuple[DailyBar, ...]
    profile: tuple[tuple[str, str], ...]
    financials: tuple[tuple[str, str], ...]
    source_hash: str

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("observation retrieval time must include a UTC offset")
        dates = tuple(value.trading_date for value in self.bars)
        if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("observation bars must have unique ascending dates")
        for values, name in ((self.profile, "profile"), (self.financials, "financials")):
            keys = tuple(key for key, _ in values)
            if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
                raise ValueError(f"observation {name} keys must be unique and sorted")
            if any(not key or not value for key, value in values):
                raise ValueError(f"observation {name} values must not be empty")
        if len(self.source_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_hash
        ):
            raise ValueError("observation source hash must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ImportedEquityBatch:
    """Normalized output of one exact provider batch request."""

    request: EquityBatchRequest
    source_name: str
    source_version: str
    dataset: str
    retrieved_at: datetime
    observations: tuple[EquityBatchObservation, ...]
    failures: tuple[EquityAcquisitionFailure, ...]
    response_hash: str

    def __post_init__(self) -> None:
        if any(not value for value in (self.source_name, self.source_version, self.dataset)):
            raise ValueError("batch source identity must not be empty")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("batch retrieval time must include a UTC offset")
        identities = tuple(
            (value.requested.instrument.mic, value.requested.instrument.symbol)
            for value in self.observations
        )
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("batch observations must be unique and sorted")
        requested = {
            (value.instrument.mic, value.instrument.symbol) for value in self.request.instruments
        }
        if tuple(value.requested for value in self.observations) != self.request.instruments:
            raise ValueError("batch observations must exactly match every requested instrument")
        if any(
            not self.request.start <= bar.trading_date <= self.request.end
            for observation in self.observations
            for bar in observation.bars
        ):
            raise ValueError("batch observation bars must remain inside the requested range")
        if any(
            bar.adjustment != self.request.adjustment
            for observation in self.observations
            for bar in observation.bars
        ):
            raise ValueError("batch observation bars must preserve the requested adjustment")
        if any(
            (value.instrument.mic, value.instrument.symbol) not in requested
            for value in self.failures
        ):
            raise ValueError("batch failure was not requested")
        if len(self.response_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.response_hash
        ):
            raise ValueError("batch response hash must be a lowercase SHA-256 digest")


@runtime_checkable
class EquityBatchFetcher(Protocol):
    """Fetch a broad equity set without persistence or source substitution."""

    def doctor(self) -> SourceDiagnostic: ...

    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch: ...
