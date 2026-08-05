from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from marketsieve import (
    BalancedCandidateScreen,
    DecisionAction,
    DecisionConfidence,
    DecisionEvidence,
    EvidenceDirection,
    InstrumentUniverse,
    ScreenCandidate,
    ScreenPolicy,
)
from marketsieve.decision import InstrumentDecision
from marketsieve.domain import Instrument


def instrument(symbol: str) -> Instrument:
    return Instrument.create(
        symbol=symbol,
        mic="XNAS",
        currency="USD",
        exchange_timezone="America/New_York",
    )


def decision(
    symbol: str,
    action: DecisionAction,
    confidence: DecisionConfidence,
    supporting: int,
) -> InstrumentDecision:
    evidence = tuple(
        DecisionEvidence(f"support_{index}", EvidenceDirection.SUPPORTING, "1", None)
        for index in range(supporting)
    )
    return InstrumentDecision(
        instrument(symbol),
        False,
        action,
        confidence,
        evidence,
        None,
        None,
        None,
        None,
        (),
        (),
        ("trend_change",),
        "review_candidate",
        "balanced_medium_term",
        "1.0.0",
        (),
    )


def universe(*symbols: str) -> InstrumentUniverse:
    return InstrumentUniverse.create(
        market="us",
        source_profile="offline-us",
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        instruments=tuple(instrument(symbol) for symbol in symbols),
        source_ids=("a" * 64,),
    )


def test_screen_uses_transparent_stable_order_and_content_identity() -> None:
    source = universe("CCC", "AAA", "BBB", "DDD")
    values = (
        decision("BBB", DecisionAction.BUY_CANDIDATE, DecisionConfidence.HIGH, 1),
        decision("AAA", DecisionAction.BUY_CANDIDATE, DecisionConfidence.HIGH, 2),
        decision("CCC", DecisionAction.WAIT_FOR_PULLBACK, DecisionConfidence.HIGH, 5),
        decision("DDD", DecisionAction.PASS, DecisionConfidence.HIGH, 5),
    )
    policy = BalancedCandidateScreen()

    first = policy.screen(source, values, as_of=source.as_of)
    second = policy.screen(source, tuple(reversed(values)), as_of=source.as_of)

    assert isinstance(policy, ScreenPolicy)
    assert first == second
    assert [item.decision.instrument.symbol for item in first.candidates] == ["AAA", "BBB", "CCC"]
    assert first.eligible_count == 3
    assert not hasattr(first.candidates[0], "score")


def test_screen_reports_processing_and_display_bounds() -> None:
    source = universe("AAA", "BBB", "CCC")
    report = BalancedCandidateScreen().screen(
        source,
        (decision("AAA", DecisionAction.BUY_CANDIDATE, DecisionConfidence.HIGH, 1),),
        as_of=source.as_of,
        processing_limit=2,
        display_limit=1,
    )

    assert report.processed_count == 1
    assert report.diagnostics == ("processing_limit_reached:2",)

    with pytest.raises(ValueError, match="processed universe"):
        BalancedCandidateScreen().screen(
            source,
            (decision("CCC", DecisionAction.BUY_CANDIDATE, DecisionConfidence.HIGH, 1),),
            as_of=source.as_of,
            processing_limit=2,
        )


def test_screen_reports_display_bound_and_rejects_invalid_invocations() -> None:
    source = universe("AAA", "BBB")
    values = (
        decision("AAA", DecisionAction.BUY_CANDIDATE, DecisionConfidence.HIGH, 1),
        decision("BBB", DecisionAction.BUY_CANDIDATE, DecisionConfidence.HIGH, 1),
    )

    report = BalancedCandidateScreen().screen(source, values, as_of=source.as_of, display_limit=1)

    assert report.eligible_count == 2
    assert report.diagnostics == ("display_limit_reached:1",)
    with pytest.raises(ValueError, match="limits"):
        BalancedCandidateScreen().screen(source, values, as_of=source.as_of, processing_limit=0)
    with pytest.raises(ValueError, match="UTC offset"):
        BalancedCandidateScreen().screen(
            source, values, as_of=datetime(2026, 8, 1), processing_limit=2
        )
    with pytest.raises(ValueError, match="unique"):
        BalancedCandidateScreen().screen(
            source, (values[0], values[0]), as_of=source.as_of, processing_limit=2
        )


def test_universe_rejects_invalid_identity_and_content() -> None:
    source = universe("AAA")

    with pytest.raises(ValueError, match="market"):
        InstrumentUniverse.create(
            market="eu",
            source_profile="offline",
            as_of=source.as_of,
            instruments=(instrument("AAA"),),
            source_ids=("a" * 64,),
        )
    with pytest.raises(ValueError, match="at least one"):
        InstrumentUniverse.create(
            market="us",
            source_profile="offline",
            as_of=source.as_of,
            instruments=(),
            source_ids=("a" * 64,),
        )
    with pytest.raises(ValueError, match="source IDs"):
        InstrumentUniverse.create(
            market="us",
            source_profile="offline",
            as_of=source.as_of,
            instruments=(instrument("AAA"),),
            source_ids=("",),
        )


def test_content_addressed_models_reject_tampering() -> None:
    source = universe("AAA")
    report = BalancedCandidateScreen().screen(
        source,
        (decision("AAA", DecisionAction.BUY_CANDIDATE, DecisionConfidence.HIGH, 1),),
        as_of=source.as_of,
    )

    with pytest.raises(ValueError, match="semantic content"):
        replace(source, diagnostics=("changed",))
    with pytest.raises(ValueError, match="semantic content"):
        replace(report, diagnostics=("changed",))


def test_candidate_and_report_reject_inconsistent_manual_construction() -> None:
    source = universe("AAA", "BBB")
    first = decision("AAA", DecisionAction.BUY_CANDIDATE, DecisionConfidence.HIGH, 1)
    second = decision("BBB", DecisionAction.WAIT_FOR_PULLBACK, DecisionConfidence.LOW, 0)
    report = BalancedCandidateScreen().screen(source, (first, second), as_of=source.as_of)

    with pytest.raises(ValueError, match="not eligible"):
        ScreenCandidate(decision("AAA", DecisionAction.PASS, DecisionConfidence.LOW, 0), 0)
    with pytest.raises(ValueError, match="must not be held"):
        ScreenCandidate(replace(first, held=True, action=DecisionAction.KEEP), 1)
    with pytest.raises(ValueError, match="does not match"):
        ScreenCandidate(first, 0)

    invalid = (
        ({"report_id": "bad"}, "report ID"),
        ({"schema_version": "v2"}, "schema"),
        ({"universe_id": "bad"}, "universe ID"),
        ({"as_of": datetime(2026, 8, 1)}, "UTC offset"),
        ({"policy_name": ""}, "policy identity"),
        ({"processed_count": -1}, "counts"),
        ({"eligible_count": 0}, "visible candidates"),
        ({"candidates": tuple(reversed(report.candidates))}, "stable policy order"),
        ({"diagnostics": ("same", "same")}, "diagnostics"),
    )
    for changes, message in invalid:
        with pytest.raises(ValueError, match=message):
            replace(report, **changes)
