"""Contract for importing one manifest-backed daily-bar bundle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from marketsieve.data.daily import Adjustment, DailyBar
from marketsieve.domain import Instrument


class AvailabilityBasis(StrEnum):
    """Timestamp used to decide when an observation is knowable."""

    PUBLISHED = "published"
    RETRIEVAL = "retrieval"


@dataclass(frozen=True, slots=True)
class InstrumentProfile:
    """Provider facts that describe one exchange-qualified instrument."""

    observation_date: date
    published_at: datetime | None
    names: tuple[tuple[str, str], ...]
    attributes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if type(self.observation_date) is not date:
            raise TypeError("profile observation_date must be datetime.date")
        if self.published_at is not None and (
            self.published_at.tzinfo is None or self.published_at.utcoffset() is None
        ):
            raise ValueError("profile published_at must include a UTC offset")
        if any(not key or not value for key, value in (*self.names, *self.attributes)):
            raise ValueError("profile facts must not contain empty keys or values")


@dataclass(frozen=True, slots=True)
class ImportedDailyBars:
    """Normalized output of one daily-bar bundle importer."""

    source_profile: str
    source_name: str
    source_version: str
    dataset: str
    instrument: Instrument
    adjustment: Adjustment
    retrieved_at: datetime
    availability_basis: AvailabilityBasis
    bars: tuple[DailyBar, ...]
    bundle_hash: str
    instrument_profile: InstrumentProfile | None = None
    fetch_request: DailyBarFetchRequest | None = None

    def __post_init__(self) -> None:
        text_fields = (
            self.source_profile,
            self.source_name,
            self.source_version,
            self.dataset,
            self.bundle_hash,
        )
        if any(not value for value in text_fields):
            raise ValueError("import identity fields must not be empty")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a UTC offset")
        dates = tuple(bar.trading_date for bar in self.bars)
        if not dates:
            raise ValueError("an imported daily-bar bundle must not be empty")
        if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("imported daily bars must have unique ascending dates")
        if any(bar.adjustment != self.adjustment for bar in self.bars):
            raise ValueError("imported bars must preserve the declared adjustment")
        if self.fetch_request is not None:
            request = self.fetch_request
            if (
                request.source_profile != self.source_profile
                or request.instrument != self.instrument
                or request.adjustment != self.adjustment
            ):
                raise ValueError("fetch request identity must match imported daily bars")
            if any(not request.start <= value <= request.end for value in dates):
                raise ValueError("fetched daily bars must remain inside the requested range")


@runtime_checkable
class DailyBarBundleImporter(Protocol):
    """Normalize a local bundle without persisting application state."""

    def import_bundle(self, path: Path) -> ImportedDailyBars: ...


@dataclass(frozen=True, slots=True)
class DailyBarSourceConfiguration:
    """Complete non-secret configuration for one daily-bar source profile."""

    currency: str
    timezone: str
    settings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.currency or not self.timezone:
            raise ValueError("daily-bar source currency and timezone must not be empty")


@dataclass(frozen=True, slots=True)
class DailyBarFetchRequest:
    """Exact provider request selected by one configured source profile."""

    source_profile: str
    instrument: Instrument
    start: date
    end: date
    adjustment: Adjustment
    settings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.source_profile:
            raise ValueError("source_profile must not be empty")
        if self.start > self.end:
            raise ValueError("fetch start must not exceed end")


@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    """Credential-safe readiness result for one selected source."""

    ready: bool
    code: str
    message: str
    recovery: str | None = None


@runtime_checkable
class DailyBarFetcher(Protocol):
    """Fetch one exact daily-bar range without persisting application state."""

    def doctor(self, configuration: DailyBarSourceConfiguration) -> SourceDiagnostic: ...

    def fetch(self, request: DailyBarFetchRequest) -> ImportedDailyBars: ...
