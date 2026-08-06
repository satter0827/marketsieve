from __future__ import annotations

import hashlib
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
from marketsieve_ai import (
    FactCatalog,
    build_report_request,
    decode_response,
    parse_report_response,
    render,
)

AS_OF = datetime(2026, 8, 3, 6, tzinfo=UTC)


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


def test_request_is_deterministic_and_excludes_private_portfolio_values() -> None:
    first = build_report_request(example_report())
    second = build_report_request(example_report())
    payload = json.dumps(first, ensure_ascii=False, sort_keys=True)

    assert first == second
    assert first["request_id"] == second["request_id"]
    assert first["interaction"] == {
        "mode": "temporary_chat",
        "project": False,
        "web_search": False,
        "external_tools": False,
        "custom_instructions": "disabled",
    }
    assert '"quantity"' not in payload
    assert "2300" not in payload
    assert "taxable" not in payload
    assert "bars-evidence" not in payload

    with pytest.raises(ValueError, match="locale"):
        build_report_request(example_report(), "fr")
    with pytest.raises(TypeError, match="DecisionReport"):
        FactCatalog.from_report(object())  # type: ignore[arg-type]

    private_threshold = DecisionEvidence(
        "concentrated", EvidenceDirection.OPPOSING, None, "0.173829", ()
    )
    source_report = example_report()
    private_decision = replace(source_report.decisions[0], evidence=(private_threshold,))
    private_report = replace(source_report, decisions=(private_decision,))
    assert "0.173829" not in json.dumps(build_report_request(private_report))


def test_weekly_candidate_decisions_use_distinct_facts_and_sections() -> None:
    report = example_report()
    candidate_instrument = Instrument.create(
        symbol="AAPL", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
    )
    candidate = replace(
        report.decisions[0],
        instrument=candidate_instrument,
        held=False,
        action=DecisionAction.BUY_CANDIDATE,
        next_action="define entry and invalidation",
    )
    weekly = replace(
        report,
        session=MarketSession.WEEKLY,
        input_report_ids=("b" * 64, "c" * 64),
        candidate_decisions=(candidate,),
        screening_report_ids=("d" * 64,),
    )

    catalog = FactCatalog.from_report(weekly)
    facts = {fact.fact_id: fact for fact in catalog.facts}

    assert "decision.XTKS:7203.action" in facts
    assert facts["candidate.XNAS:AAPL.action"].value == "buy_candidate"
    assert facts["candidate.XNAS:AAPL.action"].section == "candidate:XNAS:AAPL"
    assert "candidate:XNAS:AAPL" in catalog.sections


@pytest.mark.parametrize("fenced", [False, True])
def test_response_accepts_json_or_one_bare_json_fence(fenced: bool) -> None:
    report = example_report()
    request = build_report_request(report)
    raw = response(request["request_id"])
    if fenced:
        raw = f"```json\n{raw}\n```"

    plan = parse_report_response(raw, request, report)
    text = render(FactCatalog.from_report(report), plan, "ja")

    assert "keep" in text
    assert "判断値は保存済みレポートから引用" in text


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"extra": True}),
        lambda value: value.update({"request_id": "b" * 64}),
        lambda value: value.update({"section_order": ["unknown"]}),
        lambda value: value.update({"selected_fact_ids": []}),
        lambda value: value.update({"selected_fact_ids": ["unknown.fact"]}),
        lambda value: value["selected_fact_ids"].append(value["selected_fact_ids"][0]),
        lambda value: value.update({"connections": "invalid"}),
    ],
)
def test_invalid_response_is_rejected(mutation: Any) -> None:
    report = example_report()
    request = build_report_request(report)
    value = json.loads(response(request["request_id"]))
    mutation(value)

    with pytest.raises(ValueError, match="AI response"):
        parse_report_response(json.dumps(value), request, report)


@pytest.mark.parametrize("relation", ["recommends", "価格は二千五百円です。"])
def test_unrecognized_or_self_referential_connection_is_rejected(relation: str) -> None:
    report = example_report()
    request = build_report_request(report)

    with pytest.raises(ValueError, match="invalid connection"):
        value = json.loads(response(request["request_id"]))
        fact_id = value["selected_fact_ids"][0]
        value["connections"] = [
            {"from_fact_id": fact_id, "relation": relation, "to_fact_id": fact_id}
        ]
        parse_report_response(json.dumps(value), request, report)


def test_request_tampering_is_rejected_against_the_immutable_report() -> None:
    report = example_report()
    request = build_report_request(report)
    request["catalog"]["facts"][0]["value"] = "changed"

    with pytest.raises(ValueError, match="does not match"):
        parse_report_response(response(request["request_id"]), request, report)


def test_self_consistent_prompt_metadata_tampering_is_rejected() -> None:
    report = example_report()
    request = build_report_request(report)
    request["interaction"]["web_search"] = True
    semantic = {key: value for key, value in request.items() if key != "request_id"}
    request["request_id"] = hashlib.sha256(
        json.dumps(semantic, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()

    with pytest.raises(ValueError, match="does not match"):
        parse_report_response(response(request["request_id"]), request, report)


def test_request_for_another_immutable_report_is_rejected() -> None:
    report = example_report()
    request = build_report_request(report)
    other_report = replace(report, report_id="b" * 64)

    with pytest.raises(ValueError, match="does not match"):
        parse_report_response(response(request["request_id"]), request, other_report)


@pytest.mark.parametrize(
    "raw,error",
    [
        (b"\xff", "UTF-8"),
        ("[]", "one JSON object"),
        (" " * 65_537, "size limit"),
        (object(), "bytes or text"),
    ],
)
def test_response_decoder_rejects_invalid_transport(raw: object, error: str) -> None:
    with pytest.raises((TypeError, ValueError), match=error):
        decode_response(raw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"section_order": ["XTKS:7203", "XTKS:7203"]}),
        lambda value: value.update({"selected_fact_ids": "invalid"}),
        lambda value: value.update({"selected_fact_ids": ["report.session"]}),
        lambda value: value.update({"connections": "invalid"}),
        lambda value: value.update({"connections": [{}]}),
    ],
)
def test_response_rejects_additional_structural_failures(mutation: Any) -> None:
    report = example_report()
    request = build_report_request(report)
    value = json.loads(response(request["request_id"]))
    mutation(value)

    with pytest.raises(ValueError, match=r"AI response|selected_fact_ids"):
        parse_report_response(json.dumps(value), request, report)


def test_structured_relationship_is_rendered_without_ai_free_text() -> None:
    report = example_report()
    request = build_report_request(report, "en")
    value = json.loads(response(request["request_id"]))
    value["selected_fact_ids"].append("decision.XTKS:7203.confidence")
    value["connections"] = [
        {
            "from_fact_id": "decision.XTKS:7203.confidence",
            "relation": "supports",
            "to_fact_id": "decision.XTKS:7203.action",
        }
    ]

    plan = parse_report_response(json.dumps(value), request, report)
    rendered = render(FactCatalog.from_report(report), plan, "en")

    assert "confidence supports decision.XTKS:7203.action" in rendered
    with pytest.raises(ValueError, match="locale"):
        render(FactCatalog.from_report(report), plan, "fr")


def test_render_preserves_all_local_evidence_ids() -> None:
    report = example_report()
    evidence = replace(report.decisions[0].evidence[0], evidence_ids=("first", "second"))
    decision = replace(report.decisions[0], evidence=(evidence,))
    report = replace(report, decisions=(decision,))
    request = build_report_request(report)
    value = json.loads(response(request["request_id"]))
    value["selected_fact_ids"] = ["decision.XTKS:7203.evidence.0"]

    plan = parse_report_response(json.dumps(value), request, report)
    rendered = render(FactCatalog.from_report(report), plan, "ja")

    assert "evidence=first,second" in rendered
    assert "first" not in json.dumps(request, ensure_ascii=False)
    assert "second" not in json.dumps(request, ensure_ascii=False)


def test_response_rejects_text_surrounding_a_json_code_fence() -> None:
    report = example_report()
    request = build_report_request(report)
    raw = f"Here is the answer:\n```json\n{response(request['request_id'])}\n```"

    with pytest.raises(json.JSONDecodeError):
        parse_report_response(raw, request, report)
