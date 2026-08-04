"""Contract for importing one manifest-backed daily-bar bundle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


@runtime_checkable
class DailyBarBundleImporter(Protocol):
    """Normalize a local bundle without persisting application state."""

    def import_bundle(self, path: Path) -> ImportedDailyBars: ...
