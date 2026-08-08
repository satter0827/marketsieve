from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from marketsieve.data.daily import Adjustment
from marketsieve.domain import Instrument
from marketsieve.synthetic.daily import fixture_bars
from marketsieve_cli.adapters.config import Settings
from marketsieve_cli.adapters.research import ResearchStore
from marketsieve_cli.application.research import ResearchService
from marketsieve_cli.contracts import ResearchBuildInputs
from marketsieve_extension_api import (
    EquityBatchObservation,
    ImportedEquityBatch,
    ImportedSecurityResearch,
    ResearchEvent,
    ResearchFinancialFact,
    SecurityResearchRequest,
)

INSTRUMENT = Instrument.create(
    symbol="MSFT", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
)


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

    assert document["schema"] == "security-research/v4"
    assert document["price_requirements_met"] is True
    assert not list(root.glob("*.csv")) and not list(root.glob("*.xlsx"))
    html = (root / "explorer.html").read_text()
    assert "<svg" in html and "https://" not in html
    chart_payload = html.split('<script id="explorer-data" type="application/json">', 1)[1].split(
        "</script>", 1
    )[0]
    assert any(
        chart["chart_id"] == "price_sma_volume" for chart in json.loads(chart_payload)["charts"]
    )
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/security-research/v4/schema.json").read_text()
    )
    Draft202012Validator(schema).validate(document)
    assert (
        ResearchStore(tmp_path / "research").list()["research"][0]["research_id"]
        == document["research_id"]
    )
    assert (
        ResearchStore(tmp_path / "research").latest("a" * 64, "XNAS:MSFT")["research_id"]
        == document["research_id"]
    )
    with pytest.raises(LookupError, match="does not exist"):
        ResearchStore(tmp_path / "research").show("invalid")
    with pytest.raises(LookupError, match="does not exist"):
        ResearchStore(tmp_path / "empty").latest("a" * 64, "XNAS:MSFT")


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
        return {"snapshot_id": "a" * 64, "definitions": {}}


class _ResearchFetcher:
    def fetch_research(self, request: SecurityResearchRequest) -> ImportedSecurityResearch:
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
            "price_requirements_met": True,
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


class _BenchmarkRegistry(_Registry):
    def load_equity_batch_fetcher(self, name: str) -> Any:
        assert name == "yfinance"

        class Fetcher:
            def fetch(self, request: Any) -> ImportedEquityBatch:
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
