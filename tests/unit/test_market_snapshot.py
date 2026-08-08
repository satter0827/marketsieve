from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from marketsieve.domain import Instrument
from marketsieve.matrix import MatrixRow, MatrixSecurity, build_matrix_row, field_definitions
from marketsieve.synthetic.daily import JP_INSTRUMENT, US_INSTRUMENT, fixture_bars
from marketsieve_cli.adapters.config import Settings
from marketsieve_cli.adapters.market_snapshots import MarketSnapshotStore, _request_fingerprint
from marketsieve_cli.application.market import MarketService, _not_requested_fields, _summary
from marketsieve_cli.contracts import MarketBuildInputs, RuntimeSettings
from marketsieve_extension_api import (
    EquityBatchObservation,
    EquityBatchRequest,
    ImportedEquityBatch,
    SourceDiagnostic,
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
            "price_requirements_met": summary["price_requirements_met"],
        },
        fields=field_definitions(),
        rows=rows,
        summary=summary,
        failures=failures,
    )
    return store, document


def test_snapshot_is_self_contained_without_spreadsheets(tmp_path: Path) -> None:
    store, document = _store(tmp_path)
    root = Path(document["artifacts"]["manifest.json"]).parent

    assert document["schema"] == "market-snapshot/v3"
    assert set(path.name for path in root.iterdir()) == set(document["artifacts"])
    assert (root / "aggregates.jsonl").is_file()
    assert not list(root.glob("*.csv"))
    assert not list(root.glob("*.xlsx"))
    assert "http://" not in (root / "explorer.html").read_text()
    assert "https://" not in (root / "explorer.html").read_text()
    assert store.list()["schema"] == "market-snapshot-list/v2"
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
    def doctor(self) -> SourceDiagnostic:
        return SourceDiagnostic(True, "ready", "ready")

    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch:
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
    def load_equity_batch_fetcher(self, name: str) -> _BatchFetcher:
        assert name == "yfinance"
        return _BatchFetcher()


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
    }
    assert document["row_count"] == 30
    assert document["price_requirements_met"] is True
    row = service.row(document["snapshot_id"], "XNAS:AAPL")
    assert row["missing"]["close"] == "not_requested"
    assert row["missing"]["trailing_pe"] == "not_requested"
    failures = [
        json.loads(line)
        for line in Path(document["artifacts"]["failures.jsonl"]).read_text().splitlines()
    ]
    assert not any(failure["field"] == "close" for failure in failures)
    assert service.show("latest")["snapshot_id"] == document["snapshot_id"]
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/market-snapshot/v3/schema.json").read_text()
    )
    Draft202012Validator(schema).validate(document)


def test_financial_only_scope_preserves_required_currency_field() -> None:
    missing = dict(_not_requested_fields(("financials",)))

    assert "financial_currency" not in missing
    assert missing["currency"] == "not_requested"
