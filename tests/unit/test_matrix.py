from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, getcontext, setcontext
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument
from marketsieve.matrix import (
    MatrixRow,
    MatrixSecurity,
    build_matrix_row,
    field_definitions,
)
from marketsieve.synthetic.daily import JP_INSTRUMENT, US_INSTRUMENT, fixture_bars
from marketsieve_cli.adapters.market_snapshots import (
    MarketSnapshotStore,
    _json_bytes,
    _row_document,
)
from marketsieve_cli.application.market import (
    MarketService,
    _configuration_document,
    _load_universe,
    _median,
    _percentile,
    _provider_failure_fields,
    _summary,
)
from marketsieve_cli.contracts import MarketConfiguration
from marketsieve_extension_api import (
    EquityAcquisitionFailure,
    EquityBatchFetcher,
    EquityBatchObservation,
    EquityBatchRequest,
    ImportedEquityBatch,
    SourceDiagnostic,
)


def _bars(instrument: Instrument, count: int = 253, *, offset: int = 0) -> tuple[DailyBar, ...]:
    closes = tuple(str(100 + offset + index) for index in range(count))
    return fixture_bars(instrument, closes, dataset=f"matrix-{instrument.symbol}-{count}")


def _security(
    instrument: Instrument = US_INSTRUMENT,
    *,
    memberships: tuple[str, ...] = ("sp500",),
    count: int = 253,
) -> MatrixSecurity:
    is_japanese = instrument.mic == "XTKS"
    profile = tuple(
        sorted(
            {
                "country": "Japan" if is_japanese else "United States",
                "currency": "JPY" if is_japanese else "USD",
                "financial_currency": "JPY" if is_japanese else "USD",
                "exchange": "JPX" if is_japanese else "NMS",
                "industry": "Automobiles" if is_japanese else "Software",
                "market_cap": "1000000",
                "name": "Fixture Corp",
                "quote_type": "EQUITY",
                "sector": "Industrials" if is_japanese else "Technology",
                "shares_outstanding": "10000",
            }.items()
        )
    )
    financials = tuple(
        sorted(
            {
                "free_cash_flow_ttm": "20",
                "operating_margin": "0.2",
                "price_to_book": "2",
                "return_on_equity": "0.1",
                "revenue_growth": "0.08",
                "revenue_ttm": "100",
                "total_assets": "200",
                "total_equity": "80",
                "trailing_pe": "10",
            }.items()
        )
    )
    bars = _bars(instrument, count)
    return MatrixSecurity(
        instrument,
        "MSFT" if instrument.mic != "XTKS" else "7203.T",
        memberships,
        datetime(2026, 8, 7, tzinfo=UTC),
        bars,
        profile,
        financials,
        "a" * 64,
    )


def _configuration(indices: tuple[str, ...] = ("sp500",)) -> MarketConfiguration:
    return MarketConfiguration(
        indices,
        1095,
        50,
        2,
        30,
        3,
        0.0,
        Decimal("0.95"),
        Decimal("0.90"),
    )


def _request_fingerprint(document: Mapping[str, object]) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def test_configuration_document_canonicalizes_equivalent_decimal_ratios() -> None:
    trailing_zero = _configuration()
    canonical = replace(
        trailing_zero,
        minimum_overall_price_coverage=Decimal("0.950"),
        minimum_index_price_coverage=Decimal("0.9"),
    )

    assert _configuration_document(trailing_zero) == _configuration_document(canonical)
    assert _configuration_document(trailing_zero)["minimum_index_price_coverage"] == "0.9"


def test_field_catalog_and_full_row_cover_all_cells_without_imputation() -> None:
    fields = field_definitions()
    security = _security()
    benchmark = _bars(
        Instrument.create(
            symbol="GSPC",
            mic="XNYS",
            currency="USD",
            exchange_timezone="America/New_York",
        )
    )

    row = build_matrix_row(security, {"sp500": benchmark})
    values = dict(row.values)
    missing = dict(row.missing)

    assert len(fields) >= 100
    assert len({field.name for field in fields}) == len(fields)
    assert {field.name for field in fields} == set(values) | set(missing)
    assert not (set(values) & set(missing))
    assert values["relative_return_sp500_252d"] == "0"
    assert values["beta_sp500_252d"] == "1"
    assert values["free_cash_flow_margin"] == "0.2"
    assert values["equity_ratio"] == "0.4"
    assert values["earnings_yield"] == "0.1"
    assert missing["relative_return_dow30_20d"] == "not_applicable"
    assert next(field for field in fields if field.name == "return_20d").formula is not None
    calculated = tuple(field for field in fields if field.source == "marketsieve")
    assert all(field.formula is not None for field in calculated)
    assert all(field.period is not None for field in calculated)
    assert "latest_four_compatible_quarterly_values" in str(
        next(field for field in fields if field.name == "revenue_ttm").formula
    )
    assert "three_year_prior_positive_value" in str(
        next(field for field in fields if field.name == "revenue_cagr_3y").formula
    )
    assert (
        next(field for field in fields if field.name == "revenue_ttm").unit == "financial_currency"
    )
    assert next(field for field in fields if field.name == "dividend_yield").unit == "ratio"


def test_matrix_rejects_cross_currency_financial_yield_without_conversion() -> None:
    security = _security()
    profile = dict(security.profile)
    profile["financial_currency"] = "EUR"

    row = build_matrix_row(replace(security, profile=tuple(sorted(profile.items()))), {})

    assert dict(row.missing)["free_cash_flow_yield"] == "currency_mismatch"
    assert "free_cash_flow_yield" not in dict(row.values)


def test_matrix_failure_override_removes_an_observed_value() -> None:
    security = replace(_security(), missing=(("close", "stale_history"),))

    row = build_matrix_row(security, {})

    assert "close" not in dict(row.values)
    assert dict(row.missing)["close"] == "stale_history"


def test_matrix_boundaries_preserve_missing_reasons_and_zero_denominators() -> None:
    security = _security(count=20)
    row = build_matrix_row(security, {})
    missing = dict(row.missing)

    assert missing["return_20d"] == "insufficient_history"
    assert missing["high_52w"] == "insufficient_history"
    assert missing["position_52w"] == "insufficient_history"
    assert missing["beta_sp500_252d"] == "benchmark_unavailable"

    empty = MatrixSecurity(
        security.instrument,
        security.provider_symbol,
        security.memberships,
        security.retrieved_at,
        (),
        (),
        (),
        "b" * 64,
    )
    empty_row = build_matrix_row(empty, {})
    assert dict(empty_row.missing)["close"] == "history_empty"
    row_schema = json.loads(
        (Path(__file__).parents[2] / "schemas/market-snapshot-security/v1/schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(row_schema, format_checker=FormatChecker()).validate(
        _row_document(empty_row)
    )
    with pytest.raises(ValueError, match="cover every field"):
        MatrixRow(security, (), ())

    profile_failure = EquityAcquisitionFailure(
        security.instrument, "profile", "company", "rate_limited"
    )
    assert {
        "previous_close",
        "high_52w",
        "low_52w",
    }.isdisjoint(_provider_failure_fields(profile_failure))


def test_matrix_distinguishes_observed_zero_denominators_from_missing_inputs() -> None:
    security = _security()
    constant_bars = tuple(
        replace(
            bar,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
        )
        for bar in fixture_bars(
            security.instrument,
            tuple("100" for _ in range(253)),
            dataset="constant-security",
        )
    )
    benchmark_instrument = Instrument.create(
        symbol="GSPC",
        mic="XNYS",
        currency="USD",
        exchange_timezone="America/New_York",
    )
    constant_benchmark = fixture_bars(
        benchmark_instrument,
        tuple("100" for _ in range(253)),
        dataset="constant-benchmark",
    )

    constant_row = build_matrix_row(
        replace(security, bars=constant_bars), {"sp500": constant_benchmark}
    )
    constant_missing = dict(constant_row.missing)

    assert constant_missing["position_52w"] == "zero_denominator"
    assert constant_missing["bollinger_z_20"] == "zero_denominator"
    assert constant_missing["beta_sp500_252d"] == "zero_denominator"

    profile = {**dict(security.profile), "market_cap": "0", "shares_outstanding": "0"}
    financials = {
        **dict(security.financials),
        "revenue_ttm": "0",
        "total_assets": "0",
        "trailing_pe": "0",
    }
    ratio_row = build_matrix_row(
        replace(
            security,
            profile=tuple(sorted(profile.items())),
            financials=tuple(sorted(financials.items())),
        ),
        {},
    )
    ratio_missing = dict(ratio_row.missing)

    assert ratio_missing["volume_turnover_20d"] == "zero_denominator"
    assert ratio_missing["free_cash_flow_margin"] == "zero_denominator"
    assert ratio_missing["equity_ratio"] == "zero_denominator"
    assert ratio_missing["earnings_yield"] == "zero_denominator"
    assert ratio_missing["free_cash_flow_yield"] == "zero_denominator"


def test_matrix_arithmetic_is_independent_of_the_ambient_decimal_context() -> None:
    security = _security()
    benchmark = _bars(US_INSTRUMENT)
    original = getcontext().copy()
    try:
        getcontext().prec = 6
        low_precision = build_matrix_row(security, {"sp500": benchmark})
        getcontext().prec = 50
        high_precision = build_matrix_row(security, {"sp500": benchmark})
    finally:
        setcontext(original)

    assert low_precision == high_precision


def test_summary_quantiles_use_decimal34_and_canonical_rendering() -> None:
    values = [
        Decimal("0.1234567890123456789012345678901234"),
        Decimal("0.2234567890123456789012345678901234"),
    ]

    assert _percentile(values, 25) == "0.1484567890123456789012345678901234"
    assert _median([Decimal("1E+3")]) == "1000"


def test_summary_canonicalizes_small_aggregate_ratios() -> None:
    first = _security()
    first_profile = {**dict(first.profile), "market_cap": "1", "sector": "Tiny"}
    second = replace(
        first,
        instrument=replace(first.instrument, symbol="ZZZ"),
        provider_symbol="ZZZ",
        profile=tuple(
            sorted({**dict(first.profile), "market_cap": "100000000", "sector": "Huge"}.items())
        ),
        evidence_id="b" * 64,
    )
    rows = (
        build_matrix_row(replace(first, profile=tuple(sorted(first_profile.items()))), {}),
        build_matrix_row(second, {}),
    )

    summary = _summary(rows, _configuration(), datetime(2026, 8, 7, tzinfo=UTC))

    share = summary["groups"]["all"]["sectors"]["Tiny"]["market_cap_share"]
    assert share == "0.0000000099999999000000009999999900000001"
    assert "E" not in share


def test_summary_keeps_market_cap_distributions_and_shares_separate_by_currency() -> None:
    us = build_matrix_row(_security(), {"sp500": _bars(US_INSTRUMENT)})
    jp = build_matrix_row(
        _security(JP_INSTRUMENT, memberships=("nikkei225",)),
        {"nikkei225": _bars(JP_INSTRUMENT)},
    )

    summary = _summary(
        (jp, us),
        _configuration(("nikkei225", "sp500")),
        datetime(2026, 8, 7, tzinfo=UTC),
    )
    combined = summary["groups"]["all"]

    assert "market_cap" not in combined["distributions"]
    assert "median_traded_value_20d" not in combined["distributions"]
    assert set(combined["currency_distributions"]["market_cap"]) == {"JPY", "USD"}
    assert set(combined["currency_distributions"]["median_traded_value_20d"]) == {"JPY", "USD"}
    assert combined["concentration"]["top_10_market_cap_share"] is None
    assert set(combined["concentration"]["by_currency"]) == {"JPY", "USD"}
    assert combined["sectors"]["Industrials"]["market_cap_share"] is None
    assert combined["sectors"]["Industrials"]["market_cap_share_by_currency"] == {"JPY": "1"}


def test_summary_omits_distributions_without_observations() -> None:
    row = build_matrix_row(
        replace(_security(count=0), bars=()),
        {},
    )

    summary = _summary((row,), _configuration(), datetime(2026, 8, 7, tzinfo=UTC))

    distributions = summary["groups"]["all"]["distributions"]
    assert "return_20d" not in distributions
    assert distributions["trailing_pe"]["count"] == 1


def _stored_matrix(
    tmp_path: Path,
) -> tuple[MarketSnapshotStore, dict[str, object], tuple[MatrixRow, ...]]:
    first = build_matrix_row(_security(), {"sp500": _bars(US_INSTRUMENT)})
    jp_security = _security(
        JP_INSTRUMENT,
        memberships=("nikkei225", "topix500"),
    )
    second = build_matrix_row(jp_security, {"nikkei225": _bars(JP_INSTRUMENT)})
    rows = (second, first)
    summary = _summary(
        rows,
        _configuration(("nikkei225", "sp500", "topix500")),
        datetime(2026, 8, 7, tzinfo=UTC),
    )
    store = MarketSnapshotStore(tmp_path / "matrices")
    request = {
        "schema": "market-snapshot-request/v1",
        "indices": ["nikkei225", "sp500", "topix500"],
        "assets": {},
        "start": "2023-08-08",
        "end": "2026-08-07",
        "adjustment": "adjusted",
        "settings": {},
        "source": {"name": "yfinance", "profile": "market-yfinance"},
    }
    request_fingerprint = _request_fingerprint(request)
    run_id = store.begin_run(request_fingerprint, request, resume=None)
    document = store.put(
        run_id=run_id,
        manifest_body={
            "created_at": "2026-08-07T00:00:00+00:00",
            "request": {"fingerprint": request_fingerprint, **request},
            "source": {
                "name": "yfinance",
                "version": "1.5.2",
                "dataset": "fixture",
                "response_hash": "c" * 64,
            },
            "input_snapshot_id": "c" * 64,
            "universe_assets": {},
            "configuration": {},
            "row_count": 2,
            "field_count": len(field_definitions()),
            "failure_count": sum(
                reason != "not_applicable" for row in rows for _, reason in row.missing
            ),
            "coverage": summary["coverage"],
            "price_requirements_met": summary["price_requirements_met"],
        },
        fields=field_definitions(),
        rows=rows,
        summary=summary,
        failures=tuple(
            {
                "instrument_id": f"{row.security.instrument.mic}:{row.security.instrument.symbol}",
                "stage": "calculation",
                "field": field,
                "reason": reason,
            }
            for row in rows
            for field, reason in row.missing
            if reason != "not_applicable"
        ),
    )
    return store, document, rows


def test_matrix_store_projects_self_contained_artifacts_and_offline_views(tmp_path: Path) -> None:
    store, document, rows = _stored_matrix(tmp_path)
    snapshot_id = str(document["snapshot_id"])
    path = tmp_path / "matrices" / "objects" / snapshot_id

    assert store.show("latest")["snapshot_id"] == snapshot_id
    schema_root = Path(__file__).parents[2] / "schemas"
    stored_manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    stored_manifest_schema = json.loads(
        (schema_root / "market-snapshot-manifest/v2/schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(stored_manifest_schema, format_checker=FormatChecker()).validate(
        stored_manifest
    )
    projection_schema = json.loads(
        (schema_root / "market-snapshot/v2/schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(projection_schema, format_checker=FormatChecker()).validate(document)
    for incomplete in (
        {**document, "coverage": {}},
        {**document, "coverage": {"nonsense": True}},
        {**document, "summary": {}},
        {**document, "summary": {"nonsense": True}},
        {**document, "artifacts": {}},
    ):
        assert not Draft202012Validator(projection_schema, format_checker=FormatChecker()).is_valid(
            incomplete
        )
    assert not Draft202012Validator(
        stored_manifest_schema, format_checker=FormatChecker()
    ).is_valid({**stored_manifest, "coverage": {}})
    json_rows = [json.loads(line) for line in (path / "securities.jsonl").read_text().splitlines()]
    assert len(json_rows) == len(rows)
    with (path / "securities.csv").open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == len(rows)
    assert set(field.name for field in field_definitions()).issubset(csv_rows[0])
    assert json.loads(csv_rows[0]["missing_fields_json"])
    for csv_row, json_row in zip(csv_rows, json_rows, strict=True):
        assert csv_row["instrument_id"] == json_row["instrument_id"]
        assert json.loads(csv_row["missing_fields_json"]) == json_row["missing"]
        assert all(
            csv_row[field.name] == json_row["values"].get(field.name, "")
            for field in field_definitions()
        )
    html = (path / "explorer.html").read_text(encoding="utf-8")
    assert "https://" not in html and "http://" not in html
    assert "data-column" in html and 'id="index"' in html and 'id="market"' in html
    assert "free_cash_flow_yield" in html
    readme = (path / "README.md").read_text(encoding="utf-8")
    summary_markdown = (path / "summary.md").read_text(encoding="utf-8")
    definitions = json.loads((path / "definitions.json").read_text())
    assert "securities.jsonl" in readme and "One row represents one security" in readme
    assert "Price coverage" in summary_markdown
    assert any(item["category"] == "expected" for item in definitions["missing_reasons"])
    assert all(item["path"] == name for name, item in stored_manifest["artifacts"].items())
    assert not (path / "analysis.md").exists()
    assert not list(path.glob("*.xlsx"))

    first_id = f"{rows[0].security.instrument.mic}:{rows[0].security.instrument.symbol}"
    second_id = f"{rows[1].security.instrument.mic}:{rows[1].security.instrument.symbol}"
    row_projection = store.row("latest", first_id)
    assert row_projection["instrument_id"] == first_id
    assert row_projection["snapshot_id"] == snapshot_id
    row_schema = json.loads(
        (
            Path(__file__).parents[2] / "schemas/market-snapshot-security-result/v1/schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(row_schema, format_checker=FormatChecker()).validate(row_projection)
    comparison = store.compare("latest", (first_id, second_id), ("close", "trailing_pe"))
    assert comparison["schema"] == "market-snapshot-comparison/v1"
    assert comparison["fields"] == ["close", "trailing_pe"]
    complete_comparison = store.compare("latest", (first_id, second_id), ())
    comparison_schema = json.loads(
        (Path(__file__).parents[2] / "schemas/market-snapshot-comparison/v1/schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(comparison_schema).validate(complete_comparison)
    for projected in complete_comparison["rows"]:
        assert set(projected["values"]) | set(projected["missing"]) == set(
            complete_comparison["fields"]
        )
        assert not set(projected["values"]) & set(projected["missing"])
    with pytest.raises(ValueError, match="unknown market snapshot fields"):
        store.compare("latest", (first_id, second_id), ("unknown",))
    with pytest.raises(ValueError, match="fields must be unique"):
        store.compare("latest", (first_id, second_id), ("close", "close"))


def test_matrix_store_lists_history_and_queries_saved_rows(tmp_path: Path) -> None:
    store, document, rows = _stored_matrix(tmp_path)
    request = {
        "schema": "market-snapshot-request/v1",
        "indices": ["nikkei225", "sp500", "topix500"],
        "assets": {},
        "start": "2023-08-09",
        "end": "2026-08-08",
        "adjustment": "adjusted",
        "settings": {},
        "source": {"name": "yfinance", "profile": "market-yfinance"},
    }
    fingerprint = _request_fingerprint(request)
    run_id = store.begin_run(fingerprint, request, resume=None)
    summary = _summary(
        rows,
        _configuration(("nikkei225", "sp500", "topix500")),
        datetime(2026, 8, 8, tzinfo=UTC),
    )
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
    newer = store.put(
        run_id=run_id,
        manifest_body={
            "created_at": "2026-08-08T00:00:00+00:00",
            "request": {"fingerprint": fingerprint, **request},
            "source": {
                "name": "yfinance",
                "version": "1.5.2",
                "dataset": "fixture",
                "response_hash": "d" * 64,
            },
            "input_snapshot_id": "d" * 64,
            "universe_assets": {},
            "configuration": {},
            "row_count": len(rows),
            "field_count": len(field_definitions()),
            "failure_count": len(failures),
            "coverage": summary["coverage"],
            "price_requirements_met": summary["price_requirements_met"],
        },
        fields=field_definitions(),
        rows=rows,
        summary=summary,
        failures=failures,
    )

    listing = store.list()
    assert listing["schema"] == "market-snapshot-list/v1"
    assert [item["snapshot_id"] for item in listing["snapshots"]] == [
        newer["snapshot_id"],
        document["snapshot_id"],
    ]

    result = store.query(
        str(document["snapshot_id"]),
        filters={"market": ("jp",), "index": ("nikkei225", "dow30")},
        minimums={"close": Decimal("300")},
        maximums={"close": Decimal("400")},
        present=("trailing_pe",),
        missing=("forward_pe",),
        fields=("close", "trailing_pe", "forward_pe"),
    )

    assert result["schema"] == "market-snapshot-query-result/v1"
    assert result["matched_count"] == 1
    assert [row["instrument_id"] for row in result["rows"]] == ["XTKS:7203"]
    assert result["rows"][0]["missing"] == {"forward_pe": "field_absent"}

    with pytest.raises(ValueError, match="numeric fields"):
        store.query(
            "latest",
            filters={},
            minimums={"name": Decimal("1")},
            maximums={},
            present=(),
            missing=(),
            fields=(),
        )
    with pytest.raises(ValueError, match="unknown market snapshot fields"):
        store.query(
            "latest",
            filters={},
            minimums={},
            maximums={},
            present=("unknown",),
            missing=(),
            fields=(),
        )
    with pytest.raises(ValueError, match="unknown market snapshot indices"):
        store.query(
            "latest",
            filters={"index": ("bogus",)},
            minimums={},
            maximums={},
            present=(),
            missing=(),
            fields=(),
        )
    with pytest.raises(ValueError, match="cannot be empty"):
        store.query(
            "latest",
            filters={"sector": ()},
            minimums={},
            maximums={},
            present=(),
            missing=(),
            fields=(),
        )


def test_matrix_store_lists_empty_history(tmp_path: Path) -> None:
    assert MarketSnapshotStore(tmp_path / "matrices").list() == {
        "schema": "market-snapshot-list/v1",
        "snapshots": [],
    }


def test_matrix_store_list_ignores_legacy_objects(tmp_path: Path) -> None:
    store, document, _ = _stored_matrix(tmp_path)
    legacy = tmp_path / "matrices" / "objects" / ("f" * 64)
    legacy.mkdir()
    legacy.joinpath("manifest.json").write_bytes(
        _json_bytes({"schema": "market-matrix-manifest/v1", "snapshot_id": "f" * 64})
    )

    listing = store.list()

    assert [item["snapshot_id"] for item in listing["snapshots"]] == [document["snapshot_id"]]


def test_matrix_store_keeps_published_object_when_run_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, previous, rows = _stored_matrix(tmp_path)
    previous_id = str(previous["snapshot_id"])
    request = {
        "schema": "market-snapshot-request/v1",
        "indices": ["nikkei225", "sp500", "topix500"],
        "assets": {},
        "start": "2023-08-09",
        "end": "2026-08-08",
        "adjustment": "adjusted",
        "settings": {},
        "source": {"name": "yfinance", "profile": "market-yfinance"},
    }
    request_fingerprint = _request_fingerprint(request)
    run_id = store.begin_run(request_fingerprint, request, resume=None)
    run_path = tmp_path / "matrices" / "runs" / run_id
    summary = _summary(
        rows,
        _configuration(("nikkei225", "sp500", "topix500")),
        datetime(2026, 8, 8, tzinfo=UTC),
    )
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
    original_rmtree = cast(Any, shutil.rmtree)

    def fail_run_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path) == run_path:
            raise PermissionError("fixture cleanup failure")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", fail_run_cleanup)

    published = store.put(
        run_id=run_id,
        manifest_body={
            "created_at": "2026-08-08T00:00:00+00:00",
            "request": {"fingerprint": request_fingerprint, **request},
            "source": {
                "name": "yfinance",
                "version": "1.5.2",
                "dataset": "fixture",
                "response_hash": "d" * 64,
            },
            "input_snapshot_id": "d" * 64,
            "universe_assets": {},
            "configuration": {},
            "row_count": len(rows),
            "field_count": len(field_definitions()),
            "failure_count": len(failures),
            "coverage": summary["coverage"],
            "price_requirements_met": summary["price_requirements_met"],
        },
        fields=field_definitions(),
        rows=rows,
        summary=summary,
        failures=failures,
    )

    monkeypatch.undo()
    assert published["snapshot_id"] != previous_id
    assert store.show("latest")["snapshot_id"] == published["snapshot_id"]
    assert run_path.is_dir()


def test_matrix_store_preserves_run_when_latest_publication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, previous, rows = _stored_matrix(tmp_path)
    previous_id = str(previous["snapshot_id"])
    request = {
        "schema": "market-snapshot-request/v1",
        "indices": ["nikkei225", "sp500", "topix500"],
        "assets": {},
        "start": "2023-08-09",
        "end": "2026-08-08",
        "adjustment": "adjusted",
        "settings": {},
        "source": {"name": "yfinance", "profile": "market-yfinance"},
    }
    request_fingerprint = _request_fingerprint(request)
    run_id = store.begin_run(request_fingerprint, request, resume=None)
    run_path = tmp_path / "matrices" / "runs" / run_id
    summary = _summary(
        rows,
        _configuration(("nikkei225", "sp500", "topix500")),
        datetime(2026, 8, 8, tzinfo=UTC),
    )
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
    original_replace = Path.replace

    def fail_latest_publication(path: Path, target: Path) -> Path:
        if Path(target) == store.latest_ref:
            raise OSError("fixture latest failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_latest_publication)

    with pytest.raises(OSError, match="fixture latest failure"):
        store.put(
            run_id=run_id,
            manifest_body={
                "created_at": "2026-08-08T00:00:00+00:00",
                "request": {"fingerprint": request_fingerprint, **request},
                "source": {
                    "name": "yfinance",
                    "version": "1.5.2",
                    "dataset": "fixture",
                    "response_hash": "d" * 64,
                },
                "input_snapshot_id": "d" * 64,
                "universe_assets": {},
                "configuration": {},
                "row_count": len(rows),
                "field_count": len(field_definitions()),
                "failure_count": len(failures),
                "coverage": summary["coverage"],
                "price_requirements_met": summary["price_requirements_met"],
            },
            fields=field_definitions(),
            rows=rows,
            summary=summary,
            failures=failures,
        )

    monkeypatch.undo()
    assert store.show("latest")["snapshot_id"] == previous_id
    assert run_path.is_dir()
    assert not list((tmp_path / "matrices").glob(".latest.*.tmp"))


def test_matrix_store_verifies_content_and_resume_fingerprint(tmp_path: Path) -> None:
    store, document, _ = _stored_matrix(tmp_path)
    request = {"schema": "fixture-resume-request/v1", "window": "first"}
    fingerprint = _request_fingerprint(request)
    run_id = store.begin_run(fingerprint, request, resume=None)
    assert store.run_request(run_id) == request
    assert store.begin_run(fingerprint, request, resume=run_id) == run_id
    different_request = {"schema": "fixture-resume-request/v1", "window": "second"}
    different_fingerprint = _request_fingerprint(different_request)
    with pytest.raises(ValueError, match="does not match"):
        store.begin_run(different_fingerprint, different_request, resume=run_id)
    with pytest.raises(ValueError, match="already exists"):
        store.begin_run(fingerprint, request, resume=None)
    with pytest.raises(ValueError, match="run ID"):
        store.begin_run(fingerprint, request, resume="../outside")
    with pytest.raises(ValueError, match="run ID"):
        store.begin_run(fingerprint, request, resume=str(tmp_path / "outside"))

    artifacts = cast(dict[str, str], document["artifacts"])
    path = Path(artifacts["securities.jsonl"])
    path.write_text(path.read_text().replace("Fixture Corp", "Tampered Corp", 1))
    with pytest.raises(ValueError, match="content identity"):
        store.show(str(document["snapshot_id"]))


def test_matrix_store_does_not_expose_a_partially_initialized_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MarketSnapshotStore(tmp_path / "matrices")
    request = {"schema": "fixture-request/v1"}
    fingerprint = _request_fingerprint(request)

    def fail_rename(_: Path, __: Path) -> Path:
        raise OSError("stop")

    with monkeypatch.context() as context:
        context.setattr(Path, "rename", fail_rename)
        with pytest.raises(OSError, match="stop"):
            store.begin_run(fingerprint, request, resume=None)

    assert list(store.runs.iterdir()) == []
    run_id = store.begin_run(fingerprint, request, resume=None)
    assert store.run_request(run_id) == request


@pytest.mark.parametrize(
    "artifact",
    (
        "manifest.json",
        "definitions.json",
        "quality.json",
        "market.json",
        "securities.jsonl",
        "failures.jsonl",
    ),
)
def test_matrix_store_rejects_noncanonical_evidence(tmp_path: Path, artifact: str) -> None:
    store, document, _ = _stored_matrix(tmp_path)
    snapshot_id = str(document["snapshot_id"])
    path = tmp_path / "matrices" / "objects" / snapshot_id / artifact
    path.write_bytes(path.read_bytes().replace(b"{", b"{ ", 1))

    with pytest.raises(ValueError, match="not canonical"):
        store.show(snapshot_id)


@pytest.mark.parametrize(
    ("artifact", "message"),
    (
        ("securities.csv", "CSV projection"),
        ("explorer.html", "HTML projection"),
        ("README.md", "README projection"),
        ("summary.md", "summary projection"),
    ),
)
def test_matrix_store_rejects_tampered_projections(
    tmp_path: Path, artifact: str, message: str
) -> None:
    store, document, rows = _stored_matrix(tmp_path)
    snapshot_id = str(document["snapshot_id"])
    path = tmp_path / "matrices" / "objects" / snapshot_id / artifact
    path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match=message):
        store.show(snapshot_id)
    instrument = rows[0].security.instrument
    with pytest.raises(ValueError, match=message):
        store.row(snapshot_id, f"{instrument.mic}:{instrument.symbol}")


def test_matrix_store_rejects_an_unlisted_file(tmp_path: Path) -> None:
    store, document, _ = _stored_matrix(tmp_path)
    snapshot_id = str(document["snapshot_id"])
    path = tmp_path / "matrices" / "objects" / snapshot_id
    (path / "analysis.md").write_text("external interpretation\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inventory"):
        store.show(snapshot_id)


def test_built_in_universe_deduplicates_overlapping_memberships() -> None:
    securities, assets = _load_universe(("dow30", "nasdaq100", "sp500", "topix500"))
    identities = [(security.instrument.mic, security.instrument.symbol) for security in securities]

    assert len(identities) == len(set(identities))
    assert set(assets) == {"dow30", "nasdaq100", "sp500", "topix500"}
    assert all(len(asset["asset_hash"]) == 64 for asset in assets.values())
    assert any(len(security.memberships) > 1 for security in securities)
    assert assets["topix500"]["benchmark_symbol"] == "1308.T"
    assert assets["topix500"]["benchmark_kind"] == "etf_proxy"
    topix_fields = {field.name: field for field in field_definitions() if "topix500" in field.name}
    assert topix_fields
    assert all("ETF proxy 1308.T" in field.definition for field in topix_fields.values())


@dataclass
class _Registry:
    fetcher: EquityBatchFetcher

    def load_equity_batch_fetcher(self, name: str) -> EquityBatchFetcher:
        assert name == "yfinance"
        return self.fetcher


class _Fetcher:
    def doctor(self) -> SourceDiagnostic:
        return SourceDiagnostic(True, "ready", "fixture")

    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch:
        observations = []
        for item in request.instruments:
            profile = (
                ()
                if item.provider_symbol.startswith("^")
                else (
                    ("exchange", "NMS"),
                    ("market_cap", "1000"),
                    ("name", item.provider_symbol),
                )
            )
            observations.append(
                EquityBatchObservation(
                    item,
                    datetime(2026, 8, 7, tzinfo=UTC),
                    tuple(
                        replace(bar, adjustment=request.adjustment)
                        for bar in _bars(item.instrument)
                        if request.start <= bar.trading_date <= request.end
                    ),
                    tuple(sorted(profile)),
                    (),
                    "a" * 64,
                )
            )
        return ImportedEquityBatch(
            request,
            "yfinance",
            "1.5.2",
            "fixture",
            datetime(2026, 8, 7, tzinfo=UTC),
            tuple(observations),
            (),
            "b" * 64,
        )


class _InterruptedFetcher(_Fetcher):
    def __init__(self) -> None:
        self.attempts = 0
        self.requests: list[EquityBatchRequest] = []

    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch:
        self.attempts += 1
        self.requests.append(request)
        if self.attempts == 1:
            raise RuntimeError("fixture interruption")
        return super().fetch(request)


class _MismatchedRequestFetcher(_Fetcher):
    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch:
        imported = super().fetch(request)
        return replace(
            imported, request=replace(request, timeout_seconds=request.timeout_seconds + 1)
        )


class _FailureFetcher(_Fetcher):
    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch:
        imported = super().fetch(request)
        target = next(
            observation
            for observation in imported.observations
            if not observation.requested.provider_symbol.startswith("^")
        )
        observations = tuple(
            replace(observation, bars=(), profile=(), financials=())
            if observation.requested == target.requested
            else observation
            for observation in imported.observations
        )
        return replace(
            imported,
            observations=observations,
            failures=(
                EquityAcquisitionFailure(
                    target.requested.instrument,
                    "price",
                    "history",
                    "network_error",
                ),
                EquityAcquisitionFailure(
                    target.requested.instrument,
                    "profile",
                    "company",
                    "rate_limited",
                ),
                EquityAcquisitionFailure(
                    target.requested.instrument,
                    "financials",
                    "company_financials",
                    "financials_unavailable",
                ),
            ),
        )


class _SiblingFailureFetcher(_Fetcher):
    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch:
        imported = super().fetch(request)
        targets = tuple(
            observation
            for observation in imported.observations
            if not observation.requested.provider_symbol.startswith("^")
        )[:2]
        statement_target, info_target = targets
        observations = tuple(
            replace(
                observation,
                profile=(),
                financials=(("revenue_ttm", "100"),),
            )
            if observation.requested == statement_target.requested
            else replace(
                observation,
                financials=(("free_cash_flow_ttm", "20"),),
            )
            if observation.requested == info_target.requested
            else observation
            for observation in imported.observations
        )
        return replace(
            imported,
            observations=observations,
            failures=(
                EquityAcquisitionFailure(
                    statement_target.requested.instrument,
                    "profile",
                    "company",
                    "rate_limited",
                ),
                EquityAcquisitionFailure(
                    info_target.requested.instrument,
                    "financials",
                    "quarterly_cash_flow",
                    "provider_error",
                ),
            ),
        )


class _Configuration:
    def market_configuration(self) -> MarketConfiguration:
        return _configuration(("dow30",))


def test_matrix_service_builds_every_constituent_with_authoritative_asset_identity(
    tmp_path: Path,
) -> None:
    service = MarketService(
        _Registry(_Fetcher()),
        MarketSnapshotStore(tmp_path / "matrices"),
        _Configuration(),
        today=lambda: date(2026, 8, 7),
    )

    document = service.refresh()

    assert document["row_count"] == 30
    assert document["price_requirements_met"] is True
    assert document["coverage"]["overall"] == "1"
    assert document["request"]["fingerprint"]
    assert document["request"]["start"] == "2023-08-08"
    assert document["request"]["end"] == "2026-08-07"
    row_path = Path(document["artifacts"]["securities.jsonl"])
    rows = [json.loads(line) for line in row_path.read_text().splitlines()]
    assert len(rows) == 30
    assert any(row["instrument_id"] == "XNAS:AAPL" for row in rows)
    assert any(row["instrument_id"] == "XNYS:JPM" for row in rows)
    assert all(row["schema"] == "market-snapshot-security/v1" for row in rows)
    assert all(
        set(row["values"]) | set(row["missing"]) == {f.name for f in field_definitions()}
        for row in rows
    )


def test_built_in_universe_names_are_well_formed() -> None:
    path = (
        Path(__file__).parents[2] / "packages/cli/src/marketsieve_cli/resources/index_universe.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))

    suspicious = ("Ã", "â", "�")
    names = [
        member["name"] for index in document["indices"].values() for member in index["members"]
    ]
    assert not [name for name in names if any(marker in name for marker in suspicious)]
    assert "Amazon.com, Inc.amazon.com" not in names
    assert all(name and name == name.strip() for name in names)


def test_matrix_service_resumes_only_the_persisted_request(tmp_path: Path) -> None:
    fetcher = _InterruptedFetcher()
    root = tmp_path / "matrices"
    store = MarketSnapshotStore(root)
    service = MarketService(
        _Registry(fetcher), store, _Configuration(), today=lambda: date(2026, 8, 7)
    )

    with pytest.raises(RuntimeError, match="fixture interruption"):
        service.refresh()
    run_ids = [path.name for path in (root / "runs").iterdir()]
    assert len(run_ids) == 1

    resumed_service = MarketService(
        _Registry(fetcher), store, _Configuration(), today=lambda: date(2026, 8, 7)
    )
    document = resumed_service.refresh(resume=run_ids[0])

    assert fetcher.attempts == 2
    assert fetcher.requests[1].start == fetcher.requests[0].start
    assert fetcher.requests[1].end == fetcher.requests[0].end
    assert document["row_count"] == 30
    assert not (root / "runs" / run_ids[0]).exists()


def test_matrix_service_rejects_resume_after_the_original_acquisition_date(
    tmp_path: Path,
) -> None:
    fetcher = _InterruptedFetcher()
    root = tmp_path / "matrices"
    store = MarketSnapshotStore(root)
    service = MarketService(
        _Registry(fetcher), store, _Configuration(), today=lambda: date(2026, 8, 7)
    )

    with pytest.raises(RuntimeError, match="fixture interruption"):
        service.refresh()
    run_id = next((root / "runs").iterdir()).name
    delayed = MarketService(
        _Registry(fetcher), store, _Configuration(), today=lambda: date(2026, 8, 8)
    )

    with pytest.raises(ValueError, match="original acquisition date"):
        delayed.refresh(resume=run_id)

    assert fetcher.attempts == 1
    assert store.run_request(run_id)["end"] == "2026-08-07"


def test_matrix_service_rejects_acquisition_that_crosses_the_local_date(
    tmp_path: Path,
) -> None:
    dates = iter((date(2026, 8, 7), date(2026, 8, 8)))
    root = tmp_path / "matrices"
    store = MarketSnapshotStore(root)
    service = MarketService(
        _Registry(_Fetcher()),
        store,
        _Configuration(),
        today=lambda: next(dates),
    )

    with pytest.raises(ValueError, match="crossed the local date boundary"):
        service.refresh()

    assert not (root / "objects").exists()
    run = next((root / "runs").iterdir())
    assert store.run_request(run.name)["end"] == "2026-08-07"


def test_matrix_service_rejects_a_batch_for_a_different_request(tmp_path: Path) -> None:
    service = MarketService(
        _Registry(_MismatchedRequestFetcher()),
        MarketSnapshotStore(tmp_path / "matrices"),
        _Configuration(),
        today=lambda: date(2026, 8, 7),
    )

    with pytest.raises(ValueError, match="exact market request"):
        service.refresh()


def test_matrix_store_rejects_symlinked_root_and_run_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    request = {"schema": "fixture-request/v1"}
    fingerprint = _request_fingerprint(request)

    linked_root = tmp_path / "linked-matrices"
    linked_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="real directory"):
        MarketSnapshotStore(linked_root).begin_run(fingerprint, request, resume=None)

    external_state = tmp_path / "external-state"
    external_state.mkdir()
    linked_state = tmp_path / ".marketsieve"
    linked_state.symlink_to(external_state, target_is_directory=True)
    with pytest.raises(ValueError, match="real directory"):
        MarketSnapshotStore(linked_state / "matrices").begin_run(fingerprint, request, resume=None)

    root = tmp_path / "matrices"
    root.mkdir()
    (root / "runs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="real directory"):
        MarketSnapshotStore(root).begin_run(fingerprint, request, resume=None)


def test_matrix_store_rejects_symlinked_object_directory(tmp_path: Path) -> None:
    store, document, _ = _stored_matrix(tmp_path)
    root = tmp_path / "matrices"
    objects = root / "objects"
    objects.rename(root / "real-objects")
    outside = tmp_path / "outside"
    outside.mkdir()
    objects.symlink_to(outside, target_is_directory=True)

    with pytest.raises(LookupError, match="storage directory"):
        store.show(str(document["snapshot_id"]))
    with pytest.raises(LookupError, match="storage directory"):
        store.query(
            str(document["snapshot_id"]),
            filters={},
            minimums={},
            maximums={},
            present=(),
            missing=(),
            fields=(),
        )


def test_matrix_store_rejects_an_invalid_latest_reference(tmp_path: Path) -> None:
    store, _, _ = _stored_matrix(tmp_path)
    (tmp_path / "matrices" / "latest.json").write_text('{"unexpected":"value"}\n')

    with pytest.raises(ValueError, match="market snapshot latest reference is invalid"):
        store.show("latest")


def test_matrix_service_propagates_provider_failures_to_empty_cells(tmp_path: Path) -> None:
    service = MarketService(
        _Registry(_FailureFetcher()),
        MarketSnapshotStore(tmp_path / "matrices"),
        _Configuration(),
    )

    document = service.refresh()
    rows = [
        json.loads(line)
        for line in Path(document["artifacts"]["securities.jsonl"]).read_text().splitlines()
    ]
    target = next(row for row in rows if not row["values"].get("name"))

    assert target["missing"]["close"] == "network_error"
    assert target["missing"]["relative_return_dow30_20d"] == "network_error"
    assert target["missing"]["beta_dow30_252d"] == "network_error"
    assert target["missing"]["name"] == "rate_limited"
    assert target["missing"]["quote_type"] == "rate_limited"
    assert target["missing"]["trailing_pe"] == "rate_limited"
    assert target["missing"]["total_assets"] == "financials_unavailable"
    assert target["missing"]["earnings_cagr_3y"] == "financials_unavailable"
    assert target["missing"]["equity_ratio"] == "financials_unavailable"
    assert target["missing"]["free_cash_flow_margin"] == "financials_unavailable"


def test_matrix_service_preserves_values_acquired_from_a_sibling_endpoint(tmp_path: Path) -> None:
    service = MarketService(
        _Registry(_SiblingFailureFetcher()),
        MarketSnapshotStore(tmp_path / "matrices"),
        _Configuration(),
    )

    document = service.refresh()
    rows = [
        json.loads(line)
        for line in Path(document["artifacts"]["securities.jsonl"]).read_text().splitlines()
    ]
    statement_row = next(row for row in rows if row["values"].get("revenue_ttm") == "100")
    info_row = next(row for row in rows if row["values"].get("free_cash_flow_ttm") == "20")

    assert statement_row["missing"]["name"] == "rate_limited"
    assert "revenue_ttm" not in statement_row["missing"]
    assert info_row["missing"]["operating_cash_flow_ttm"] == "provider_error"
    assert "free_cash_flow_ttm" not in info_row["missing"]


def test_whole_financial_failure_maps_every_financial_and_dependent_field() -> None:
    failure = EquityAcquisitionFailure(
        US_INSTRUMENT,
        "financials",
        "company_financials",
        "financials_unavailable",
    )
    expected = {
        field.name
        for field in field_definitions()
        if field.group in {"financial", "fundamental", "profitability", "safety", "valuation"}
    }

    assert _provider_failure_fields(failure) == expected


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        (
            "volume_20d",
            {
                "average_volume_20d",
                "average_volume_60d",
                "median_traded_value_20d",
                "volume_turnover_20d",
                "amihud_illiquidity_20d",
                "zero_volume_days_20d",
            },
        ),
        ("volume_60d", {"average_volume_60d"}),
    ),
)
def test_volume_failure_maps_only_affected_liquidity_fields(field: str, expected: set[str]) -> None:
    failure = EquityAcquisitionFailure(US_INSTRUMENT, "volume", field, "field_absent")

    assert _provider_failure_fields(failure) == expected
