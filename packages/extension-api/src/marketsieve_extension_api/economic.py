"""Acquisition contract for one explicit economic series."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from marketsieve import EconomicSeries
from marketsieve_extension_api.daily import SourceDiagnostic


@dataclass(frozen=True, slots=True)
class EconomicSeriesSourceConfiguration:
    """Non-secret settings for an economic-series source."""

    settings: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class EconomicSeriesFetchRequest:
    """Exact series, observation range, and historical knowledge date to fetch."""

    source_profile: str
    series_id: str
    observation_start: date
    observation_end: date
    knowledge_date: date
    settings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.source_profile:
            raise ValueError("economic source profile must not be empty")
        if not self.series_id:
            raise ValueError("economic series ID must not be empty")
        if any(
            type(value) is not date
            for value in (self.observation_start, self.observation_end, self.knowledge_date)
        ):
            raise TypeError("economic request dates must use datetime.date")
        if self.observation_start > self.observation_end:
            raise ValueError("economic observation start must not exceed end")


@dataclass(frozen=True, slots=True)
class ImportedEconomicSeries:
    """Normalized result of one complete provider request."""

    request: EconomicSeriesFetchRequest
    source_name: str
    source_version: str
    dataset: str
    retrieved_at: datetime
    series: EconomicSeries
    response_hash: str

    def __post_init__(self) -> None:
        if any(not value for value in (self.source_name, self.source_version, self.dataset)):
            raise ValueError("economic import identity fields must not be empty")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("economic retrieval time must include a UTC offset")
        if self.series.series_id != self.request.series_id:
            raise ValueError("economic result series must match its request")
        if self.series.knowledge_date != self.request.knowledge_date:
            raise ValueError("economic result knowledge date must match its request")
        observed_dates = (
            *(value.observation_date for value in self.series.observations),
            *self.series.missing_observation_dates,
        )
        if any(
            not self.request.observation_start <= value <= self.request.observation_end
            for value in observed_dates
        ):
            raise ValueError("economic observations must remain inside the requested range")
        if len(self.response_hash) != 64 or any(
            value not in "0123456789abcdef" for value in self.response_hash
        ):
            raise ValueError("economic response hash must be a lowercase SHA-256 digest")


@runtime_checkable
class EconomicSeriesFetcher(Protocol):
    """Fetch one exact economic series without persisting application state."""

    def doctor_economic_series(
        self, configuration: EconomicSeriesSourceConfiguration
    ) -> SourceDiagnostic: ...

    def fetch_economic_series(
        self, request: EconomicSeriesFetchRequest
    ) -> ImportedEconomicSeries: ...
