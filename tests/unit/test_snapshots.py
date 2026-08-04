from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from marketsieve_cli.adapters.snapshots import SnapshotStore
from marketsieve_extension_api import DailyBarFetchRequest
from marketsieve_source_csv import CsvDailyBarImporter


def write_bundle(path: Path) -> Path:
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
            "availability_basis": "published",
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


def test_snapshot_is_content_addressed_idempotent_and_resolvable(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))
    store = SnapshotStore(tmp_path / "state")

    first = store.put_daily_bars(imported)
    second = store.put_daily_bars(imported)

    assert first.object_id == second.object_id
    assert len(first.object_id) == 64
    assert store.resolve("offline-jp", "XTKS:7203").object_id == first.object_id
    assert store.verify(first.object_id) == first
    assert len(store.normalized(first.object_id)["bars"]) == 2


def test_snapshot_verification_detects_normalized_mutation(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))
    store = SnapshotStore(tmp_path / "state")
    stored = store.put_daily_bars(imported)
    normalized = (
        tmp_path / "state" / "objects" / stored.object_id / "normalized" / "daily-bars.json"
    )
    normalized.write_bytes(normalized.read_bytes().replace(b'"close":"112"', b'"close":"999"'))

    with pytest.raises(ValueError, match="checksum"):
        store.verify(stored.object_id)


def test_fetch_request_boundaries_are_part_of_snapshot_identity(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))
    first_request = DailyBarFetchRequest(
        imported.source_profile,
        imported.instrument,
        date(2026, 7, 29),
        date(2026, 7, 31),
        imported.adjustment,
        {},
    )
    second_request = replace(first_request, start=date(2026, 7, 30))
    store = SnapshotStore(tmp_path / "state")

    first = store.put_daily_bars(replace(imported, fetch_request=first_request))
    second = store.put_daily_bars(replace(imported, fetch_request=second_request))

    assert first.object_id != second.object_id
    assert first.manifest["request"]["start"] == "2026-07-29"
    assert second.manifest["request"]["start"] == "2026-07-30"


def test_pending_directory_is_not_a_snapshot(tmp_path: Path) -> None:
    pending = tmp_path / "state" / "objects" / ".pending-interrupted"
    pending.mkdir(parents=True)

    assert SnapshotStore(tmp_path / "state").list() == ()


def test_snapshot_lookup_rejects_path_traversal(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "state")

    with pytest.raises(ValueError, match="source profile"):
        store.resolve("../outside", "XTKS:7203")
    with pytest.raises(ValueError, match="MIC:SYMBOL"):
        store.resolve("offline-jp", "XTKS:../../outside")


def test_snapshot_store_rejects_symlinked_state_directory(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))
    outside = tmp_path / "outside"
    outside.mkdir()
    state = tmp_path / "state"
    state.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic links"):
        SnapshotStore(state).put_daily_bars(imported)
