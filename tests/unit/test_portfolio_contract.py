from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from marketsieve import PortfolioSnapshot
from marketsieve_extension_api import (
    ImportedPortfolioSnapshot,
    verify_portfolio_snapshot_importer,
)

OBSERVED_AT = datetime(2026, 8, 6, 3, 48, 40, tzinfo=UTC)


def imported(*, as_of: datetime = OBSERVED_AT) -> ImportedPortfolioSnapshot:
    return ImportedPortfolioSnapshot(
        PortfolioSnapshot(as_of, (), (), "fixture"),
        "fixture",
        "0.7.0",
        "empty/v1",
        "a" * 64,
        ("empty_portfolio",),
    )


class ConformingImporter:
    def import_portfolio(self, path: Path, *, as_of: datetime) -> ImportedPortfolioSnapshot:
        assert path.name == "portfolio.csv"
        return replace(imported(), snapshot=replace(imported().snapshot, as_of=as_of))


class WrongResultImporter:
    def import_portfolio(self, path: Path, *, as_of: datetime) -> object:
        return path, as_of


class WrongTimestampImporter:
    def import_portfolio(self, path: Path, *, as_of: datetime) -> ImportedPortfolioSnapshot:
        return imported()


class NormalizedTimestampImporter:
    def import_portfolio(self, path: Path, *, as_of: datetime) -> ImportedPortfolioSnapshot:
        normalized = as_of.astimezone(UTC)
        return replace(imported(), snapshot=replace(imported().snapshot, as_of=normalized))


def test_portfolio_importer_conformance_preserves_exact_timestamp(tmp_path: Path) -> None:
    result = verify_portfolio_snapshot_importer(
        ConformingImporter(), tmp_path / "portfolio.csv", as_of=OBSERVED_AT
    )

    assert result.snapshot.as_of == OBSERVED_AT


def test_portfolio_importer_conformance_rejects_wrong_capability(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="does not implement"):
        verify_portfolio_snapshot_importer(object(), tmp_path / "portfolio.csv", as_of=OBSERVED_AT)


def test_portfolio_importer_conformance_rejects_wrong_result(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="non-conforming"):
        verify_portfolio_snapshot_importer(
            WrongResultImporter(), tmp_path / "portfolio.csv", as_of=OBSERVED_AT
        )


def test_portfolio_importer_conformance_rejects_changed_timestamp(tmp_path: Path) -> None:
    requested = datetime(2026, 8, 7, tzinfo=UTC)
    with pytest.raises(ValueError, match="exact portfolio as_of"):
        verify_portfolio_snapshot_importer(
            WrongTimestampImporter(), tmp_path / "portfolio.csv", as_of=requested
        )


def test_portfolio_importer_conformance_rejects_changed_offset_representation(
    tmp_path: Path,
) -> None:
    requested = datetime.fromisoformat("2026-08-06T12:48:40+09:00")
    with pytest.raises(ValueError, match="exact portfolio as_of"):
        verify_portfolio_snapshot_importer(
            NormalizedTimestampImporter(), tmp_path / "portfolio.csv", as_of=requested
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"source_name": ""}, "source identity"),
        ({"source_hash": "A" * 64}, "lowercase SHA-256"),
        ({"diagnostics": ("empty", "empty")}, "unique"),
    ),
)
def test_imported_portfolio_rejects_ambiguous_provenance(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(imported(), **changes)


@pytest.mark.parametrize(
    "changes",
    (
        {"source_name": 1},
        {"source_version": 1},
        {"dataset": 1},
        {"source_hash": 1},
        {"diagnostics": ["empty"]},
        {"diagnostics": (1,)},
    ),
)
def test_imported_portfolio_rejects_non_string_provenance(changes: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        replace(imported(), **changes)
