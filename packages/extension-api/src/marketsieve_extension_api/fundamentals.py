"""Financial-fact and corporate-event source contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from marketsieve.domain import Instrument

from .daily import AvailabilityBasis, SourceDiagnostic


class FinancialPeriod(StrEnum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    INTERIM_YTD = "interim_ytd"
    TTM = "ttm"


class Consolidation(StrEnum):
    CONSOLIDATED = "consolidated"
    NON_CONSOLIDATED = "non_consolidated"


class Revision(StrEnum):
    REPORTED = "reported"
    RESTATED = "restated"


class CorporateEventType(StrEnum):
    DIVIDEND = "dividend"
    EARNINGS = "earnings"
    SPLIT = "split"


@dataclass(frozen=True, slots=True)
class SourceConfiguration:
    currency: str
    timezone: str
    settings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.currency, str) or not isinstance(self.timezone, str):
            raise TypeError("source currency and timezone must be strings")
        if not self.currency or not self.timezone:
            raise ValueError("source currency and timezone must not be empty")
        if not isinstance(self.settings, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.settings.items()
        ):
            raise TypeError("source settings must map strings to strings")


@dataclass(frozen=True, slots=True)
class FactFetchRequest:
    source_profile: str
    instrument: Instrument
    start: date
    end: date
    settings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("fact fetch instrument must be an Instrument")
        if type(self.start) is not date or type(self.end) is not date:
            raise TypeError("fact fetch boundaries must be dates")
        if not self.source_profile or self.start > self.end:
            raise ValueError("fact fetch request must have a profile and ascending dates")
        if not isinstance(self.settings, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.settings.items()
        ):
            raise TypeError("fact fetch settings must map strings to strings")


@dataclass(frozen=True, slots=True)
class FinancialFact:
    concept: str
    provider_fact: str
    accounting_standard: str | None
    period: FinancialPeriod
    provider_period: str
    fiscal_period_start: date
    fiscal_period_end: date
    published_at: datetime | None
    available_at: datetime
    availability_basis: AvailabilityBasis
    consolidation: Consolidation
    revision: Revision
    currency: str
    scale: int
    value: Decimal

    def __post_init__(self) -> None:
        if type(self.fiscal_period_start) is not date or type(self.fiscal_period_end) is not date:
            raise TypeError("financial fact fiscal boundaries must be dates")
        if not isinstance(self.value, Decimal):
            raise TypeError("financial fact value must use decimal.Decimal")
        if not isinstance(self.period, FinancialPeriod) or not isinstance(
            self.consolidation, Consolidation
        ):
            raise TypeError("financial fact period and consolidation must use contract enums")
        if not isinstance(self.revision, Revision) or not isinstance(
            self.availability_basis, AvailabilityBasis
        ):
            raise TypeError("financial fact revision and availability must use contract enums")
        if not all(
            isinstance(value, str)
            for value in (self.concept, self.provider_fact, self.provider_period, self.currency)
        ):
            raise TypeError("financial fact identity values must be strings")
        if (
            not self.concept
            or not self.provider_fact
            or not self.provider_period
            or not self.currency
        ):
            raise ValueError("financial fact identity must not be empty")
        if self.fiscal_period_start > self.fiscal_period_end:
            raise ValueError("financial fact period must be ascending")
        if self.published_at is not None and (
            self.published_at.tzinfo is None or self.published_at.utcoffset() is None
        ):
            raise ValueError("financial fact published_at must include a UTC offset")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("financial fact available_at must include a UTC offset")
        if self.availability_basis is AvailabilityBasis.PUBLISHED and (
            self.published_at is None or self.available_at != self.published_at
        ):
            raise ValueError("published financial facts must use published_at as available_at")
        if not isinstance(self.scale, int) or isinstance(self.scale, bool):
            raise TypeError("financial fact scale must be an integer")
        if self.scale <= 0 or not self.value.is_finite():
            raise ValueError("financial fact scale and value must be finite and positive-scale")


@dataclass(frozen=True, slots=True)
class CorporateEvent:
    event_type: CorporateEventType
    observation_date: date
    effective_date: date
    published_at: datetime | None
    available_at: datetime
    availability_basis: AvailabilityBasis
    values: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if type(self.observation_date) is not date or type(self.effective_date) is not date:
            raise TypeError("event observation and effective values must be dates")
        if not isinstance(self.event_type, CorporateEventType) or not isinstance(
            self.availability_basis, AvailabilityBasis
        ):
            raise TypeError("event type and availability must use contract enums")
        if self.published_at is not None and (
            self.published_at.tzinfo is None or self.published_at.utcoffset() is None
        ):
            raise ValueError("event published_at must include a UTC offset")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("event available_at must include a UTC offset")
        if self.availability_basis is AvailabilityBasis.PUBLISHED and self.published_at is None:
            raise ValueError("published events require published_at")
        if (
            self.availability_basis is AvailabilityBasis.PUBLISHED
            and self.available_at != self.published_at
        ):
            raise ValueError("published events must use published_at as available_at")
        if any(not key or not value for key, value in self.values):
            raise ValueError("event values must not contain empty keys or values")
        if len({key for key, _ in self.values}) != len(self.values):
            raise ValueError("event value keys must be unique")


@dataclass(frozen=True, slots=True)
class ImportedFinancials:
    request: FactFetchRequest
    source_name: str
    source_version: str
    dataset: str
    retrieved_at: datetime
    facts: tuple[FinancialFact, ...]
    response_hash: str
    missing_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request, FactFetchRequest):
            raise TypeError("financial request must use FactFetchRequest")
        if any(not isinstance(fact, FinancialFact) for fact in self.facts):
            raise TypeError("financial facts must use FinancialFact")
        if (
            not self.source_name
            or not self.source_version
            or not self.dataset
            or not self.response_hash
        ):
            raise ValueError("financial import identity must not be empty")
        if len(self.response_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.response_hash
        ):
            raise ValueError("financial response_hash must be a lowercase SHA-256 digest")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("financial retrieved_at must include a UTC offset")
        if not self.facts and not self.missing_reasons:
            raise ValueError("financial import must contain facts or missing reasons")
        if any(fact.available_at > self.retrieved_at for fact in self.facts):
            raise ValueError("financial facts must not be available after retrieval")
        identities = tuple(
            (
                fact.provider_fact,
                fact.period,
                fact.provider_period,
                fact.fiscal_period_start,
                fact.fiscal_period_end,
                fact.published_at,
                fact.available_at,
                fact.consolidation,
                fact.revision,
                fact.currency,
                fact.scale,
            )
            for fact in self.facts
        )
        if len(set(identities)) != len(identities):
            raise ValueError("financial facts must have unique provider observation identities")
        if any(not reason for reason in self.missing_reasons) or len(
            set(self.missing_reasons)
        ) != len(self.missing_reasons):
            raise ValueError("financial missing reasons must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class ImportedEvents:
    request: FactFetchRequest
    source_name: str
    source_version: str
    dataset: str
    retrieved_at: datetime
    events: tuple[CorporateEvent, ...]
    response_hash: str
    missing_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request, FactFetchRequest):
            raise TypeError("event request must use FactFetchRequest")
        if any(not isinstance(event, CorporateEvent) for event in self.events):
            raise TypeError("events must use CorporateEvent")
        if (
            not self.source_name
            or not self.source_version
            or not self.dataset
            or not self.response_hash
        ):
            raise ValueError("event import identity must not be empty")
        if len(self.response_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.response_hash
        ):
            raise ValueError("event response_hash must be a lowercase SHA-256 digest")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("event retrieved_at must include a UTC offset")
        if not self.events and not self.missing_reasons:
            raise ValueError("event import must contain events or missing reasons")
        if any(event.available_at > self.retrieved_at for event in self.events):
            raise ValueError("events must not be available after retrieval")
        identities = tuple(
            (
                event.event_type,
                event.observation_date,
                event.effective_date,
                event.published_at,
                event.available_at,
            )
            for event in self.events
        )
        if len(set(identities)) != len(identities):
            raise ValueError("events must have unique provider observation identities")
        if any(not reason for reason in self.missing_reasons) or len(
            set(self.missing_reasons)
        ) != len(self.missing_reasons):
            raise ValueError("event missing reasons must be non-empty and unique")


@runtime_checkable
class FinancialFetcher(Protocol):
    def doctor_financials(self, configuration: SourceConfiguration) -> SourceDiagnostic: ...

    def fetch_financials(self, request: FactFetchRequest) -> ImportedFinancials: ...


@runtime_checkable
class EventFetcher(Protocol):
    def doctor_events(self, configuration: SourceConfiguration) -> SourceDiagnostic: ...

    def fetch_events(self, request: FactFetchRequest) -> ImportedEvents: ...
