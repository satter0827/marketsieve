from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

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
from marketsieve_agent import FactCatalog, explain
from marketsieve_agent.pipeline import build_prompt

AS_OF = datetime(2026, 8, 3, 6, tzinfo=UTC)


class StubModel:
    provider = "fixture"
    model = "stub"

    def __init__(self, output: str) -> None:
        self.output = output
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.output


class ErrorModel:
    provider = "fixture"
    model = "error"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def invoke(self, prompt: str) -> str:
        del prompt
        raise self.error


def report() -> DecisionReport:
    instrument = Instrument.create(
        symbol="7203",
        mic="XTKS",
        currency="JPY",
        exchange_timezone="Asia/Tokyo",
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
        ("close_below_sma60",),
        "次の終値で傾向を確認する",
        "balanced_medium_term",
        "1.0.0",
        settings,
    )
    portfolio = PortfolioSnapshot(
        AS_OF,
        (Holding(instrument, Decimal("10"), Decimal("2300"), "taxable"),),
        (),
        "fixture",
    )
    return DecisionReport(
        "a" * 64,
        "decision-report/v1",
        MarketSession.JP_CLOSE,
        AS_OF,
        portfolio,
        decision.policy_name,
        decision.policy_version,
        settings,
        (decision,),
        ("FRED系列は未取得",),
    )


def response(*, connection: str = "保存済みの判断根拠を整理します。") -> str:
    return json.dumps(
        {
            "section_order": ["XTKS:7203"],
            "selected_facts": [{"fact_id": "decision.XTKS:7203.action", "emphasis": "context"}],
            "connections": [connection],
        },
        ensure_ascii=False,
    )


def test_explicit_model_selects_facts_but_renderer_owns_values_and_evidence() -> None:
    result = explain(report(), model=StubModel(response()))

    assert result.status == "model"
    assert result.provider == "fixture"
    assert "keep" in result.text
    assert result.report_id == "a" * 64
    assert result.as_document()["schema_version"] == "1.0.0"


def test_catalog_uses_only_static_report_and_excludes_private_portfolio_values() -> None:
    catalog = FactCatalog.from_report(report())
    prompt = build_prompt(catalog, "ja")

    assert catalog.report_id == "a" * 64
    assert "bars-evidence" not in prompt
    assert '"quantity"' not in prompt
    assert "2300" not in prompt
    assert "taxable" not in prompt


@pytest.mark.parametrize(
    ("output", "reason"),
    (("not-json", "invalid_json"), ("{}", "invalid_model_output")),
)
def test_invalid_model_output_uses_template_without_exposing_output(
    output: str, reason: str
) -> None:
    result = explain(report(), model=StubModel(output))

    assert result.status == "template"
    assert result.fallback_reason == reason
    assert output not in result.text


def test_unknown_fact_uses_template() -> None:
    raw = json.loads(response())
    raw["selected_facts"][0]["fact_id"] = "decision.XTKS:7203.unknown"

    result = explain(report(), model=StubModel(json.dumps(raw)))

    assert result.fallback_reason == "invalid_model_output"


@pytest.mark.parametrize(
    "connection", ["価格は二千五百円です。", "Return is five percent.", "推奨します。"]
)
def test_numeric_or_advisory_connections_use_template(connection: str) -> None:
    result = explain(report(), model=StubModel(response(connection=connection)))

    assert result.status == "template"
    assert connection not in result.text


@pytest.mark.parametrize(
    ("error", "reason"),
    ((TimeoutError(), "model_timeout"), (RuntimeError("not exposed"), "model_unavailable")),
)
def test_provider_failures_use_template_without_exception_detail(
    error: Exception, reason: str
) -> None:
    result = explain(report(), model=ErrorModel(error))

    assert result.fallback_reason == reason
    assert "not exposed" not in result.text


def test_catalog_hash_and_result_are_deterministic() -> None:
    first = explain(report(), model=StubModel(response()))
    second = explain(report(), model=StubModel(response()))

    assert first == second


def test_english_template_identifies_unchanged_report_values() -> None:
    result = explain(report(), model=StubModel("invalid"), locale="en")

    assert result.status == "template"
    assert "were not changed by the model" in result.text


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.update({"extra": True}),
        lambda raw: raw.update({"section_order": ["XTKS:7203", "XTKS:7203"]}),
        lambda raw: raw.update({"section_order": ["unknown"]}),
        lambda raw: raw.update({"selected_facts": []}),
        lambda raw: raw.update({"selected_facts": ["decision.XTKS:7203.action"]}),
        lambda raw: raw["selected_facts"].append(raw["selected_facts"][0]),
        lambda raw: raw.update({"section_order": ["report"]}),
        lambda raw: raw.update({"connections": []}),
        lambda raw: raw.update({"connections": ["one", "two"]}),
        lambda raw: raw.update({"connections": [""]}),
    ],
)
def test_invalid_plan_shapes_use_template(mutation: Any) -> None:
    raw = json.loads(response())
    mutation(raw)

    result = explain(report(), model=StubModel(json.dumps(raw)))

    assert result.status == "template"


def test_invalid_report_and_locale_are_rejected_before_model_use() -> None:
    with pytest.raises(TypeError, match="DecisionReport"):
        explain({"report_id": "bad"}, model=StubModel(response()))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="locale"):
        explain(report(), model=StubModel(response()), locale="fr")


def test_report_change_changes_catalog_even_when_report_id_is_invalidly_reused() -> None:
    original = FactCatalog.from_report(report())
    decision = report().decisions[0]
    changed = replace(report(), decisions=(replace(decision, next_action="変更を確認する"),))

    assert FactCatalog.from_report(changed).catalog_hash != original.catalog_hash
