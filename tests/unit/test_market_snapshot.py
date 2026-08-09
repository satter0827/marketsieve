from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from marketsieve import __version__
from marketsieve.domain import Instrument
from marketsieve.matrix import MatrixRow, MatrixSecurity, build_matrix_row, field_definitions
from marketsieve.synthetic.daily import JP_INSTRUMENT, US_INSTRUMENT, fixture_bars
from marketsieve_cli.adapters import explorer_v2
from marketsieve_cli.adapters.config import Settings
from marketsieve_cli.adapters.explorer_v2 import build_snapshot_explorer_data
from marketsieve_cli.adapters.market_snapshots import MarketSnapshotStore, _request_fingerprint
from marketsieve_cli.application.market import (
    MarketService,
    _load_universe,
    _not_requested_fields,
    _provider_failure_fields,
    _summary,
)
from marketsieve_cli.contracts import MarketBuildInputs, RuntimeSettings
from marketsieve_extension_api import (
    EquityAcquisitionFailure,
    EquityBatchObservation,
    EquityBatchRequest,
    ImportedEquityBatch,
    ImportedMarketIndicators,
    MarketIndicatorObservation,
    SourceDiagnostic,
)


def test_snapshot_explorer_rejects_incomplete_field_catalog() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        build_snapshot_explorer_data({}, ())


def test_snapshot_explorer_rejects_view_field_missing_from_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fields = [{"name": definition.name} for definition in field_definitions()]
    original = explorer_v2._view

    def invalid_view(*args: Any, **kwargs: Any) -> dict[str, Any]:
        view = original(*args, **kwargs)
        view["fields"] = ["unknown_view_field"]
        return view

    monkeypatch.setattr(explorer_v2, "_view", invalid_view)
    with pytest.raises(ValueError, match=r"view .* contains unknown fields"):
        build_snapshot_explorer_data(
            {
                "snapshot_id": "snapshot",
                "created_at": "2026-08-08T00:00:00Z",
                "source": "fixture",
            },
            fields,
        )


def _row(instrument: Instrument, memberships: tuple[str, ...], offset: int) -> MatrixRow:
    bars = fixture_bars(
        instrument,
        tuple(str(100 + offset + index) for index in range(253)),
        dataset=f"fixture-{instrument.symbol}",
    )
    profile = tuple(
        sorted(
            {
                "name": instrument.symbol,
                "country": "Japan" if instrument.mic == "XTKS" else "United States",
                "currency": instrument.currency,
                "exchange": instrument.mic,
                "sector": "Technology",
                "industry": "Software",
            }.items()
        )
    )
    security = MatrixSecurity(
        instrument,
        f"{instrument.symbol}.T" if instrument.mic == "XTKS" else instrument.symbol,
        memberships,
        datetime(2026, 8, 8, tzinfo=UTC),
        bars,
        profile,
        (),
        "a" * 64,
    )
    return build_matrix_row(security, {})


def _store(tmp_path: Path, offset: int = 0) -> tuple[MarketSnapshotStore, dict[str, Any]]:
    store = MarketSnapshotStore(tmp_path / "market-snapshots")
    rows = (
        _row(JP_INSTRUMENT, ("nikkei225", "topix500"), offset),
        _row(US_INSTRUMENT, ("sp500", "nasdaq100"), offset),
    )
    indices = ("nasdaq100", "nikkei225", "sp500", "topix500")
    summary = _summary(
        rows,
        indices,
        RuntimeSettings(),
        datetime(2026, 8, 8, tzinfo=UTC),
        price_requested=True,
    )
    request = {"schema": "market-snapshot-request/v2", "offset": offset}
    fingerprint = _request_fingerprint(request)
    run_id = store.begin_run(fingerprint, request, resume=None)
    failures = tuple(
        {
            "instrument_id": f"{row.security.instrument.mic}:{row.security.instrument.symbol}",
            "stage": "calculation",
            "field": field,
            "reason": reason,
        }
        for row in rows
        for field, reason in row.missing
        if reason != "not_applicable"
    )
    document = store.put(
        run_id=run_id,
        manifest_body={
            "created_at": "2026-08-08T00:00:00+00:00",
            "request": {"fingerprint": fingerprint, **request},
            "source": {
                "name": "yfinance",
                "version": "1.5.2",
                "dataset": "fixture",
                "response_hash": "b" * 64,
            },
            "input_snapshot_id": "b" * 64,
            "universe_assets": {},
            "inputs": {"indices": list(indices), "evidence": ["price"], "history_days": 1095},
            "runtime_settings": {},
            "runtime_settings_hash": "c" * 64,
            "request_fingerprint": fingerprint,
            "row_count": len(rows),
            "field_count": len(field_definitions()),
            "failure_count": len(failures),
            "coverage": summary["coverage"],
            "price_coverage_gate_passed": summary["price_requirements_met"],
        },
        fields=field_definitions(),
        rows=rows,
        summary=summary,
        failures=failures,
        market_indicators=(
            {
                "schema": "market-indicator/v2",
                "indicator_id": "usd_jpy",
                "provider_symbol": "JPY=X",
                "name": "USD/JPY",
                "kind": "fx_rate",
                "unit": "JPY_per_USD",
                "retrieved_at": "2026-08-08T00:00:00+00:00",
                "observations": [{"date": "2026-08-08", "value": "150"}],
                "missing_reason": None,
                "not_applicable": ["volume_metrics"],
            },
        ),
    )
    return store, document


def test_snapshot_is_self_contained_without_spreadsheets(tmp_path: Path) -> None:
    store, document = _store(tmp_path)
    root = Path(document["artifacts"]["manifest.json"]).parent

    assert document["schema"] == "market-snapshot/v8"
    assert set(path.name for path in root.iterdir()) == set(document["artifacts"])
    assert (root / "aggregates.jsonl").is_file()
    assert not list(root.glob("*.csv"))
    assert not list(root.glob("*.xlsx"))
    assert "http://" not in (root / "explorer.html").read_text()
    assert "https://" not in (root / "explorer.html").read_text()
    assert "securities.jsonl" not in (root / "explorer.html").read_text()
    assert "fetch('explorer-data.json'" in (root / "explorer.html").read_text()
    html = (root / "explorer.html").read_text()
    assert "sectors.indexOf(d.y)" in html
    assert "Math.floor(i/2)" not in html
    assert 'return`<span class="meta"' not in html
    assert "coverageValue(D.quality.price_coverage)" in html
    assert "価格取得率 [object Object]" not in html
    assert "横軸 ${esc(fieldLabel(xf))}" in html
    assert "unitLabel(v.unit)" in html
    assert "periodLabel(v.period)" in html
    assert "denominator:present.length" in html
    assert "未取得の市場指標" in html
    assert "indicator.missing_reason" in html
    explorer_data = json.loads((root / "explorer-data.json").read_text())
    assert explorer_data["schema"] == "explorer-data/v4"
    assert "securities" not in explorer_data
    assert {view["section"] for view in explorer_data["views"]} >= {
        "overview",
        "risk",
        "fundamentals",
        "quality",
    }
    assert all(
        "data" not in view and "fallback_table" not in view for view in explorer_data["views"]
    )
    assert len((root / "explorer-data.json").read_bytes()) < 100_000
    assert len((root / "explorer.html").read_bytes()) < 100_000
    explorer_schema = json.loads(
        (Path(__file__).parents[2] / "schemas/explorer-data/v4/schema.json").read_text()
    )
    Draft202012Validator(explorer_schema).validate(explorer_data)
    quality = json.loads((root / "quality-summary.json").read_text())
    assert quality["schema"] == "market-snapshot-quality-summary/v4"
    assert quality["failures"]["record_count"] == document["failure_count"]
    assert quality["freshness"]["price_age_days"]["observation_count"] == 2
    definitions = json.loads((root / "definitions.json").read_text())
    units = {field["name"]: field["unit"] for field in definitions["fields"]}
    assert units["position_52w"] == "bounded_ratio"
    assert units["trailing_pe"] == "multiple"
    assert store.list()["schema"] == "market-snapshot-list/v3"
    assert (
        store.query(
            "latest",
            filters={"market": ("us",)},
            minimums={},
            maximums={},
            present=("close",),
            missing=(),
            fields=("close",),
        )["matched_count"]
        == 1
    )
    comparison = store.compare("latest", ("XNAS:MSFT",), ("close", "return_20d"))
    assert comparison["schema"] == "market-snapshot-comparison/v3"
    assert comparison["rows"][0]["instrument_id"] == "XNAS:MSFT"
    context = store.research_context("latest", "XNAS:MSFT")
    assert context["market"]["markets"].keys() == {"us"}
    assert all(
        segment["segment_type"] in {"index", "sector", "industry", "market-sector"}
        for segment in context["segments"]
    )
    with pytest.raises(LookupError, match="not present"):
        store.row("latest", "XNAS:MISSING")
    with pytest.raises(ValueError, match="one market and currency"):
        store.compare("latest", ("XNAS:MSFT", "XTKS:7203"), ("market_cap",))
    with pytest.raises(ValueError, match="unique"):
        store.compare("latest", ("XNAS:MSFT",), ("close", "close"))
    with pytest.raises(ValueError, match="unknown"):
        store.compare("latest", ("XNAS:MSFT",), ("unknown",))
    with pytest.raises(LookupError, match="not present"):
        store.compare("latest", ("XNAS:MISSING",), ("close",))


def test_snapshot_query_supports_profile_order_limit_and_transient_budget(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)

    result = store.query(
        "latest",
        filters={},
        minimums={},
        maximums={},
        present=("close",),
        missing=(),
        fields=(),
        order=("return_20d:desc",),
        limit=1,
        domains=("return", "risk"),
        profile="swing",
        budget=Decimal("50000"),
        budget_currency="JPY",
        trading_unit=100,
    )

    assert result["schema"] == "market-snapshot-query-result/v3"
    assert result["total_matched_count"] == 2
    assert result["matched_count"] == 1
    assert all("252d" not in field for field in result["fields"])
    assert result["rows"][0]["purchase_projection"]["trading_unit"] == 100
    assert result["input_count"] == 2
    assert result["filter_funnel"][0]["condition"] == "input"

    converted = store.query(
        "latest",
        filters={"market": ("us",)},
        minimums={},
        maximums={},
        present=("close",),
        missing=(),
        fields=("close",),
        budget=Decimal("50000"),
        budget_currency="JPY",
        trading_unit=1,
        use_snapshot_fx=True,
    )
    projection = converted["rows"][0]["purchase_projection"]
    assert projection["fx"]["value"] == "150"
    assert projection["reason"] is None


def test_snapshot_query_rejects_invalid_order_domain_and_limit(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    common: dict[str, Any] = dict(
        snapshot_id="latest",
        filters={},
        minimums={},
        maximums={},
        present=(),
        missing=(),
        fields=("close",),
    )
    with pytest.raises(ValueError, match="FIELD:asc"):
        store.query(**common, order=("close",))
    with pytest.raises(ValueError, match="domains"):
        store.query(**common, domains=("unknown",))
    with pytest.raises(ValueError, match="positive"):
        store.query(**common, limit=0)


def test_financial_issuer_metrics_are_not_applicable() -> None:
    bars = fixture_bars(
        US_INSTRUMENT,
        tuple(str(100 + index) for index in range(253)),
        dataset="financial-issuer",
    )
    security = MatrixSecurity(
        US_INSTRUMENT,
        "MSFT",
        ("sp500",),
        datetime(2026, 8, 8, tzinfo=UTC),
        bars,
        tuple(sorted({"sector": "Financial Services", "quote_type": "EQUITY"}.items())),
        (("debt_to_equity", "1.2"), ("enterprise_to_ebitda", "8")),
        "d" * 64,
    )

    row = build_matrix_row(security, {})
    definitions = {value.name: value for value in field_definitions()}

    assert dict(row.missing)["debt_to_equity"] == "not_applicable"
    assert dict(row.missing)["enterprise_to_ebitda"] == "not_applicable"
    assert definitions["debt_to_equity"].applicable_to == "non_financial_non_reit_equities"
    assert "financial_or_insurance_issuer" in definitions["debt_to_equity"].exclusion_conditions


def test_historical_reconstruction_is_price_only_and_deduplicated(tmp_path: Path) -> None:
    service = MarketService(
        _Registry(),
        MarketSnapshotStore(tmp_path / "market-snapshots"),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    )
    inputs = MarketBuildInputs(
        ("dow30",),
        ("benchmarks", "price"),
        365,
        as_of=date(2026, 7, 1),
        mode="historical_price_reconstruction",
        session="close",
    )

    first = service.build(inputs)
    duplicate = service.build(inputs)

    assert first["inputs"]["mode"] == "historical_price_reconstruction"
    assert first["run"]["status"] == "completed"
    assert duplicate["snapshot_id"] == first["snapshot_id"]
    assert duplicate["run"]["status"] == "duplicate"


def test_overlapping_market_build_merges_benchmark_and_indicator(tmp_path: Path) -> None:
    registry = _Registry()
    service = MarketService(
        registry,
        MarketSnapshotStore(tmp_path / "market-snapshots"),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    )

    document = service.build(
        MarketBuildInputs(
            ("nasdaq100", "sp500"),
            ("benchmarks", "price"),
            365,
        )
    )

    expected_universe, _ = _load_universe(("nasdaq100", "sp500"))
    assert document["row_count"] == len(expected_universe)
    request = registry.fetcher.request
    assert request is not None
    identities = tuple(
        (item.instrument.mic, item.instrument.symbol) for item in request.instruments
    )
    assert identities == tuple(sorted(set(identities)))
    ndx = next(
        item
        for item in request.instruments
        if (item.instrument.mic, item.instrument.symbol) == ("XNAS", "NDX")
    )
    assert ndx.memberships == ("nasdaq100",)


def test_complete_builtin_universe_is_unique_and_stable() -> None:
    universe, assets = _load_universe(("dow30", "nasdaq100", "nikkei225", "sp500", "topix500"))

    identities = [(seed.instrument.mic, seed.instrument.symbol) for seed in universe]
    assert len(universe) == 1021
    assert identities == sorted(set(identities))
    assert set(assets) == {"dow30", "nasdaq100", "nikkei225", "sp500", "topix500"}
    assert all(
        len(asset["asset_hash"]) == 64 and len(asset["source_hash"]) == 64
        for asset in assets.values()
    )


def test_historical_reconstruction_rejects_future_and_pre_universe_dates(tmp_path: Path) -> None:
    service = MarketService(
        _Registry(),
        MarketSnapshotStore(tmp_path / "market-snapshots"),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    )

    with pytest.raises(ValueError, match="future"):
        service.build(
            MarketBuildInputs(
                ("dow30",),
                ("benchmarks", "price"),
                365,
                as_of=date(2026, 8, 9),
                mode="historical_price_reconstruction",
            )
        )
    with pytest.raises(ValueError, match="universe asset basis"):
        service.build(
            MarketBuildInputs(
                ("dow30",),
                ("benchmarks", "price"),
                365,
                as_of=date(2026, 6, 30),
                mode="historical_price_reconstruction",
            )
        )


def test_snapshot_diff_is_deterministic_and_definition_safe(tmp_path: Path) -> None:
    store, left = _store(tmp_path / "left", 0)
    _, right_other = _store(tmp_path / "right", 5)
    right_source = Path(right_other["artifacts"]["manifest.json"]).parent
    right_target = store.objects / right_other["snapshot_id"]
    right_target.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(right_source, right_target)

    result = store.diff(left["snapshot_id"], right_other["snapshot_id"], ("close",))

    assert result["schema"] == "market-snapshot-diff/v1"
    assert [item["instrument_id"] for item in result["changed_securities"]] == [
        "XNAS:MSFT",
        "XTKS:7203",
    ]
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/market-snapshot-diff/v1/schema.json").read_text()
    )
    Draft202012Validator(schema).validate(result)


class _BatchFetcher:
    def __init__(self) -> None:
        self.request: EquityBatchRequest | None = None

    def doctor(self) -> SourceDiagnostic:
        return SourceDiagnostic(True, "ready", "ready")

    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch:
        self.request = request
        retrieved_at = datetime(2026, 8, 8, tzinfo=UTC)
        observations = tuple(
            EquityBatchObservation(item, retrieved_at, (), (), (), "d" * 64)
            for item in request.instruments
        )
        return ImportedEquityBatch(
            request,
            "yfinance",
            "1.5.2",
            "equity-company",
            retrieved_at,
            observations,
            (),
            "e" * 64,
        )


class _Registry:
    def __init__(self) -> None:
        self.fetcher = _BatchFetcher()

    def load_equity_batch_fetcher(self, name: str) -> _BatchFetcher:
        assert name == "yfinance"
        return self.fetcher

    def load_market_indicator_fetcher(self, name: str) -> Any:
        assert name == "yfinance"

        class Fetcher:
            def fetch_market_indicators(self, request: Any) -> ImportedMarketIndicators:
                retrieved_at = datetime(2026, 8, 8, tzinfo=UTC)
                return ImportedMarketIndicators(
                    request,
                    "yfinance",
                    "1.5.2",
                    retrieved_at,
                    tuple(
                        MarketIndicatorObservation(item, retrieved_at, (), "f" * 64)
                        for item in request.indicators
                    ),
                    (),
                    "1" * 64,
                )

        return Fetcher()


def test_market_service_builds_explicit_company_only_scope(tmp_path: Path) -> None:
    service = MarketService(
        _Registry(),
        MarketSnapshotStore(tmp_path / "market-snapshots"),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    )

    document = service.build(MarketBuildInputs(("dow30",), ("company",), None))

    assert document["inputs"] == {
        "indices": ["dow30"],
        "evidence": ["company"],
        "history_days": None,
        "as_of": None,
        "mode": "current",
        "session": None,
    }
    assert document["request"]["producer"] == {
        "name": "marketsieve-cli",
        "version": __version__,
        "snapshot_schema": "market-snapshot/v8",
        "explorer_schema": "explorer-data/v4",
    }
    assert document["row_count"] == 30
    assert document["price_coverage_gate_passed"] is True
    row = service.row(document["snapshot_id"], "XNAS:AAPL")
    assert row["missing"]["close"] == "not_requested"
    assert row["missing"]["trailing_pe"] == "not_requested"
    failures = [
        json.loads(line)
        for line in Path(document["artifacts"]["failures.jsonl"]).read_text().splitlines()
    ]
    assert not any(failure["field"] == "close" for failure in failures)
    quality = json.loads(Path(document["artifacts"]["quality-summary.json"]).read_text())
    assert quality["failures"]["affected_security_count"] == 0
    assert quality["failures"]["complete_failure_security_count"] == 0
    assert service.show("latest")["snapshot_id"] == document["snapshot_id"]
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/market-snapshot/v8/schema.json").read_text()
    )
    Draft202012Validator(schema).validate(document)


def test_market_service_requires_exactly_one_new_or_resumed_request(tmp_path: Path) -> None:
    service = MarketService(
        _Registry(),
        MarketSnapshotStore(tmp_path / "market-snapshots"),
        Settings(None),
        today=lambda: date(2026, 8, 8),
    )
    with pytest.raises(ValueError, match="inputs are required"):
        service.build(None)
    with pytest.raises(ValueError, match="cannot be combined"):
        service.build(MarketBuildInputs(("dow30",), ("company",), None), resume="run")


def test_financial_only_scope_preserves_required_currency_field() -> None:
    missing = dict(_not_requested_fields(("financials",)))

    assert "financial_currency" not in missing
    assert missing["currency"] == "not_requested"


@pytest.mark.parametrize(
    ("stage", "field", "expected"),
    (
        ("price", "close", "return_20d"),
        ("profile", "company_profile", "sector"),
        ("financials", "company_financials", "trailing_pe"),
        ("financials", "annual_income", "revenue_cagr_3y"),
        ("financials", "balance_sheet", "total_assets"),
        ("financials", "quarterly_cash_flow", "free_cash_flow_ttm"),
        ("volume", "volume_20d", "average_volume_20d"),
    ),
)
def test_provider_failures_map_to_their_complete_field_domain(
    stage: str, field: str, expected: str
) -> None:
    failure = EquityAcquisitionFailure(US_INSTRUMENT, stage, field, "field_absent")
    assert expected in _provider_failure_fields(failure)
