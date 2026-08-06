from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from marketsieve import (
    AnalysisContext,
    BalancedMediumTermPolicy,
    DecisionAction,
    DecisionConfidence,
    Holding,
    MarketSession,
    PortfolioSnapshot,
)
from marketsieve.synthetic.daily import JP_INSTRUMENT, US_INSTRUMENT, fixture_bars
from marketsieve_cli.adapters.analysis import (
    ANALYSIS_SCHEMA,
    README_TEXT,
    AnalysisWorkspace,
    _validate_analysis_document,
    render_analysis,
)
from marketsieve_cli.adapters.portfolios import PortfolioStore
from marketsieve_cli.adapters.reports import ReportStore, _decision_document, create_report
from marketsieve_cli.adapters.screening import ScreeningStore
from marketsieve_cli.adapters.watchlists import WatchlistStore
from marketsieve_extension_api import ImportedPortfolioSnapshot


def test_analysis_workspace_is_deterministic_historical_and_private(tmp_path: Path) -> None:
    observed = datetime(2026, 8, 6, 10, tzinfo=UTC)
    holding = Holding(
        JP_INSTRUMENT,
        Decimal("12345.6789"),
        Decimal("98765.4321"),
        "private-account-type",
    )
    portfolio = PortfolioSnapshot(observed, (holding,), (), "fixture-broker")
    portfolios = PortfolioStore(tmp_path / "portfolio")
    portfolio_id = portfolios.put(
        ImportedPortfolioSnapshot(
            portfolio,
            "fixture",
            "1.0.0",
            "anonymous-holdings",
            "a" * 64,
            ("account owner at /Users/private/broker.csv",),
        )
    )
    watchlists = WatchlistStore(tmp_path / "watchlists")
    watchlists.add(US_INSTRUMENT, as_of=observed, screen_report_id="b" * 64)

    bars = fixture_bars(
        JP_INSTRUMENT,
        tuple(str(100 + index) for index in range(252)),
        dataset="analysis-workspace",
    )
    analysis_as_of = max(observed, bars[-1].available_at)
    first_decision = BalancedMediumTermPolicy().evaluate(
        AnalysisContext(JP_INSTRUMENT, analysis_as_of, bars, holding=holding)
    )
    first = create_report(
        MarketSession.JP_CLOSE,
        analysis_as_of,
        portfolio,
        (first_decision,),
        diagnostics=("financials_missing",),
    )
    reports = ReportStore(tmp_path / "reports")
    reports.put(first)
    changed_decision = replace(
        first_decision,
        action=DecisionAction.WATCH,
        confidence=DecisionConfidence.LOW,
        next_action="research_latest_primary_sources",
    )
    second = create_report(
        MarketSession.JP_CLOSE,
        analysis_as_of + timedelta(days=1),
        portfolio,
        (changed_decision,),
        previous_report_id=first.report_id,
    )
    reports.put(second)
    root = tmp_path / "analysis"
    workspace = AnalysisWorkspace(
        root,
        portfolios,
        watchlists,
        reports,
        ScreeningStore(tmp_path / "screening"),
    )

    first_context = workspace.build()
    first_bytes = (root / "context.json").read_bytes()
    second_context = workspace.build()

    assert first_context == second_context
    assert (root / "context.json").read_bytes() == first_bytes
    assert first_context["portfolio"]["object_id"] == portfolio_id
    assert first_context["previous_deltas"][0]["changes"] == [
        {
            "instrument": "XTKS:7203",
            "previous": [first_decision.action.value, first_decision.confidence.value],
            "current": [DecisionAction.WATCH.value, DecisionConfidence.LOW.value],
        }
    ]
    assert first_context["watchlist"]["items"][0]["key"] == "XNAS:MSFT"
    expected_input_ids = {
        portfolio_id,
        first.report_id,
        second.report_id,
        "b" * 64,
        *(
            evidence_id
            for evidence in changed_decision.evidence
            for evidence_id in evidence.evidence_ids
        ),
    }
    assert expected_input_ids <= set(first_context["input_artifact_ids"])
    context_text = first_bytes.decode("utf-8")
    for forbidden in (
        "quantity",
        "average_acquisition_price",
        "account_type",
        "12345.6789",
        "98765.4321",
        "private-account-type",
        "/Users/",
        "account owner",
    ):
        assert forbidden not in context_text
    assert "portfolio_import_diagnostics_omitted:1" in first_context["diagnostics"]
    verified, markdown = workspace.show()
    assert verified == first_context
    assert "XTKS:7203" in markdown
    assert "research_latest_primary_sources" in markdown


def test_analysis_delta_includes_weekly_candidate_changes(tmp_path: Path) -> None:
    bars = fixture_bars(
        US_INSTRUMENT,
        tuple(str(100 + index) for index in range(252)),
        dataset="weekly-candidate-delta",
    )
    observed = bars[-1].available_at
    holding = Holding(JP_INSTRUMENT, Decimal("1"), Decimal("100"), "private")
    portfolio = PortfolioSnapshot(observed, (holding,), (), "fixture")
    held_decision = BalancedMediumTermPolicy().evaluate(
        AnalysisContext(
            JP_INSTRUMENT,
            observed,
            fixture_bars(
                JP_INSTRUMENT,
                tuple(str(100 + index) for index in range(252)),
                dataset="weekly-held-delta",
            ),
            holding=holding,
        )
    )
    candidate = replace(
        BalancedMediumTermPolicy().evaluate(AnalysisContext(US_INSTRUMENT, observed, bars)),
        action=DecisionAction.BUY_CANDIDATE,
        confidence=DecisionConfidence.MEDIUM,
    )
    first = create_report(
        MarketSession.WEEKLY,
        observed,
        portfolio,
        (held_decision,),
        input_report_ids=("b" * 64, "c" * 64),
        candidate_decisions=(candidate,),
        screening_report_ids=("a" * 64,),
    )
    changed_candidate = replace(
        candidate,
        action=DecisionAction.WAIT_FOR_PULLBACK,
        confidence=DecisionConfidence.LOW,
    )
    second = create_report(
        MarketSession.WEEKLY,
        observed + timedelta(days=1),
        portfolio,
        (held_decision,),
        previous_report_id=first.report_id,
        input_report_ids=("b" * 64, "c" * 64),
        candidate_decisions=(changed_candidate,),
        screening_report_ids=("a" * 64,),
    )
    portfolios = PortfolioStore(tmp_path / "portfolio")
    portfolios.put(ImportedPortfolioSnapshot(portfolio, "fixture", "1", "fixture", "f" * 64))
    reports = ReportStore(tmp_path / "reports")
    reports.put(first)
    reports.put(second)
    context = AnalysisWorkspace(
        tmp_path / "analysis",
        portfolios,
        WatchlistStore(tmp_path / "watchlists"),
        reports,
        ScreeningStore(tmp_path / "screening"),
    ).build()

    assert context["previous_deltas"][0]["changes"] == [
        {
            "instrument": "XNAS:MSFT",
            "previous": [candidate.action.value, candidate.confidence.value],
            "current": [DecisionAction.WAIT_FOR_PULLBACK.value, DecisionConfidence.LOW.value],
        }
    ]
    assert "a" * 64 in context["input_artifact_ids"]


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def _minimal_context() -> dict[str, object]:
    semantic = {
        "schema": ANALYSIS_SCHEMA,
        "as_of": "2026-08-06T10:00:00+00:00",
        "portfolio": {
            "object_id": "a" * 64,
            "as_of": "2026-08-06T10:00:00+00:00",
            "source": "fixture",
            "source_name": "fixture",
            "dataset": "fixture",
            "diagnostics": [],
            "holdings": [],
        },
        "watchlist": {"latest_id": None, "items": [], "history": []},
        "decision_reports": [],
        "screening_reports": [],
        "previous_deltas": [],
        "input_artifact_ids": ["a" * 64],
        "missing": [],
        "diagnostics": [],
        "constraints": [],
    }
    return {"context_id": hashlib.sha256(_canonical_json(semantic)).hexdigest(), **semantic}


def _complete_context() -> dict[str, Any]:
    bars = fixture_bars(
        JP_INSTRUMENT,
        tuple(str(100 + index) for index in range(252)),
        dataset="analysis-validation",
    )
    decision = _decision_document(
        BalancedMediumTermPolicy().evaluate(
            AnalysisContext(JP_INSTRUMENT, bars[-1].available_at, bars)
        )
    )
    watchlist_item = {
        "key": "XNAS:MSFT",
        "instrument": {
            "mic": "XNAS",
            "symbol": "MSFT",
            "currency": "USD",
            "timezone": "America/New_York",
            "type": "equity",
        },
        "source_screen_report_id": "b" * 64,
    }
    revision = {
        "watchlist_id": "c" * 64,
        "schema": "watchlist-result/v1",
        "as_of": "2026-08-06T10:00:00+00:00",
        "previous_watchlist_id": None,
        "change": {"operation": "add", "instrument": "XNAS:MSFT"},
        "items": [watchlist_item],
    }
    document = _minimal_context()
    document["watchlist"] = {
        "latest_id": revision["watchlist_id"],
        "items": revision["items"],
        "history": [revision],
    }
    document["decision_reports"] = [
        {
            "report_id": "d" * 64,
            "session": "jp_close",
            "as_of": "2026-08-06T10:00:00+00:00",
            "policy": {"name": "balanced_medium_term", "version": "1.0.0", "settings": {}},
            "decisions": [decision],
            "candidate_decisions": [],
            "previous_report_id": "e" * 64,
            "input_report_ids": ["f" * 64],
            "screening_report_ids": ["b" * 64],
            "diagnostics": ["financials_missing"],
        }
    ]
    document["screening_reports"] = [
        {
            "schema": "screening-report/v1",
            "report_id": "b" * 64,
            "universe_id": "1" * 64,
            "as_of": "2026-08-06T10:00:00+00:00",
            "policy": {"name": "balanced_candidate_screen", "version": "1.0.0"},
            "processed_count": 1,
            "eligible_count": 1,
            "candidates": [{"decision": decision, "supporting_evidence_count": 1}],
            "diagnostics": ["bounded_refresh"],
        }
    ]
    document["previous_deltas"] = [
        {
            "session": "jp_close",
            "current_report_id": "d" * 64,
            "previous_report_id": "e" * 64,
            "changes": [
                {
                    "instrument": "XTKS:7203",
                    "previous": ["watch", "low"],
                    "current": [decision["action"], decision["confidence"]],
                }
            ],
        }
    ]
    semantic = {key: value for key, value in document.items() if key != "context_id"}
    document["context_id"] = hashlib.sha256(_canonical_json(semantic)).hexdigest()
    return document


def test_analysis_show_rejects_missing_and_mutated_workspace(tmp_path: Path) -> None:
    root = tmp_path / "analysis"
    workspace = AnalysisWorkspace(root, None, None, None, None)
    with pytest.raises(LookupError, match="analysis build"):
        workspace.show()

    root.mkdir()
    document = _minimal_context()
    (root / "context.json").write_bytes(_canonical_json(document))
    (root / "analysis.md").write_text(render_analysis(document), encoding="utf-8")
    (root / "README.md").write_text(README_TEXT, encoding="utf-8")
    assert workspace.show()[0] == document

    (root / "analysis.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Markdown does not match"):
        workspace.show()
    (root / "analysis.md").write_text(render_analysis(document), encoding="utf-8")
    (root / "README.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="README is invalid"):
        workspace.show()
    (root / "README.md").write_text(README_TEXT, encoding="utf-8")
    changed = dict(document)
    changed["as_of"] = "2026-08-07T10:00:00+00:00"
    (root / "context.json").write_bytes(_canonical_json(changed))
    with pytest.raises(ValueError, match="ID does not match"):
        workspace.show()

    (root / "context.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="context is invalid"):
        workspace.show()
    unsupported = dict(document)
    unsupported["schema"] = "unknown/v1"
    (root / "context.json").write_bytes(_canonical_json(unsupported))
    with pytest.raises(ValueError, match="schema is unsupported"):
        workspace.show()
    (root / "context.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="not canonical"):
        workspace.show()

    extra = {**document, "unexpected": "accepted only when validation is missing"}
    semantic = {key: value for key, value in extra.items() if key != "context_id"}
    extra["context_id"] = hashlib.sha256(_canonical_json(semantic)).hexdigest()
    (root / "context.json").write_bytes(_canonical_json(extra))
    with pytest.raises(ValueError, match="structure is invalid"):
        workspace.show()


def test_analysis_render_covers_candidates_changes_and_diagnostics() -> None:
    document = _minimal_context()
    document["screening_reports"] = [
        {
            "candidates": [
                {
                    "decision": {
                        "instrument": {"mic": "XNAS", "symbol": "MSFT"},
                        "action": "buy_candidate",
                        "confidence": "medium",
                    }
                }
            ]
        }
    ]
    document["previous_deltas"] = [
        {"changes": [{"instrument": "XNAS:MSFT", "previous": None, "current": ["watch", "low"]}]}
    ]
    document["missing"] = ["decision_report:weekly"]
    document["diagnostics"] = ["rate_limit"]

    markdown = render_analysis(document)

    assert "XNAS:MSFT: buy_candidate / medium" in markdown
    assert "None -> ['watch', 'low']" in markdown
    assert "decision_report:weekly" in markdown
    assert "rate_limit" in markdown


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(context_id="bad"), "SHA-256"),
        (lambda value: value.update(as_of="2026-08-06T10:00:00"), "analysis as_of"),
        (lambda value: value.update(portfolio=[]), "portfolio structure"),
        (lambda value: value["portfolio"].update(extra=True), "portfolio structure"),
        (lambda value: value["portfolio"].update(object_id="bad"), "portfolio object ID"),
        (lambda value: value["portfolio"].update(source=1), "portfolio identity"),
        (lambda value: value["portfolio"].update(diagnostics={}), "portfolio diagnostics"),
        (lambda value: value["portfolio"].update(holdings={}), "portfolio holdings"),
        (lambda value: value["portfolio"].update(holdings=[{}]), "instrument is invalid"),
        (lambda value: value.update(watchlist=[]), "watchlist is invalid"),
        (lambda value: value.update(decision_reports={}), "decision reports are invalid"),
        (lambda value: value.update(screening_reports=[None]), "screening report is invalid"),
        (lambda value: value.update(input_artifact_ids={}), "artifact IDs are invalid"),
        (lambda value: value.update(input_artifact_ids=["bad"]), "artifact ID must"),
        (
            lambda value: value.update(input_artifact_ids=["a" * 64, "a" * 64]),
            "artifact IDs must be unique",
        ),
        (lambda value: value.update(missing=[1]), "analysis missing are invalid"),
        (lambda value: value.update(diagnostics=["same", "same"]), "diagnostics must be unique"),
    ),
)
def test_analysis_show_enforces_declared_schema_constraints(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    root = tmp_path / "analysis"
    root.mkdir()
    document = _minimal_context()
    mutation(document)
    if document.get("context_id") != "bad":
        semantic = {key: value for key, value in document.items() if key != "context_id"}
        document["context_id"] = hashlib.sha256(_canonical_json(semantic)).hexdigest()
    (root / "context.json").write_bytes(_canonical_json(document))
    (root / "analysis.md").write_text("unused", encoding="utf-8")
    (root / "README.md").write_text(README_TEXT, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        AnalysisWorkspace(root, None, None, None, None).show()


def test_analysis_recursive_validation_accepts_complete_context() -> None:
    _validate_analysis_document(_complete_context())


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    (
        (("watchlist", "latest_id"), "bad", "watchlist latest ID"),
        (("watchlist", "history"), {}, "watchlist history"),
        (("watchlist", "history", 0, "schema"), "unknown/v1", "revision schema"),
        (("watchlist", "history", 0, "change", "operation"), "replace", "change"),
        (("watchlist", "history", 0, "items", 0, "key"), 1, "item key"),
        (
            ("watchlist", "history", 0, "items", 0, "instrument", "type"),
            "fund",
            "watchlist instrument",
        ),
        (("decision_reports", 0, "session"), "unknown", "report session"),
        (("decision_reports", 0, "policy", "settings"), [], "report policy"),
        (("decision_reports", 0, "decisions"), {}, "decisions are invalid"),
        (("decision_reports", 0, "decisions", 0), {}, "decision is invalid"),
        (("decision_reports", 0, "input_report_ids"), {}, "input_report_ids are invalid"),
        (("screening_reports", 0, "schema"), "unknown/v1", "report schema"),
        (("screening_reports", 0, "policy", "name"), 1, "screening policy"),
        (("screening_reports", 0, "processed_count"), True, "screening counts"),
        (("screening_reports", 0, "candidates"), {}, "screening candidates"),
        (
            ("screening_reports", 0, "candidates", 0, "supporting_evidence_count"),
            -1,
            "evidence count",
        ),
        (("previous_deltas", 0, "session"), "unknown", "delta session"),
        (("previous_deltas", 0, "changes"), {}, "delta changes"),
        (("previous_deltas", 0, "changes", 0, "instrument"), 1, "delta instrument"),
        (("previous_deltas", 0, "changes", 0, "current"), ["watch"], "delta state"),
        (("as_of",), 1, "analysis as_of"),
        (("as_of",), "not-a-date", "analysis as_of"),
    ),
)
def test_analysis_recursive_validation_rejects_nested_mutation(
    path: tuple[str | int, ...],
    replacement: object,
    message: str,
) -> None:
    document = deepcopy(_complete_context())
    target: Any = document
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = replacement

    with pytest.raises(ValueError, match=message):
        _validate_analysis_document(document)
