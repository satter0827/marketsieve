from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from marketsieve import (
    DecisionAction,
    DecisionConfidence,
    DecisionEvidence,
    DecisionReport,
    EvidenceDirection,
    Holding,
    InstrumentDecision,
    MarketSession,
    PortfolioSnapshot,
)
from marketsieve.domain import Instrument
from marketsieve_ai import build_report_request
from marketsieve_cli.adapters.ai_exchange import AiExchangeStore, canonical_bytes
from marketsieve_cli.application.ai import ManualAiService

ROOT = Path(__file__).parents[2]


def example_report() -> DecisionReport:
    instrument = Instrument.create(
        symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
    )
    settings = (("rsi_overbought", "70"),)
    decision = InstrumentDecision(
        instrument,
        True,
        DecisionAction.KEEP,
        DecisionConfidence.MEDIUM,
        (
            DecisionEvidence(
                "trend_above_sma60",
                EvidenceDirection.SUPPORTING,
                "2500",
                "2400",
                ("bars-evidence",),
            ),
        ),
        None,
        Decimal("0.05"),
        Decimal("0.03"),
        Decimal("1000000"),
        (("per", "14.2"),),
        (("latest_filing", "fixture-2026"),),
        ("close_below_sma60",),
        "次の終値で傾向を確認する",
        "balanced_medium_term",
        "1.0.0",
        settings,
    )
    portfolio = PortfolioSnapshot(
        datetime(2026, 8, 3, 6, tzinfo=UTC),
        (Holding(instrument, Decimal("10"), Decimal("2300"), "taxable"),),
        (),
        "fixture",
    )
    return DecisionReport(
        "a" * 64,
        "decision-report/v1",
        MarketSession.JP_CLOSE,
        portfolio.as_of,
        portfolio,
        decision.policy_name,
        decision.policy_version,
        settings,
        (decision,),
        ("FRED系列は未取得",),
    )


def response(request_id: str) -> str:
    return json.dumps(
        {
            "request_id": request_id,
            "section_order": ["XTKS:7203"],
            "selected_fact_ids": ["decision.XTKS:7203.action"],
            "connections": [],
        },
        ensure_ascii=False,
    )


def validate_schema(name: str, document: object) -> None:
    schema = json.loads((ROOT / "schemas" / name / "v1" / "schema.json").read_text())
    Draft202012Validator(schema).validate(document)


class ReportReader:
    def resolve(self, report_id: str) -> DecisionReport:
        if report_id not in {"latest", "a" * 64}:
            raise LookupError("report does not exist")
        return example_report()


class DisappearingReportReader:
    def __init__(self) -> None:
        self.available = True

    def resolve(self, report_id: str) -> DecisionReport:
        del report_id
        if not self.available:
            raise LookupError("source report disappeared")
        return example_report()


def service(root: Path) -> ManualAiService:
    return ManualAiService(
        ReportReader(),
        AiExchangeStore(root),
        clock=lambda: datetime(2026, 8, 6, 12, tzinfo=UTC),
    )


def test_prepare_import_show_keeps_artifacts_separate(tmp_path: Path) -> None:
    selected = service(tmp_path)
    prepared = selected.prepare_report("latest", "ja")
    prepared.response_path.write_text(response(prepared.request_id), encoding="utf-8")

    explanation = selected.import_response(
        prepared.response_path, model_label="shown-label", controlled=True
    )

    assert selected.show("latest") == explanation
    assert explanation["service"] == "chatgpt"
    assert explanation["model_label"] == "shown-label"
    assert explanation["controlled"] is True
    assert "keep" in explanation["text"]
    for kind in ("request", "response", "validation", "explanation"):
        assert len(tuple((tmp_path / kind / "objects").glob("*.json"))) == 1
    validate_schema("report-ai-request", json.loads(prepared.request_path.read_text()))
    response_document = json.loads(next((tmp_path / "response/objects").glob("*.json")).read_text())
    validate_schema("report-ai-response", response_document)
    validation_document = json.loads(
        next((tmp_path / "validation/objects").glob("*.json")).read_text()
    )
    validate_schema("report-ai-validation", validation_document)
    validate_schema("report-ai-explanation", explanation)
    assert prepared.request_path.read_bytes() == canonical_bytes(
        build_report_request(example_report())
    )


def test_reimporting_the_same_request_creates_a_new_trial(tmp_path: Path) -> None:
    selected = service(tmp_path)
    prepared = selected.prepare_report("latest", "ja")
    prepared.response_path.write_text(response(prepared.request_id), encoding="utf-8")

    first = selected.import_response(prepared.response_path)
    second = selected.import_response(prepared.response_path)

    assert first["trial"] == 1
    assert second["trial"] == 2
    assert first["response_id"] != second["response_id"]


def test_trial_numbering_rejects_a_noncanonical_stored_response(tmp_path: Path) -> None:
    selected = service(tmp_path)
    prepared = selected.prepare_report("latest", "ja")
    prepared.response_path.write_text(response(prepared.request_id), encoding="utf-8")
    directory = tmp_path / "response" / "objects"
    directory.mkdir(parents=True)
    (directory / f"{'e' * 64}.json").write_text(
        json.dumps(
            {
                "schema": "report-ai-response/v1",
                "request_id": prepared.request_id,
                "trial": 999,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not canonical"):
        selected.import_response(prepared.response_path)


def test_invalid_response_is_audited_without_an_explanation(tmp_path: Path) -> None:
    selected = service(tmp_path)
    prepared = selected.prepare_report("latest", "ja")
    prepared.response_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError):
        selected.import_response(prepared.response_path)

    assert len(tuple((tmp_path / "response" / "objects").glob("*.json"))) == 1
    validation_path = next((tmp_path / "validation" / "objects").glob("*.json"))
    validation = json.loads(validation_path.read_text())
    assert validation["status"] == "invalid"
    validate_schema("report-ai-validation", validation)
    assert not (tmp_path / "explanation" / "objects").exists()


@pytest.mark.parametrize(
    "raw,error",
    [
        (b"[" * 10_000 + b"0" + b"]" * 10_000, "recursion depth"),
        (b"\xff", "UTF-8"),
    ],
)
def test_malformed_bytes_are_losslessly_audited_as_invalid(
    tmp_path: Path, raw: bytes, error: str
) -> None:
    selected = service(tmp_path)
    prepared = selected.prepare_report("latest", "ja")
    prepared.response_path.write_bytes(raw)

    with pytest.raises(ValueError, match=error):
        selected.import_response(prepared.response_path)

    response_path = next((tmp_path / "response" / "objects").glob("*.json"))
    stored = json.loads(response_path.read_text(encoding="utf-8"))
    assert base64.b64decode(stored["raw_base64"], validate=True) == raw
    assert stored["raw_text"] == (raw.decode("utf-8") if error != "UTF-8" else None)
    validation_path = next((tmp_path / "validation" / "objects").glob("*.json"))
    assert json.loads(validation_path.read_text(encoding="utf-8"))["status"] == "invalid"


def test_malformed_response_uses_its_inbox_request_not_the_latest_request(tmp_path: Path) -> None:
    selected = service(tmp_path)
    older = selected.prepare_report("latest", "ja")
    newer = selected.prepare_report("latest", "en")
    assert older.request_id != newer.request_id
    older.response_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError):
        selected.import_response(older.response_path)

    response_path = next((tmp_path / "response" / "objects").glob("*.json"))
    assert json.loads(response_path.read_text())["request_id"] == older.request_id


def test_unparseable_response_without_request_binding_is_rejected(tmp_path: Path) -> None:
    selected = service(tmp_path)
    selected.prepare_report("latest", "ja")
    path = tmp_path / "response.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be bound"):
        selected.import_response(path)

    assert not (tmp_path / "response" / "objects").exists()


def test_store_rejects_noncanonical_or_symlinked_content(tmp_path: Path) -> None:
    store = AiExchangeStore(tmp_path / "ai")
    request = build_report_request(example_report())
    request_id = request.pop("request_id")
    stored = store.put("request", request)
    assert stored["request_id"] == request_id

    path = store.path("request", request_id)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="not canonical"):
        store.show("request", request_id)


def test_oversized_response_is_rejected_before_it_is_stored(tmp_path: Path) -> None:
    selected = service(tmp_path)
    prepared = selected.prepare_report("latest", "ja")
    prepared.response_path.write_bytes(b" " * 65_537)

    with pytest.raises(ValueError, match="size limit"):
        selected.import_response(prepared.response_path)

    assert not (tmp_path / "response" / "objects").exists()


def test_store_rejects_invalid_kinds_ids_schemas_and_references(tmp_path: Path) -> None:
    store = AiExchangeStore(tmp_path / "ai")

    with pytest.raises(ValueError, match="unsupported"):
        store.put("unknown", {})
    with pytest.raises(ValueError, match="unexpected schema"):
        store.put("request", {"schema": "wrong"})
    with pytest.raises(ValueError, match="reserved"):
        store.put("request", {"request_id": "a" * 64})
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        store.response_path("invalid")
    with pytest.raises(LookupError, match="does not exist"):
        store.show("request", "a" * 64)
    with pytest.raises(LookupError, match="reference does not exist"):
        store.resolve_ref("missing")

    refs = tmp_path / "ai/refs"
    refs.mkdir(parents=True)
    (refs / "bad.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="reference is invalid"):
        store.resolve_ref("bad")
    (refs / "bad.json").write_text('{"object_id":1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="reference is invalid"):
        store.resolve_ref("bad")


def test_store_rejects_conflicts_and_non_directory_paths(tmp_path: Path) -> None:
    root = tmp_path / "ai"
    store = AiExchangeStore(root)
    request = build_report_request(example_report())
    request_id = request.pop("request_id")
    store.put("request", request)
    path = store.path("request", request_id)
    path.write_text("conflict", encoding="utf-8")

    with pytest.raises(ValueError, match="conflicts"):
        store.put("request", request)

    bad_root = tmp_path / "bad-root"
    bad_root.write_text("file", encoding="utf-8")
    with pytest.raises(ValueError, match="root"):
        AiExchangeStore(bad_root).put("request", request)

    root = tmp_path / "symlinked-kind"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "response").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="real directory"):
        AiExchangeStore(root).put("response", {"request_id": "a" * 64, "trial": 1})
    assert tuple(outside.iterdir()) == ()

    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        AiExchangeStore(alias / "ai").put("request", request)
    assert not (outside / "ai").exists()


def test_import_rejects_an_unknown_request_and_naive_clock(tmp_path: Path) -> None:
    selected = service(tmp_path)
    prepared = selected.prepare_report("latest", "ja")
    value = json.loads(response(prepared.request_id))
    value["request_id"] = "b" * 64
    prepared.response_path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown request"):
        selected.import_response(prepared.response_path)

    naive = ManualAiService(
        ReportReader(), AiExchangeStore(tmp_path / "naive"), clock=lambda: datetime(2026, 8, 6)
    )
    naive_prepared = naive.prepare_report("latest", "ja")
    naive_prepared.response_path.write_text(response(naive_prepared.request_id), encoding="utf-8")
    with pytest.raises(ValueError, match="UTC offset"):
        naive.import_response(naive_prepared.response_path)


def test_missing_source_report_creates_an_invalid_validation(tmp_path: Path) -> None:
    reports = DisappearingReportReader()
    selected = ManualAiService(
        reports,
        AiExchangeStore(tmp_path),
        clock=lambda: datetime(2026, 8, 6, 12, tzinfo=UTC),
    )
    prepared = selected.prepare_report("latest", "ja")
    prepared.response_path.write_text(response(prepared.request_id), encoding="utf-8")
    reports.available = False

    with pytest.raises(ValueError, match="source report disappeared"):
        selected.import_response(prepared.response_path)

    assert len(tuple((tmp_path / "response/objects").glob("*.json"))) == 1
    validation = json.loads(next((tmp_path / "validation/objects").glob("*.json")).read_text())
    assert validation["status"] == "invalid"
    assert validation["reason"] == "source report disappeared"
