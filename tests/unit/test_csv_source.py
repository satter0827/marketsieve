from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from marketsieve_extension_api import AvailabilityBasis
from marketsieve_source_csv import CsvDailyBarImporter


def write_bundle(path: Path, *, basis: str = "published") -> Path:
    path.mkdir()
    manifest = {
        "schema": "marketsieve-csv-daily-bars/v1",
        "source_profile": "offline-jp",
        "source": "csv",
        "source_version": "fixture-1",
        "retrieved_at": "2026-08-01T12:00:00+00:00",
        "instrument": {
            "symbol": "7203",
            "mic": "XTKS",
            "currency": "JPY",
            "timezone": "Asia/Tokyo",
        },
        "dataset": {
            "name": "example-bars",
            "file": "daily-bars.csv",
            "adjustment": "raw",
            "availability_basis": basis,
        },
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (path / "daily-bars.csv").write_text(
        "trading_date,open,high,low,close,volume,published_at\n"
        "2026-07-30,100,110,90,105,1000,2026-07-30T06:00:00+00:00\n"
        "2026-07-31,105,115,101,112,1200,2026-07-31T06:00:00+00:00\n",
        encoding="utf-8",
    )
    return path


def test_csv_bundle_import_is_explicit_and_time_correct(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))

    assert imported.source_profile == "offline-jp"
    assert imported.instrument.mic == "XTKS"
    assert imported.availability_basis is AvailabilityBasis.PUBLISHED
    assert [str(bar.close) for bar in imported.bars] == ["105", "112"]
    assert imported.bars[0].available_at.isoformat() == "2026-07-30T06:00:00+00:00"


def test_retrieval_basis_does_not_backdate_values(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(
        write_bundle(tmp_path / "bundle", basis="retrieval")
    )

    assert {bar.available_at for bar in imported.bars} == {imported.retrieved_at}


def test_import_contract_rejects_non_digest_bundle_identity(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))

    with pytest.raises(ValueError, match="SHA-256"):
        replace(imported, bundle_hash="not-a-digest")


def test_csv_bundle_rejects_implicit_or_unsafe_metadata(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path / "bundle")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["dataset"]["file"] = "../daily-bars.csv"
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="without path components"):
        CsvDailyBarImporter().import_bundle(bundle)
