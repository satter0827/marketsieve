"""Small contracts for importing and fetching instrument universes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from marketsieve.domain import Instrument


@dataclass(frozen=True, slots=True)
class UniverseRequest:
    """Explicit market, profile, and safety bound for one universe operation."""

    source_profile: str
    market: str
    limit: int
    settings: Mapping[str, str]
    eligible_mics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_profile:
            raise ValueError("universe source profile must not be empty")
        if self.market not in {"jp", "us"}:
            raise ValueError("universe market must be jp or us")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit <= 0:
            raise ValueError("universe limit must be a positive integer")
        if (
            self.eligible_mics != tuple(sorted(self.eligible_mics))
            or len(self.eligible_mics) != len(set(self.eligible_mics))
            or any(
                len(item) != 4 or not item.isascii() or not item.isalnum() or item != item.upper()
                for item in self.eligible_mics
            )
        ):
            raise ValueError("universe eligible MICs must be unique, uppercase, and sorted")


@dataclass(frozen=True, slots=True)
class ImportedInstrumentUniverse:
    """Normalized result that preserves provider bounds and acquisition identity."""

    request: UniverseRequest
    source_name: str
    source_version: str
    dataset: str
    retrieved_at: datetime
    instruments: tuple[Instrument, ...]
    source_hash: str
    provider_total: int
    truncated: bool
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not value for value in (self.source_name, self.source_version, self.dataset)):
            raise ValueError("universe source identity must not be empty")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("universe retrieved_at must include a UTC offset")
        if len(self.source_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_hash
        ):
            raise ValueError("universe source hash must be a lowercase SHA-256 digest")
        identities = tuple((item.mic, item.symbol) for item in self.instruments)
        if not identities or identities != tuple(sorted(identities)):
            raise ValueError("imported universe instruments must be non-empty and sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("imported universe instruments must be unique")
        if len(self.instruments) > self.request.limit:
            raise ValueError("imported universe exceeds the requested limit")
        if self.request.eligible_mics and any(
            item.mic not in self.request.eligible_mics for item in self.instruments
        ):
            raise ValueError("imported universe contains an ineligible MIC")
        if self.provider_total < len(self.instruments):
            raise ValueError("provider total must cover every imported instrument")
        if self.truncated != (self.provider_total > len(self.instruments)):
            raise ValueError("universe truncation must match provider and imported counts")
        if any(not value for value in self.diagnostics) or len(set(self.diagnostics)) != len(
            self.diagnostics
        ):
            raise ValueError("universe diagnostics must be non-empty and unique")


@runtime_checkable
class InstrumentUniverseImporter(Protocol):
    def import_universe(
        self, path: Path, request: UniverseRequest
    ) -> ImportedInstrumentUniverse: ...


@runtime_checkable
class InstrumentUniverseFetcher(Protocol):
    def fetch_universe(self, request: UniverseRequest) -> ImportedInstrumentUniverse: ...
