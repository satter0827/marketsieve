from __future__ import annotations

import json
import os
from dataclasses import replace
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
    WatchItem,
)
from marketsieve.domain import Instrument
from marketsieve_cli.adapters.explanations import ExplanationStore
from marketsieve_cli.adapters.reports import (
    ReportStore,
    create_report,
    render_markdown,
    report_document,
)

ROOT = Path(__file__).parents[2]
AS_OF = datetime(2026, 8, 5, 22, tzinfo=UTC)
POLICY_SETTINGS = (("rsi_overbought", "70"),)


def _instrument(symbol: str, mic: str, currency: str, timezone: str) -> Instrument:
    return Instrument.create(
        symbol=symbol,
        mic=mic,
        currency=currency,
        exchange_timezone=timezone,
    )


def _decision(
    instrument: Instrument,
    *,
    held: bool,
    action: DecisionAction,
) -> InstrumentDecision:
    return InstrumentDecision(
        instrument,
        held,
        action,
        DecisionConfidence.MEDIUM,
        (
            DecisionEvidence(
                "trend_above_sma60",
                EvidenceDirection.SUPPORTING,
                "105",
                "100",
                ("bars-object",),
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
        POLICY_SETTINGS,
    )


def _report(
    *,
    action: DecisionAction = DecisionAction.KEEP,
    session: MarketSession = MarketSession.JP_CLOSE,
    previous_report_id: str | None = None,
) -> DecisionReport:
    toyota = _instrument("7203", "XTKS", "JPY", "Asia/Tokyo")
    apple = _instrument("AAPL", "XNAS", "USD", "America/New_York")
    portfolio = PortfolioSnapshot(
        AS_OF,
        (Holding(toyota, Decimal("10"), Decimal("2500"), "taxable"),),
        (WatchItem(apple),),
        "fixture",
    )
    held_action = action
    unheld_action = (
        DecisionAction.INDETERMINATE
        if action is DecisionAction.INDETERMINATE
        else DecisionAction.BUY_CANDIDATE
    )
    return create_report(
        session,
        AS_OF,
        portfolio,
        (
            _decision(apple, held=False, action=unheld_action),
            _decision(toyota, held=True, action=held_action),
        ),
        diagnostics=("FRED系列は未取得",),
        previous_report_id=previous_report_id,
        input_report_ids=("1" * 64, "2" * 64) if session is MarketSession.WEEKLY else (),
    )


def test_report_identity_json_and_markdown_are_deterministic() -> None:
    first = _report()
    second = _report()

    assert first == second
    assert report_document(first) == report_document(second)
    assert render_markdown(first) == render_markdown(second)
    assert len(first.report_id) == 64


def test_report_identity_normalizes_equivalent_decimal_representations() -> None:
    first = _report()
    holding = first.portfolio.holdings[0]
    portfolio = replace(
        first.portfolio,
        holdings=(
            replace(
                holding,
                quantity=Decimal("10.00"),
                average_acquisition_price=Decimal("2.500E+3"),
            ),
        ),
    )
    decisions = tuple(replace(item, revenue_growth=Decimal("0.0500")) for item in first.decisions)

    equivalent = create_report(
        first.session,
        first.as_of,
        portfolio,
        decisions,
        diagnostics=first.diagnostics,
    )

    assert equivalent.report_id == first.report_id
    assert report_document(equivalent) == report_document(first)


def test_report_document_matches_published_schema() -> None:
    schema = json.loads(
        (ROOT / "schemas/decision-report/v1/schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        report_document(_report())
    )


def test_report_store_writes_authority_projection_and_latest_reference(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports")
    report = _report()

    assert store.put(report) == report
    assert store.put(report) == report
    assert store.list() == (report,)
    assert store.latest(MarketSession.JP_CLOSE) == report
    assert store.markdown(report.report_id) == render_markdown(report)
    assert (tmp_path / "reports/objects" / f"{report.report_id}.json").is_file()
    assert (tmp_path / "reports/rendered" / f"{report.report_id}.md").is_file()
    reference = json.loads((tmp_path / "reports/refs/jp-latest.json").read_text())
    assert reference == {"report_id": report.report_id}
    assert store.resolve(report.report_id) == report
    assert store.resolve("latest") == report


def test_latest_resolution_uses_as_of_then_stable_identity(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports")
    first = store.put(_report())
    later = store.put(
        create_report(
            MarketSession.US_CLOSE,
            AS_OF.replace(hour=23),
            first.portfolio,
            first.decisions,
            diagnostics=first.diagnostics,
        )
    )

    assert store.resolve("latest") == later


def test_all_indeterminate_report_is_retained_without_advancing_latest(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports")
    usable = _report()
    indeterminate = _report(
        action=DecisionAction.INDETERMINATE,
        previous_report_id=usable.report_id,
    )

    store.put(usable)
    store.put(indeterminate)

    assert {item.report_id for item in store.list()} == {
        usable.report_id,
        indeterminate.report_id,
    }
    assert store.latest(MarketSession.JP_CLOSE) == usable


def test_all_indeterminate_first_report_does_not_create_latest(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports")
    report = _report(action=DecisionAction.INDETERMINATE)

    store.put(report)

    with pytest.raises(LookupError, match="latest report"):
        store.latest(MarketSession.JP_CLOSE)


def test_failed_latest_replace_preserves_previous_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ReportStore(tmp_path / "reports")
    previous = store.put(_report())
    following = _report(previous_report_id=previous.report_id)
    real_replace = os.replace

    def fail_latest_replace(source: Path, destination: Path) -> None:
        if Path(destination).parent.name == "refs":
            raise OSError("injected latest failure")
        real_replace(source, destination)

    monkeypatch.setattr("marketsieve_cli.adapters.reports.os.replace", fail_latest_replace)

    with pytest.raises(OSError, match="injected latest failure"):
        store.put(following)
    assert store.latest(MarketSession.JP_CLOSE) == previous


@pytest.mark.parametrize("artifact", ["json", "markdown"])
def test_report_store_detects_artifact_mutation(tmp_path: Path, artifact: str) -> None:
    store = ReportStore(tmp_path / "reports")
    report = store.put(_report())
    if artifact == "json":
        path = tmp_path / "reports/objects" / f"{report.report_id}.json"
        path.write_bytes(path.read_bytes().replace(b'"source":"fixture"', b'"source":"changed"'))
        with pytest.raises(ValueError, match="canonical"):
            store.show(report.report_id)
    else:
        path = tmp_path / "reports/rendered" / f"{report.report_id}.md"
        path.write_text("changed\n", encoding="utf-8")
        with pytest.raises(ValueError, match="canonical JSON"):
            store.markdown(report.report_id)


def test_report_store_rejects_invalid_ids_and_references(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports")
    report = store.put(_report())

    with pytest.raises(ValueError, match="SHA-256"):
        store.show("../outside")
    reference = tmp_path / "reports/refs/jp-latest.json"
    reference.write_text(json.dumps({"unexpected": report.report_id}), encoding="utf-8")
    with pytest.raises(ValueError, match="reference"):
        store.latest(MarketSession.JP_CLOSE)


def test_report_store_rejects_conflicting_immutable_content(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports")
    report = _report()
    store.put(report)
    path = tmp_path / "reports/rendered" / f"{report.report_id}.md"
    path.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="immutable"):
        store.put(report)


def test_report_store_rejects_symlinked_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "reports"
    root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="real directory"):
        ReportStore(root).put(_report())


def test_report_id_covers_diagnostics_and_previous_report() -> None:
    report = _report()

    changed_diagnostics = create_report(
        report.session,
        report.as_of,
        report.portfolio,
        report.decisions,
        diagnostics=("別の制約",),
    )
    changed_previous = create_report(
        report.session,
        report.as_of,
        report.portfolio,
        report.decisions,
        diagnostics=report.diagnostics,
        previous_report_id="a" * 64,
    )

    assert len({report.report_id, changed_diagnostics.report_id, changed_previous.report_id}) == 3


def test_weekly_report_id_covers_exact_input_reports() -> None:
    report = _report(session=MarketSession.WEEKLY)
    changed = create_report(
        report.session,
        report.as_of,
        report.portfolio,
        report.decisions,
        diagnostics=report.diagnostics,
        input_report_ids=("1" * 64, "3" * 64),
    )

    assert changed.report_id != report.report_id


def test_markdown_has_stable_conclusion_first_sections() -> None:
    markdown = render_markdown(_report(session=MarketSession.WEEKLY))

    assert markdown.startswith("# 週末作戦会議\n")
    assert "判断: 買い候補" in markdown
    assert "確信度: 中" in markdown
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings == [
        "## 1. 今日の結論",
        "## 2. 今日見るべきもの",
        "## 3. 前回からの変化",
        "## 4. 変化なし",
        "## 5. 次の一手",
        "## 6. データ上の制約",
        "## 7. 詳細と根拠",
    ]
    assert "新規 →" in markdown


def test_markdown_projects_real_decision_changes_and_unchanged_items() -> None:
    previous = _report()
    current = _report(
        action=DecisionAction.WATCH,
        previous_report_id=previous.report_id,
    )

    markdown = render_markdown(current, previous)

    assert "XTKS:7203: 保有継続 (中) → 警戒 (中)" in markdown
    unchanged = markdown.split("## 4. 変化なし", maxsplit=1)[1].split("## 5. 次の一手", maxsplit=1)[
        0
    ]
    assert "XNAS:AAPL: 買い候補" in unchanged
    assert "XTKS:7203" not in unchanged


def test_change_projection_requires_the_exact_previous_report() -> None:
    previous = _report()
    current = _report(previous_report_id=previous.report_id)

    with pytest.raises(ValueError, match="exact previous"):
        render_markdown(current)
    with pytest.raises(ValueError, match="first report"):
        render_markdown(previous, previous)


def test_report_document_rejects_an_incorrect_identity() -> None:
    report = _report()

    with pytest.raises(ValueError, match="report ID"):
        report_document(replace(report, report_id="a" * 64))


def test_explanation_store_is_content_addressed_separate_and_tamper_evident(
    tmp_path: Path,
) -> None:
    report = _report()
    reports = ReportStore(tmp_path / "reports")
    reports.put(report)
    store = ExplanationStore(tmp_path / "explanations")
    value = {
        "schema_version": "1.0.0",
        "operation": "explain",
        "status": "model",
        "provider": "lmstudio",
        "model": "local-model",
        "prompt_version": "decision-report-selection-v1",
        "report_id": report.report_id,
        "catalog_hash": "b" * 64,
        "selected_fact_ids": ["report.session"],
        "fallback_reason": None,
        "text": "保存済みレポートの説明",
    }

    first = store.put(value)
    second = store.put(value)

    assert first == second
    assert store.show(first["explanation_id"]) == first
    assert reports.show(report.report_id) == report
    path = tmp_path / "explanations/objects" / f"{first['explanation_id']}.json"
    path.write_bytes(path.read_bytes().replace("説明".encode(), "変更".encode()))
    with pytest.raises(ValueError, match="canonical"):
        store.show(first["explanation_id"])

    with pytest.raises(ValueError, match="reserved"):
        store.put({**value, "schema": "changed"})
