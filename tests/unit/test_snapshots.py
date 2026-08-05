from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from marketsieve_cli.adapters.snapshots import SnapshotStore
from marketsieve_cli.application.snapshots import SnapshotService
from marketsieve_extension_api import (
    AvailabilityBasis,
    Consolidation,
    CorporateEvent,
    CorporateEventType,
    DailyBarFetchRequest,
    FactFetchRequest,
    FilingDocument,
    FinancialFact,
    FinancialPeriod,
    ImportedEvents,
    ImportedFinancials,
    InstrumentProfile,
    Revision,
)
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


def test_snapshot_verification_rejects_manifest_path_escape(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))
    store = SnapshotStore(tmp_path / "state")
    stored = store.put_daily_bars(imported)
    manifest = tmp_path / "state" / "objects" / stored.object_id / "manifest.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["normalized"]["path"] = "../../outside.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="path"):
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


def test_financial_and_event_snapshots_have_independent_kind_references(tmp_path: Path) -> None:
    daily = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))
    request = FactFetchRequest(
        daily.source_profile,
        daily.instrument,
        date(2026, 7, 1),
        date(2026, 7, 31),
        {},
    )
    published_at = datetime(2026, 7, 31, 6, tzinfo=UTC)
    filing = FilingDocument(
        "doc-2026",
        "issuer-7203",
        "annual-report",
        published_at,
        FinancialPeriod.ANNUAL,
        date(2025, 4, 1),
        date(2026, 3, 31),
        "J-GAAP",
        Consolidation.CONSOLIDATED,
        "JPY",
    )
    amendment_published_at = datetime(2026, 8, 1, 6, tzinfo=UTC)
    amendment = replace(
        filing,
        filing_id="doc-2026-amended",
        document_type="annual-report-amendment",
        published_at=amendment_published_at,
        amends_filing_id=filing.filing_id,
    )
    financials = ImportedFinancials(
        request,
        "fixture",
        "v1",
        "financials",
        datetime(2026, 8, 2, tzinfo=UTC),
        (
            FinancialFact(
                "revenue",
                "Sales",
                "J-GAAP",
                FinancialPeriod.ANNUAL,
                "FY",
                date(2025, 4, 1),
                date(2026, 3, 31),
                published_at,
                published_at,
                AvailabilityBasis.PUBLISHED,
                Consolidation.CONSOLIDATED,
                Revision.REPORTED,
                "JPY",
                1,
                Decimal("1000"),
                filing.filing_id,
            ),
            FinancialFact(
                "revenue",
                "Sales",
                "J-GAAP",
                FinancialPeriod.ANNUAL,
                "FY",
                date(2025, 4, 1),
                date(2026, 3, 31),
                amendment_published_at,
                amendment_published_at,
                AvailabilityBasis.PUBLISHED,
                Consolidation.CONSOLIDATED,
                Revision.RESTATED,
                "JPY",
                1,
                Decimal("1100"),
                amendment.filing_id,
            ),
        ),
        "a" * 64,
        (),
        (filing, amendment),
    )
    events = ImportedEvents(
        request,
        "fixture",
        "v1",
        "events",
        datetime(2026, 8, 1, tzinfo=UTC),
        (
            CorporateEvent(
                CorporateEventType.EARNINGS,
                date(2026, 7, 31),
                date(2026, 7, 31),
                None,
                datetime(2026, 7, 20, tzinfo=UTC),
                AvailabilityBasis.RETRIEVAL,
                (("quarter", "1Q"),),
            ),
        ),
        "b" * 64,
        ("split_not_available",),
    )
    store = SnapshotStore(tmp_path / "state")

    daily_stored = store.put_daily_bars(daily)
    financial_stored = store.put_financials(financials)
    event_stored = store.put_events(events)
    profiled_stored = daily_stored
    for day, per, digest in ((1, "10", "c" * 64), (2, "14", "d" * 64)):
        profiled_stored = store.put_daily_bars(
            replace(
                daily,
                retrieved_at=datetime(2026, 8, day, tzinfo=UTC),
                bundle_hash=digest,
                instrument_profile=InstrumentProfile(
                    date(2026, 8, day),
                    None,
                    (("ja", "トヨタ自動車"),),
                    (("trailing_per", per),),
                ),
            )
        )

    assert len({daily_stored.object_id, financial_stored.object_id, event_stored.object_id}) == 3
    assert store.resolve("offline-jp", "XTKS:7203").object_id == profiled_stored.object_id
    assert (
        store.resolve("offline-jp", "XTKS:7203", "financials").object_id
        == financial_stored.object_id
    )
    assert store.resolve("offline-jp", "XTKS:7203", "events").object_id == event_stored.object_id
    stored_fact = store.normalized(financial_stored.object_id)["facts"][0]
    assert stored_fact["concept"] == "revenue"
    assert stored_fact["provider_period"] == "FY"
    assert stored_fact["filing_id"] == filing.filing_id
    stored_filing = store.normalized(financial_stored.object_id)["filings"][0]
    assert stored_filing["filing_id"] == filing.filing_id
    assert stored_filing["published_at"] == published_at.isoformat()
    assert store.normalized(event_stored.object_id)["missing_reasons"] == ["split_not_available"]
    service = SnapshotService(cast(Any, None), store, cast(Any, None))
    trend = service.financial_trend("offline-jp", "XTKS:7203", datetime(2026, 8, 2, tzinfo=UTC))
    assert dict(trend.periods[0].values)["revenue"] == Decimal("1100")
    assert service.next_earnings_date(
        "offline-jp", "XTKS:7203", datetime(2026, 7, 25, tzinfo=UTC)
    ) == date(2026, 7, 31)
    valuation = dict(
        service.valuation_history("offline-jp", "XTKS:7203", datetime(2026, 8, 3, tzinfo=UTC))
    )
    assert valuation == {
        "trailing_per.current": "14",
        "trailing_per.history_count": "2",
        "trailing_per.history_max": "14",
        "trailing_per.history_median": "12",
        "trailing_per.history_min": "10",
    }
    assert dict(
        service.valuation_history("offline-jp", "XTKS:7203", datetime(2026, 8, 1, 12, tzinfo=UTC))
    ) == {
        "trailing_per.current": "10",
        "trailing_per.history_count": "1",
    }
    assert (
        service.fundamental_changes("offline-jp", "XTKS:7203", datetime(2026, 7, 30, tzinfo=UTC))
        == ()
    )
    assert dict(
        service.fundamental_changes("offline-jp", "XTKS:7203", datetime(2026, 8, 2, tzinfo=UTC))
    ) == {
        "amends_filing_id": "doc-2026",
        "change_type": "amendment",
        "latest_filing_id": "doc-2026-amended",
        "latest_filing_published_at": "2026-08-01T06:00:00+00:00",
        "latest_filing_type": "annual-report-amendment",
        "latest_period_end": "2026-03-31",
        "restated_concepts": "revenue",
    }
    for method in (
        service.financial_trend,
        service.next_earnings_date,
        service.valuation_history,
        service.fundamental_changes,
    ):
        with pytest.raises(ValueError, match="UTC offset"):
            method("offline-jp", "XTKS:7203", datetime(2026, 8, 2))


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
    with pytest.raises(ValueError, match="kind"):
        store.resolve("offline-jp", "XTKS:7203", "../../outside")


def test_snapshot_store_rejects_symlinked_state_directory(tmp_path: Path) -> None:
    imported = CsvDailyBarImporter().import_bundle(write_bundle(tmp_path / "bundle"))
    outside = tmp_path / "outside"
    outside.mkdir()
    state = tmp_path / "state"
    state.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic links"):
        SnapshotStore(state).put_daily_bars(imported)
