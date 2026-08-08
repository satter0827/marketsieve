"""Create a compact Snapshot v7 fixture for Explorer browser evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from marketsieve.matrix import field_definitions
from marketsieve_cli.adapters.explorer_v2 import (
    build_research_explorer_data,
    build_snapshot_explorer_data,
    render_explorer,
)


def _write(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, documents: Sequence[Mapping[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in documents
        ),
        encoding="utf-8",
    )


def _build_research(output: Path) -> None:
    output.mkdir()
    names = (
        "README.md",
        "manifest.json",
        "definitions.json",
        "company.json",
        "market-context.json",
        "prices.jsonl",
        "benchmarks.jsonl",
        "financials.jsonl",
        "events.jsonl",
        "failures.jsonl",
        "quality.json",
        "summary.md",
        "explorer-data.json",
        "explorer.html",
    )
    manifest = {
        "schema": "security-research-manifest/v6",
        "research_id": "1" * 64,
        "snapshot_id": "0" * 64,
        "instrument_id": "XNAS:MSFT",
        "provider_symbol": "MSFT",
        "created_at": "2026-08-08T00:00:00+00:00",
        "source": {"name": "yfinance", "version": "1.5.2", "response_hash": "2" * 64},
        "artifacts": {name: name for name in names},
    }
    definitions = {
        "schema": "security-research-definitions/v3",
        "company_fields": [{"name": "name", "data_type": "string"}],
    }
    prices = [
        {
            "schema": "security-research-price/v1",
            "date": f"2026-07-{day:02d}",
            "open": str(100 + day),
            "high": str(102 + day),
            "low": str(99 + day),
            "close": str(101 + day),
            "volume": 1_000_000 + day * 1_000,
            "adjustment": "adjusted",
            "missing": {},
        }
        for day in range(1, 29)
    ]
    quality = {
        "schema": "security-research-quality/v3",
        "evidence_statuses": {
            "price": "available",
            "company": "available",
            "annual_financials": "available",
            "quarterly_financials": "none_observed",
            "earnings": "acquisition_failed",
            "dividends": "available",
            "splits": "none_observed",
            "benchmarks": "available",
        },
    }
    financials = [
        {
            "schema": "security-research-financial/v1",
            "concept": "revenue",
            "statement": "income",
            "period": "annual",
            "fiscal_period_end": "2025-06-30",
            "currency": "USD",
            "value": "1000000",
            "available_at": "2026-08-08T00:00:00+00:00",
            "availability_basis": "retrieval",
        }
    ]
    events = [
        {
            "schema": "security-research-event/v1",
            "event_type": "dividend",
            "effective_date": "2026-07-15",
            "values": {"amount": "0.83"},
            "available_at": "2026-08-08T00:00:00+00:00",
            "availability_basis": "retrieval",
        }
    ]
    benchmarks = [
        {
            "schema": "security-research-benchmark-price/v1",
            "benchmark": "sp500",
            "provider_symbol": "^GSPC",
            "date": value["date"],
            "close": str(5000 + index * 10),
            "adjustment": "adjusted",
        }
        for index, value in enumerate(prices)
    ]
    _write(output / "manifest.json", manifest)
    _write(output / "definitions.json", definitions)
    _write(
        output / "company.json",
        {
            "schema": "security-research-company/v1",
            "instrument_id": "XNAS:MSFT",
            "provider_symbol": "MSFT",
            "retrieved_at": "2026-08-08T00:00:00+00:00",
            "availability_basis": "retrieval",
            "values": {"name": "Microsoft"},
        },
    )
    _write(output / "market-context.json", {})
    _write_jsonl(output / "prices.jsonl", prices)
    _write_jsonl(output / "benchmarks.jsonl", benchmarks)
    _write_jsonl(output / "financials.jsonl", financials)
    _write_jsonl(output / "events.jsonl", events)
    _write_jsonl(
        output / "failures.jsonl",
        [
            {
                "schema": "security-research-failure/v1",
                "instrument_id": "XNAS:MSFT",
                "stage": "research",
                "field": "earnings",
                "reason": "network_error",
            }
        ],
    )
    _write(output / "quality.json", quality)
    (output / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (output / "summary.md").write_text("# Fixture\n", encoding="utf-8")
    explorer = build_research_explorer_data(manifest, definitions)
    _write(output / "explorer-data.json", explorer)
    (output / "explorer.html").write_text(render_explorer(explorer), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)
    fields = [asdict(field) for field in field_definitions()]
    artifacts = {
        name: name
        for name in (
            "manifest.json",
            "definitions.json",
            "quality.json",
            "aggregates.jsonl",
            "securities.jsonl",
            "failures.jsonl",
            "market-indicators.jsonl",
            "explorer-data.json",
            "explorer.html",
        )
    }
    manifest = {
        "schema": "market-snapshot-manifest/v7",
        "snapshot_id": "0" * 64,
        "created_at": "2026-08-08T00:00:00+00:00",
        "source": {"name": "yfinance", "version": "1.5.2"},
        "artifacts": artifacts,
    }
    definitions = {
        "schema": "market-snapshot-definitions/v3",
        "fields": fields,
        "missing_reasons": [],
    }
    quality = {
        "schema": "market-snapshot-quality/v3",
        "domains": {"price": {"applicable": 2, "present": 2, "coverage": "1"}},
        "freshness": {
            "price_age_days": {"observation_count": 2, "median": 0, "p95": 0, "maximum": 0}
        },
        "failures": {"record_count": 0, "affected_security_count": 0},
    }
    base_values = {
        "currency": "USD",
        "sector": "Technology",
        "industry": "Software",
        "close": "200",
        "return_5d": "0.01",
        "return_20d": "0.04",
        "return_60d": "0.08",
        "volatility_60d": "0.2",
        "atr_14_ratio": "0.02",
        "distance_sma_20": "0.03",
        "distance_sma_200": "0.08",
        "position_52w": "0.7",
        "maximum_drawdown_252d": "-0.15",
        "trailing_pe": "22",
        "earnings_growth": "0.12",
        "price_to_book": "5",
        "return_on_equity": "0.2",
        "price_as_of": "2026-08-07",
    }
    rows = [
        {
            "instrument_id": "XNAS:MSFT",
            "provider_symbol": "MSFT",
            "instrument": {"mic": "XNAS", "currency": "USD"},
            "memberships": ["nasdaq100", "sp500"],
            "values": {**base_values, "name": "Microsoft Corporation"},
            "missing": {},
            "temporal": {},
        },
        {
            "instrument_id": "XNAS:NVDA",
            "provider_symbol": "NVDA",
            "instrument": {"mic": "XNAS", "currency": "USD"},
            "memberships": ["nasdaq100", "sp500"],
            "values": {
                **base_values,
                "name": "NVIDIA Corporation",
                "return_20d": "-0.02",
                "return_60d": "0.03",
            },
            "missing": {},
            "temporal": {},
        },
    ]
    _write(output / "manifest.json", manifest)
    _write(output / "definitions.json", definitions)
    _write(output / "quality.json", quality)
    (output / "aggregates.jsonl").write_text("{}\n", encoding="utf-8")
    (output / "securities.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    (output / "failures.jsonl").write_text("", encoding="utf-8")
    (output / "market-indicators.jsonl").write_text("", encoding="utf-8")
    explorer = build_snapshot_explorer_data(manifest, fields)
    _write(output / "explorer-data.json", explorer)
    (output / "explorer.html").write_text(render_explorer(explorer), encoding="utf-8")
    _build_research(output / "research")


if __name__ == "__main__":
    main()
