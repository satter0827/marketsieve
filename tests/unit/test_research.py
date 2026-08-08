from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from marketsieve.data.daily import Adjustment
from marketsieve.domain import Instrument
from marketsieve.synthetic.daily import fixture_bars
from marketsieve_cli.adapters.research import ResearchStore
from marketsieve_cli.application.research import ResearchService
from marketsieve_cli.contracts import ResearchConfiguration
from marketsieve_extension_api import (
    ImportedSecurityResearch,
    ResearchEvent,
    ResearchFinancialFact,
    SecurityResearchRequest,
)

INSTRUMENT = Instrument.create(
    symbol="MSFT",
    mic="XNAS",
    currency="USD",
    exchange_timezone="America/New_York",
)
SNAPSHOT_ID = "a" * 64


def _request() -> SecurityResearchRequest:
    return SecurityResearchRequest(
        "market-yfinance",
        INSTRUMENT,
        "MSFT",
        date(2016, 8, 10),
        date(2026, 8, 8),
        Adjustment.ADJUSTED,
        30,
        3,
        2.0,
        {"cache_dir": ".marketsieve/cache/yfinance"},
    )


def _imported(request: SecurityResearchRequest | None = None) -> ImportedSecurityResearch:
    selected = request or _request()
    bars = tuple(
        replace(
            bar,
            trading_date=bar.trading_date - timedelta(days=365),
            available_at=bar.available_at - timedelta(days=365),
            adjustment=Adjustment.ADJUSTED,
        )
        for bar in fixture_bars(
            INSTRUMENT,
            tuple(str(100 + index) for index in range(253)),
            dataset="research-fixture",
        )
    )
    return ImportedSecurityResearch(
        selected,
        "yfinance",
        "1.5.2",
        datetime(2026, 8, 8, tzinfo=UTC),
        bars,
        (("name", "Microsoft"), ("sector", "Technology")),
        (
            ResearchFinancialFact(
                "revenue",
                "income",
                "annual",
                date(2025, 6, 30),
                "USD",
                Decimal("281724000000"),
            ),
        ),
        (ResearchEvent("dividend", date(2026, 5, 15), (("amount", "0.83"),)),),
        (),
        "b" * 64,
    )


def _context() -> dict[str, Any]:
    return {
        "schema": "market-research-context/v1",
        "snapshot_id": SNAPSHOT_ID,
        "security": {
            "instrument_id": "XNAS:MSFT",
            "memberships": ["sp500", "nasdaq100"],
            "values": {"sector": "Technology", "industry": "Software"},
        },
        "market": {"schema": "market-snapshot-market/v1"},
        "segments": [{"segment_type": "sector", "segment_value": "Technology"}],
        "definitions": {
            "schema": "market-snapshot-definitions/v1",
            "fields": [{"name": "sector", "data_type": "string"}],
            "missing_reasons": [],
        },
    }


def test_research_store_creates_verified_self_contained_history(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "research")

    document = store.put(_imported(), _context(), minimum_price_observations=252)

    research_id = document["research_id"]
    path = tmp_path / "research" / "objects" / research_id
    assert document["price_requirements_met"] is True
    assert set(document["artifacts"]) == {
        "README.md",
        "manifest.json",
        "definitions.json",
        "company.json",
        "market-context.json",
        "prices.jsonl",
        "financials.jsonl",
        "events.jsonl",
        "failures.jsonl",
        "quality.json",
        "summary.md",
        "explorer.html",
    }
    assert all(Path(value).parent == path for value in document["artifacts"].values())
    assert store.latest(SNAPSHOT_ID, "XNAS:MSFT")["research_id"] == research_id
    assert store.list(snapshot_id=SNAPSHOT_ID, instrument_id="XNAS:MSFT")["research"]
    schema_root = Path(__file__).parents[2] / "schemas"
    for name, value in (
        ("security-research", document),
        ("security-research-manifest", json.loads((path / "manifest.json").read_text())),
        ("security-research-list", store.list()),
    ):
        schema = json.loads((schema_root / name / "v1" / "schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    assert not list(path.glob("*.xlsx"))
    definitions = json.loads((path / "definitions.json").read_text())
    assert {value["name"] for value in definitions["company_fields"]} >= {
        "name",
        "financial_currency",
        "market_cap",
    }
    assert {value["name"] for value in definitions["price_fields"]} == {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjustment",
    }
    assert {value["concept"] for value in definitions["financial_concepts"]} >= {
        "revenue",
        "total_assets",
        "free_cash_flow",
    }
    assert definitions["market_context"]["snapshot_definitions"] == _context()["definitions"]
    numeric_definitions = {value["name"]: value for value in definitions["company_fields"]}
    assert numeric_definitions["debt_to_equity"]["unit"] == "ratio"
    assert "percentage points normalized" in numeric_definitions["debt_to_equity"]["definition"]


def test_research_store_rejects_tampered_projection(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "research")
    document = store.put(_imported(), _context(), minimum_price_observations=252)
    explorer = Path(document["artifacts"]["explorer.html"])
    explorer.write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="HTML projection"):
        store.show(document["research_id"])


def test_research_store_rejects_an_unlisted_file(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "research")
    document = store.put(_imported(), _context(), minimum_price_observations=252)
    path = Path(document["artifacts"]["manifest.json"]).parent
    (path / "analysis.md").write_text("external interpretation\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inventory"):
        store.show(document["research_id"])


def test_research_store_marks_zero_filled_volume_as_missing(tmp_path: Path) -> None:
    imported = _imported()
    bars = (*imported.bars[:-1], replace(imported.bars[-1], volume=0))
    store = ResearchStore(tmp_path / "research")

    document = store.put(replace(imported, bars=bars), _context(), minimum_price_observations=252)
    prices = [
        json.loads(line)
        for line in Path(document["artifacts"]["prices.jsonl"]).read_text().splitlines()
    ]

    assert prices[-1]["volume"] is None
    assert prices[-1]["missing"] == {"volume": "field_absent"}
    assert prices[-2]["missing"] == {}


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"start": datetime(2025, 1, 1, tzinfo=UTC)}, TypeError),
        ({"instrument": object()}, TypeError),
        ({"settings": {"timeout": 30}}, TypeError),
    ),
)
def test_security_research_request_rejects_values_the_fetcher_cannot_accept(
    changes: dict[str, Any], error: type[Exception]
) -> None:
    with pytest.raises(error):
        replace(_request(), **changes)


class _Market:
    def row(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        assert snapshot_id == "latest" and instrument_id == "XNAS:MSFT"
        return {
            "snapshot_id": SNAPSHOT_ID,
            "instrument": {
                "symbol": "MSFT",
                "mic": "XNAS",
                "currency": "USD",
                "exchange_timezone": "America/New_York",
            },
            "provider_symbol": "MSFT",
        }

    def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        assert snapshot_id in {"latest", SNAPSHOT_ID} and instrument_id == "XNAS:MSFT"
        return _context()


class _Fetcher:
    def __init__(self) -> None:
        self.request: SecurityResearchRequest | None = None

    def fetch_research(self, request: SecurityResearchRequest) -> ImportedSecurityResearch:
        self.request = request
        return _imported(request)


class _Registry:
    def __init__(self, fetcher: _Fetcher) -> None:
        self.fetcher = fetcher

    def load_equity_batch_fetcher(self, name: str) -> object:
        assert name == "yfinance"
        return self.fetcher


class _Configuration:
    def research_configuration(self) -> ResearchConfiguration:
        return ResearchConfiguration(3653, 252, 30, 3, 2.0)


def test_research_service_resolves_only_a_saved_snapshot_security(tmp_path: Path) -> None:
    fetcher = _Fetcher()
    service = ResearchService(
        _Registry(fetcher),
        _Market(),
        ResearchStore(tmp_path / "research"),
        _Configuration(),
        today=lambda: date(2026, 8, 8),
    )

    document = service.build("latest", "XNAS:MSFT")

    assert document["snapshot_id"] == SNAPSHOT_ID
    assert fetcher.request is not None
    assert fetcher.request.start == date(2016, 8, 7)
    assert (
        service.show("latest", instrument_id="XNAS:MSFT")["research_id"] == document["research_id"]
    )


def test_research_service_pins_latest_before_loading_context(tmp_path: Path) -> None:
    calls: list[str] = []

    class ChangingMarket(_Market):
        def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
            calls.append(snapshot_id)
            assert instrument_id == "XNAS:MSFT"
            assert snapshot_id == SNAPSHOT_ID
            return _context()

    service = ResearchService(
        _Registry(_Fetcher()),
        ChangingMarket(),
        ResearchStore(tmp_path / "research"),
        _Configuration(),
        today=lambda: date(2026, 8, 8),
    )

    document = service.build("latest", "XNAS:MSFT")

    assert document["snapshot_id"] == SNAPSHOT_ID
    assert calls == [SNAPSHOT_ID]


def test_research_service_reads_exact_snapshot_pack_without_market_store(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "research")
    document = store.put(_imported(), _context(), minimum_price_observations=252)

    class UnavailableMarket(_Market):
        def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
            raise AssertionError("an exact research lookup must not read the source Snapshot")

    service = ResearchService(_Registry(_Fetcher()), UnavailableMarket(), store, _Configuration())

    shown = service.show("latest", snapshot_id=SNAPSHOT_ID, instrument_id="XNAS:MSFT")

    assert shown["research_id"] == document["research_id"]


def test_research_explorer_escapes_financial_currency(tmp_path: Path) -> None:
    imported = _imported()
    unsafe = replace(imported.financials[0], currency="</td><script>alert(1)</script>")
    imported = replace(imported, financials=(unsafe,))
    store = ResearchStore(tmp_path / "research")

    document = store.put(imported, _context(), minimum_price_observations=252)
    rendered = Path(document["artifacts"]["explorer.html"]).read_text(encoding="utf-8")

    assert "</td><script>" not in rendered
    assert "&lt;/td&gt;&lt;script&gt;" in rendered
