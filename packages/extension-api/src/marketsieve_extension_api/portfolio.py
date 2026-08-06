"""Small contract for importing a brokerage portfolio snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from marketsieve.portfolio import PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class ImportedPortfolioSnapshot:
    """Normalized portfolio plus source identity without retained source bytes."""

    snapshot: PortfolioSnapshot
    source_name: str
    source_version: str
    dataset: str
    source_hash: str
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, PortfolioSnapshot):
            raise TypeError("imported portfolio snapshot must use PortfolioSnapshot")
        identity = (self.source_name, self.source_version, self.dataset)
        if any(not isinstance(value, str) for value in identity):
            raise TypeError("portfolio import source identity must use strings")
        if any(not value for value in identity):
            raise ValueError("portfolio import source identity must not be empty")
        if not isinstance(self.source_hash, str):
            raise TypeError("portfolio source hash must use a string")
        if len(self.source_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_hash
        ):
            raise ValueError("portfolio source hash must be a lowercase SHA-256 digest")
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(value, str) for value in self.diagnostics
        ):
            raise TypeError("portfolio diagnostics must use a tuple of strings")
        if any(not value for value in self.diagnostics) or len(set(self.diagnostics)) != len(
            self.diagnostics
        ):
            raise ValueError("portfolio diagnostics must be non-empty and unique")


@runtime_checkable
class PortfolioSnapshotImporter(Protocol):
    """Normalize one local brokerage export without persisting it."""

    def import_portfolio(self, path: Path, *, as_of: datetime) -> ImportedPortfolioSnapshot: ...
