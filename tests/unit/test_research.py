from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from marketsieve.model import Adjustment, Instrument
from marketsieve_cli.adapters.config import Settings
from marketsieve_cli.adapters.explorer import build_research_explorer_data
from marketsieve_cli.adapters.research import ResearchStore
from marketsieve_cli.application.research import ResearchService
from marketsieve_cli.contracts import ResearchBuildInputs
from marketsieve_extension_api import (
    AcquisitionProgress,
    AcquisitionProgressState,
    EquityAcquisitionFailure,
    EquityBatchObservation,
    ImportedEquityBatch,
    ImportedSecurityResearch,
    ResearchEvent,
    ResearchFinancialFact,
    SecurityResearchRequest,
)
from marketsieve_extension_api.testing import fixture_bars

INSTRUMENT = Instrument.create(
    symbol="MSFT", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
)


def _context() -> dict[str, object]:
    return {
        "schema": "market-research-context/v1",
        "snapshot_id": "a" * 64,
        "security": {},
        "market": {},
        "segments": [],
        "definitions": {},
    }


def test_research_events_require_an_explicit_history_window() -> None:
    with pytest.raises(ValueError, match="time-series evidence requires --history-days"):
        ResearchBuildInputs("latest", ("XNAS:MSFT",), ("events",), None)


def test_research_pack_is_self_contained_and_charted(tmp_path: Path) -> None:
    request = SecurityResearchRequest(
        "market-yfinance",
        INSTRUMENT,
        "MSFT",
        date(2026, 1, 1),
        date(2027, 8, 8),
        Adjustment.ADJUSTED,
        30,
        3,
        2.0,
        {},
        ("benchmarks", "company", "events", "financials", "price"),
    )
    imported = ImportedSecurityResearch(
        request,
        "yfinance",
        "1.5.2",
        datetime(2026, 8, 8, tzinfo=UTC),
        tuple(
            replace(bar, adjustment=Adjustment.ADJUSTED)
            for bar in fixture_bars(
                INSTRUMENT, tuple(str(100 + i) for i in range(253)), dataset="research"
            )
        ),
        (("name", "Microsoft"),),
        (
            ResearchFinancialFact(
                "revenue", "income", "annual", date(2025, 6, 30), "USD", Decimal("1")
            ),
        ),
        (ResearchEvent("dividend", date(2026, 5, 15), (("amount", "0.83"),)),),
        (),
        "d" * 64,
    )
    context = {
        "schema": "market-research-context/v1",
        "snapshot_id": "a" * 64,
        "security": {"instrument_id": "XNAS:MSFT"},
        "market": {},
        "segments": [],
        "definitions": {
            "schema": "market-snapshot-definitions/v1",
            "fields": [],
            "missing_reasons": [],
        },
    }
    document = ResearchStore(tmp_path / "research").put(
        imported,
        context,
        minimum_price_observations=252,
        runtime_settings={},
        runtime_settings_hash="b" * 64,
        benchmarks=None,
    )
    root = Path(document["artifacts"]["manifest.json"]).parent

    assert document["schema"] == "security-research/v9"
    assert document["price_coverage_gate_passed"] is True
    assert not list(root.glob("*.csv")) and not list(root.glob("*.xlsx"))
    html = (root / "explorer.html").read_text()
    assert "<svg" in html and "https://" not in html
    assert "Microsoft" not in html and 'id="explorer-data"' not in html
    assert "lazyTable('表データ',rows)" in html
    assert "details.querySelector('.lazy-table').innerHTML=table" in html
    assert "株価鮮度" in html and "財務鮮度" in html
    assert "rticks(min,max)" in html
    assert "CONCEPT[s.name]" in html
    assert "reason_code:status" in html
    explorer = json.loads((root / "explorer-data.json").read_text())
    assert explorer["schema"] == "explorer-data/v5"
    assert explorer["metadata"]["object_contract"] == "security-research/v9"
    assert explorer["sources"]["prices"]["path"] == "prices.jsonl"
    assert "prices" not in explorer
    explorer_schema = json.loads(
        (
            Path(__file__).parents[2] / "packages/cli/schemas/explorer-data/v5/schema.json"
        ).read_text()
    )
    Draft202012Validator(explorer_schema).validate(explorer)
    incomplete_manifest = json.loads((root / "manifest.json").read_text())
    incomplete_manifest["artifacts"].pop("prices.jsonl")
    with pytest.raises(ValueError, match="not registered"):
        build_research_explorer_data(incomplete_manifest, {})
    schema = json.loads(
        (
            Path(__file__).parents[2] / "packages/cli/schemas/security-research/v9/schema.json"
        ).read_text()
    )
    Draft202012Validator(schema).validate(document)
    store = ResearchStore(tmp_path / "research")
    assert store.list()["research"][0]["research_id"] == document["research_id"]
    explorer_html = root / "explorer.html"
    original_html = explorer_html.read_text(encoding="utf-8")
    explorer_html.write_text("obsolete projection", encoding="utf-8")
    isolated = store.list()
    assert isolated["research"] == []
    assert isolated["inventory_counts"]["corrupt"] == 1
    explorer_html.write_text(original_html, encoding="utf-8")
    assert (
        ResearchStore(tmp_path / "research").latest("a" * 64, "XNAS:MSFT")["research_id"]
        == document["research_id"]
    )
    with pytest.raises(LookupError, match="does not exist"):
        ResearchStore(tmp_path / "research").show("invalid")
    with pytest.raises(LookupError, match="does not exist"):
        ResearchStore(tmp_path / "empty").latest("a" * 64, "XNAS:MSFT")


def test_research_rejects_pre_contract_manifest_with_rebuild_guidance(tmp_path: Path) -> None:
    request = SecurityResearchRequest(
        "market-yfinance",
        INSTRUMENT,
        "MSFT",
        date(2026, 1, 1),
        date(2026, 8, 8),
        Adjustment.ADJUSTED,
        30,
        3,
        2.0,
        {},
        ("company",),
    )
    imported = ImportedSecurityResearch(
        request,
        "yfinance",
        "1.5.2",
        datetime(2026, 8, 8, tzinfo=UTC),
        (),
        (("name", "Microsoft"),),
        (),
        (),
        (),
        "d" * 64,
    )
    store = ResearchStore(tmp_path / "research")
    document = store.put(
        imported,
        _context(),
        minimum_price_observations=252,
        runtime_settings={},
        runtime_settings_hash="b" * 64,
        benchmarks=None,
    )
    manifest_path = Path(document["artifacts"]["manifest.json"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema"] = "security-research-manifest/v8"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="incompatible schema; rebuild"):
        store.show(document["research_id"])


def test_research_quality_preserves_independent_event_success(tmp_path: Path) -> None:
    request = SecurityResearchRequest(
        "market-yfinance",
        INSTRUMENT,
        "MSFT",
        date(2026, 1, 1),
        date(2026, 8, 8),
        Adjustment.ADJUSTED,
        30,
        3,
        2.0,
        {},
        ("events",),
    )
    imported = ImportedSecurityResearch(
        request,
        "yfinance",
        "1.5.2",
        datetime(2026, 8, 8, tzinfo=UTC),
        (),
        (),
        (),
        (
            ResearchEvent("dividend", date(2026, 5, 15), (("amount", "0.83"),)),
            ResearchEvent("split", date(2026, 6, 1), (("ratio", "2"),)),
        ),
        (EquityAcquisitionFailure(INSTRUMENT, "research", "earnings", "network_error"),),
        "e" * 64,
    )
    document = ResearchStore(tmp_path / "research").put(
        imported,
        _context(),
        minimum_price_observations=252,
        runtime_settings={},
        runtime_settings_hash="b" * 64,
        benchmarks=None,
    )

    assert document["quality_summary"]["evidence_statuses"] == {
        "price": "not_requested",
        "company": "not_requested",
        "annual_financials": "not_requested",
        "quarterly_financials": "not_requested",
        "earnings": "acquisition_failed",
        "dividends": "available",
        "splits": "available",
        "benchmarks": "not_requested",
    }


def test_benchmark_failure_does_not_mark_security_price_failed(tmp_path: Path) -> None:
    request = SecurityResearchRequest(
        "market-yfinance",
        INSTRUMENT,
        "MSFT",
        date(2026, 1, 1),
        date(2026, 8, 8),
        Adjustment.ADJUSTED,
        30,
        3,
        2.0,
        {},
        ("benchmarks", "price"),
    )
    imported = ImportedSecurityResearch(
        request,
        "yfinance",
        "1.5.2",
        datetime(2026, 8, 8, tzinfo=UTC),
        (),
        (),
        (),
        (),
        (),
        "f" * 64,
    )
    benchmark = SimpleNamespace(
        observations=(),
        failures=(EquityAcquisitionFailure(INSTRUMENT, "history", "price", "network_error"),),
    )
    document = ResearchStore(tmp_path / "research").put(
        imported,
        _context(),
        minimum_price_observations=252,
        runtime_settings={},
        runtime_settings_hash="b" * 64,
        benchmarks=benchmark,
    )

    assert document["quality_summary"]["evidence_statuses"]["price"] == "none_observed"
    assert document["quality_summary"]["evidence_statuses"]["benchmarks"] == "acquisition_failed"


class _Market:
    def show(self, snapshot_id: str) -> dict[str, object]:
        assert snapshot_id == "latest"
        return {"snapshot_id": "a" * 64}

    def row(self, snapshot_id: str, instrument_id: str) -> dict[str, object]:
        assert snapshot_id == "a" * 64
        if instrument_id == "XNAS:MISSING":
            raise LookupError("not present")
        return {
            "snapshot_id": "a" * 64,
            "provider_symbol": "MSFT",
            "memberships": ["sp500"],
            "instrument": {
                "symbol": "MSFT",
                "mic": "XNAS",
                "currency": "USD",
                "exchange_timezone": "America/New_York",
            },
        }

    def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, object]:
        del snapshot_id, instrument_id
        return _context()


class _ResearchFetcher:
    def fetch_research(
        self, request: SecurityResearchRequest, *, progress: Any = None
    ) -> ImportedSecurityResearch:
        if progress is not None:
            progress(
                AcquisitionProgress("research_company", AcquisitionProgressState.STARTED, 0, 1, 0)
            )
            progress(
                AcquisitionProgress("research_company", AcquisitionProgressState.COMPLETED, 1, 1, 0)
            )
        return ImportedSecurityResearch(
            request,
            "yfinance",
            "1.5.2",
            datetime(2026, 8, 8, tzinfo=UTC),
            (),
            (("name", "Microsoft"),),
            (),
            (),
            (),
            "e" * 64,
        )


class _Registry:
    def load_security_research_fetcher(self, name: str) -> _ResearchFetcher:
        assert name == "yfinance"
        return _ResearchFetcher()

    def load_equity_batch_fetcher(self, name: str) -> Any:
        raise AssertionError(name)


class _Repository:
    def put(
        self, imported: ImportedSecurityResearch, context: object, **values: object
    ) -> dict[str, object]:
        del context, values
        return {
            "research_id": "f" * 64,
            "instrument_id": (
                f"{imported.request.instrument.mic}:{imported.request.instrument.symbol}"
            ),
            "price_coverage_gate_passed": True,
        }

    def show(self, research_id: str) -> dict[str, object]:
        return {"research_id": research_id}

    def latest(self, snapshot_id: str, instrument_id: str) -> dict[str, object]:
        return {"snapshot_id": snapshot_id, "instrument_id": instrument_id}

    def list(self, **values: object) -> dict[str, object]:
        return {"schema": "security-research-list/v2", **values}


def test_research_service_preserves_partial_batch_success() -> None:
    service = ResearchService(
        _Registry(),
        _Market(),
        _Repository(),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    )

    result = service.build(
        ResearchBuildInputs("latest", ("XNAS:MSFT", "XNAS:MISSING"), ("company",), None)
    )

    assert result["requirements_met"] is True
    assert result["snapshot_id"] == "a" * 64
    assert [item["instrument_id"] for item in result["research"]] == ["XNAS:MSFT"]
    assert result["failures"] == [{"instrument_id": "XNAS:MISSING", "error": "not present"}]


def test_research_progress_sink_does_not_change_pack_identity(tmp_path: Path) -> None:
    class Market(_Market):
        def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, object]:
            del snapshot_id, instrument_id
            return {
                **_context(),
                "definitions": {
                    "schema": "market-snapshot-definitions/v1",
                    "fields": [],
                    "missing_reasons": [],
                },
            }

    inputs = ResearchBuildInputs("latest", ("XNAS:MSFT",), ("company",), None)
    plain = ResearchService(
        _Registry(),
        Market(),
        ResearchStore(tmp_path / "plain" / "research"),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    ).build(inputs)
    events: list[AcquisitionProgress] = []
    observed = ResearchService(
        _Registry(),
        Market(),
        ResearchStore(tmp_path / "observed" / "research"),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    ).build(inputs, progress=events.append)

    assert events
    assert observed["research"][0]["research_id"] == plain["research"][0]["research_id"]


class _BenchmarkRegistry(_Registry):
    def load_equity_batch_fetcher(self, name: str) -> Any:
        assert name == "yfinance"

        class Fetcher:
            def fetch(self, request: Any, *, progress: Any = None) -> ImportedEquityBatch:
                del progress
                retrieved_at = datetime(2026, 8, 8, tzinfo=UTC)
                return ImportedEquityBatch(
                    request,
                    "yfinance",
                    "1.5.2",
                    "benchmarks",
                    retrieved_at,
                    tuple(
                        EquityBatchObservation(item, retrieved_at, (), (), (), "d" * 64)
                        for item in request.instruments
                    ),
                    (),
                    "c" * 64,
                )

        return Fetcher()


def test_research_service_builds_benchmarks_and_read_views() -> None:
    service = ResearchService(
        _BenchmarkRegistry(),
        _Market(),
        _Repository(),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    )
    result = service.build(
        ResearchBuildInputs("latest", ("XNAS:MSFT",), ("benchmarks", "company", "price"), 365)
    )
    assert not result["failures"], result["failures"]
    assert result["requirements_met"] is True
    assert service.show("f" * 64)["research_id"] == "f" * 64
    assert (
        service.show("latest", snapshot_id="latest", instrument_id="XNAS:MSFT")["instrument_id"]
        == "XNAS:MSFT"
    )
    assert service.list(snapshot_id="a" * 64)["snapshot_id"] == "a" * 64
    with pytest.raises(ValueError, match="only valid"):
        service.show("f" * 64, snapshot_id="latest")
    with pytest.raises(ValueError, match="requires"):
        service.show("latest")
