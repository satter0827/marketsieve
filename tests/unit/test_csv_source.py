from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from marketsieve_extension_api import AvailabilityBasis, InstrumentUniverseImporter, UniverseRequest
from marketsieve_source_csv import CsvDailyBarImporter, CsvInstrumentUniverseImporter


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


def test_csv_universe_is_strict_sorted_bounded_and_content_identified(tmp_path: Path) -> None:
    path = tmp_path / "us.csv"
    path.write_text(
        "symbol,mic,currency,timezone,as_of\n"
        "AAA,XASE,USD,America/New_York,2026-08-01T12:00:00+00:00\n"
        "MSFT,XNAS,USD,America/New_York,2026-08-01T12:00:00+00:00\n"
        "BRK.B,XNYS,USD,America/New_York,2026-08-01T12:00:00+00:00\n",
        encoding="utf-8",
    )
    importer = CsvInstrumentUniverseImporter()
    request = UniverseRequest("offline-us", "us", 1, {}, ("XNAS", "XNYS"))

    imported = importer.import_universe(path, request)

    assert isinstance(importer, InstrumentUniverseImporter)
    assert [(item.mic, item.symbol) for item in imported.instruments] == [("XNAS", "MSFT")]
    assert imported.provider_total == 2
    assert imported.truncated is True
    assert imported.diagnostics == ("ineligible_mics_excluded:1", "limit_reached:1")
    assert len(imported.source_hash) == 64


def test_csv_universe_rejects_duplicates_and_mixed_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "symbol,mic,currency,timezone,as_of\n"
        "MSFT,XNAS,USD,America/New_York,2026-08-01T12:00:00+00:00\n"
        "MSFT,XNAS,USD,America/New_York,2026-08-02T12:00:00+00:00\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="CSV line 3"):
        CsvInstrumentUniverseImporter().import_universe(
            path, UniverseRequest("offline-us", "us", 100, {})
        )


@pytest.mark.parametrize(
    ("contents", "message"),
    (
        (b"\xff", "UTF-8"),
        (b"symbol,mic\nMSFT,XNAS\n", "columns"),
        (b"symbol,mic,currency,timezone,as_of\n", "at least one"),
        (
            b"symbol,mic,currency,timezone,as_of\n"
            b"msft,XNAS,USD,America/New_York,2026-08-01T12:00:00+00:00\n",
            "CSV line 2",
        ),
    ),
)
def test_csv_universe_rejects_malformed_files(
    tmp_path: Path, contents: bytes, message: str
) -> None:
    path = tmp_path / "bad.csv"
    path.write_bytes(contents)

    with pytest.raises(ValueError, match=message):
        CsvInstrumentUniverseImporter().import_universe(
            path, UniverseRequest("offline-us", "us", 100, {})
        )


def test_csv_universe_rejects_missing_path_and_duplicate_identity(tmp_path: Path) -> None:
    importer = CsvInstrumentUniverseImporter()
    request = UniverseRequest("offline-us", "us", 100, {})
    with pytest.raises(ValueError, match="regular file"):
        importer.import_universe(tmp_path / "missing.csv", request)

    path = tmp_path / "duplicate.csv"
    path.write_text(
        "symbol,mic,currency,timezone,as_of\n"
        "MSFT,XNAS,USD,America/New_York,2026-08-01T12:00:00+00:00\n"
        "MSFT,XNAS,USD,America/New_York,2026-08-01T12:00:00+00:00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        importer.import_universe(path, request)
