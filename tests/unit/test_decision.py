from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from marketsieve.data.daily import DailyBar
from marketsieve.decision import (
    AnalysisContext,
    BalancedMediumTermPolicy,
    DecisionAction,
    DecisionConfidence,
    DecisionEvidence,
    DecisionPolicy,
    DecisionReport,
    EvidenceDirection,
    MarketSession,
)
from marketsieve.portfolio import (
    Holding,
    PersonalInvestmentContext,
    PortfolioSnapshot,
    WatchItem,
)
from marketsieve.synthetic.daily import JP_INSTRUMENT, US_INSTRUMENT, fixture_bars


def trend_bars(*, bullish: bool, count: int = 252) -> tuple[DailyBar, ...]:
    pattern = (
        (Decimal("-1"), Decimal("1"), Decimal("-1"))
        if not bullish
        else (Decimal("1"), Decimal("-1"), Decimal("1"))
    )
    current = Decimal("400" if not bullish else "100")
    closes: list[str] = []
    for index in range(count):
        current += pattern[(index + 1) % len(pattern)]
        closes.append(str(current))
    return fixture_bars(JP_INSTRUMENT, tuple(closes), dataset=f"trend-{bullish}-{count}")


def holding() -> Holding:
    return Holding(JP_INSTRUMENT, Decimal("10"), Decimal("120"), "taxable")


def context(
    *,
    bullish: bool = True,
    held: bool = False,
    count: int = 252,
    position_weight: str | None = None,
    fundamentals: tuple[str | None, str | None, str | None] = ("0.1", "0.1", "1"),
    earnings_days: int | None = None,
) -> AnalysisContext:
    bars = trend_bars(bullish=bullish, count=count)
    as_of = bars[-1].available_at
    values = tuple(Decimal(value) if value is not None else None for value in fundamentals)
    return AnalysisContext(
        JP_INSTRUMENT,
        as_of,
        bars,
        holding=holding() if held else None,
        position_weight=Decimal(position_weight) if position_weight is not None else None,
        next_earnings_date=(as_of.date() + timedelta(days=earnings_days))
        if earnings_days is not None
        else None,
        revenue_growth=values[0],
        eps_growth=values[1],
        free_cash_flow=values[2],
        input_evidence_ids=("fundamentals-v1",),
    )


@pytest.mark.parametrize(
    ("analysis", "policy", "expected"),
    [
        (context(), BalancedMediumTermPolicy(), DecisionAction.BUY_CANDIDATE),
        (
            context(earnings_days=7),
            BalancedMediumTermPolicy(),
            DecisionAction.WAIT_FOR_EARNINGS,
        ),
        (
            context(),
            BalancedMediumTermPolicy(rsi_overbought=Decimal("60")),
            DecisionAction.WAIT_FOR_PULLBACK,
        ),
        (context(bullish=False), BalancedMediumTermPolicy(), DecisionAction.PASS),
        (context(held=True), BalancedMediumTermPolicy(), DecisionAction.KEEP),
        (
            context(held=True),
            BalancedMediumTermPolicy(atr_close_warning=Decimal("0.001")),
            DecisionAction.WATCH,
        ),
        (
            context(held=True, position_weight="0.21"),
            BalancedMediumTermPolicy(),
            DecisionAction.REDUCE_REVIEW,
        ),
        (
            context(
                bullish=False,
                held=True,
                fundamentals=("-0.1", "-0.2", "1"),
            ),
            BalancedMediumTermPolicy(),
            DecisionAction.SELL_REVIEW,
        ),
    ],
)
def test_balanced_policy_covers_the_fixed_decision_vocabulary(
    analysis: AnalysisContext,
    policy: BalancedMediumTermPolicy,
    expected: DecisionAction,
) -> None:
    decision = policy.evaluate(analysis)

    assert decision.action is expected
    assert decision.policy_name == "balanced_medium_term"
    assert isinstance(policy, DecisionPolicy)
    assert dict(decision.policy_settings)["maximum_position_weight"] == "0.2"


def test_insufficient_essential_history_is_indeterminate() -> None:
    decision = BalancedMediumTermPolicy().evaluate(
        context(count=59, fundamentals=(None, None, None))
    )

    assert decision.action is DecisionAction.INDETERMINATE
    assert decision.confidence is DecisionConfidence.LOW
    assert decision.next_action == "refresh_price_history"
    assert all(item.direction is EvidenceDirection.LIMITATION for item in decision.evidence)


def test_optional_inputs_change_confidence_without_changing_the_calculation() -> None:
    high = BalancedMediumTermPolicy().evaluate(context())
    medium = BalancedMediumTermPolicy().evaluate(context(fundamentals=(None, None, None)))
    low = BalancedMediumTermPolicy().evaluate(context(count=60, fundamentals=(None, None, None)))

    assert high.confidence is DecisionConfidence.HIGH
    assert medium.confidence is DecisionConfidence.MEDIUM
    assert low.confidence is DecisionConfidence.LOW
    assert any(item.code == "missing_maximum_drawdown" for item in low.evidence)


def test_portfolio_snapshot_is_brokerage_neutral_and_unambiguous() -> None:
    observed = trend_bars(bullish=True, count=1)[0].available_at
    snapshot = PortfolioSnapshot(
        observed,
        (holding(),),
        (WatchItem(US_INSTRUMENT),),
        "rakuten_csv",
    )

    assert snapshot.normalized_as_of.utcoffset() == timedelta(0)
    assert snapshot.source == "rakuten_csv"

    with pytest.raises(ValueError, match="also be watch"):
        PortfolioSnapshot(observed, (holding(),), (WatchItem(JP_INSTRUMENT),), "csv")
    with pytest.raises(ValueError, match="unique"):
        PortfolioSnapshot(observed, (holding(), holding()), (), "csv")


def test_invalid_personal_and_analysis_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="exceed one"):
        PersonalInvestmentContext(Decimal("1.1"))
    with pytest.raises(ValueError, match="requires a holding"):
        AnalysisContext(
            JP_INSTRUMENT,
            trend_bars(bullish=True, count=60)[-1].available_at,
            trend_bars(bullish=True, count=60),
            position_weight=Decimal("0.1"),
        )
    with pytest.raises(ValueError, match="RSI oversold"):
        BalancedMediumTermPolicy(rsi_oversold=Decimal("80"))


def test_neutral_and_financial_only_branches_are_explicit() -> None:
    bars = fixture_bars(JP_INSTRUMENT, ("100",) * 252, dataset="flat")
    neutral = AnalysisContext(JP_INSTRUMENT, bars[-1].available_at, bars)

    assert BalancedMediumTermPolicy().evaluate(neutral).action is DecisionAction.PASS
    assert (
        BalancedMediumTermPolicy(rsi_oversold=Decimal("50")).evaluate(neutral).action
        is DecisionAction.WAIT_FOR_PULLBACK
    )
    assert (
        BalancedMediumTermPolicy()
        .evaluate(context(held=True, fundamentals=("-0.1", "-0.2", "1")))
        .action
        is DecisionAction.REDUCE_REVIEW
    )
    deep = BalancedMediumTermPolicy(drawdown_warning=Decimal("0")).evaluate(context(held=True))
    assert deep.action is DecisionAction.WATCH
    assert next(item for item in deep.evidence if item.code == "maximum_drawdown").direction is (
        EvidenceDirection.OPPOSING
    )


def test_decision_report_accepts_one_canonical_semantic_model() -> None:
    analysis = context(held=True)
    decision = BalancedMediumTermPolicy().evaluate(analysis)
    snapshot = PortfolioSnapshot(analysis.as_of, (holding(),), (), "rakuten_csv")
    report = DecisionReport(
        "a" * 64,
        "decision-report/v2",
        MarketSession.JP_CLOSE,
        analysis.as_of,
        snapshot,
        decision.policy_name,
        decision.policy_version,
        decision.policy_settings,
        (decision,),
        ("valuation_missing",),
        "b" * 64,
    )

    assert report.decisions == (decision,)
    assert report.previous_report_id == "b" * 64


def test_decision_report_rejects_time_portfolio_and_policy_mismatches() -> None:
    analysis = context(held=True)
    decision = BalancedMediumTermPolicy().evaluate(analysis)
    snapshot = PortfolioSnapshot(analysis.as_of, (holding(),), (), "csv")
    report = DecisionReport(
        "a" * 64,
        "decision-report/v2",
        MarketSession.JP_CLOSE,
        analysis.as_of,
        snapshot,
        decision.policy_name,
        decision.policy_version,
        decision.policy_settings,
        (decision,),
    )

    with pytest.raises(ValueError, match="predate"):
        replace(report, as_of=analysis.as_of - timedelta(seconds=1))
    with pytest.raises(ValueError, match="portfolio instruments"):
        replace(
            report,
            portfolio=PortfolioSnapshot(analysis.as_of, (), (WatchItem(US_INSTRUMENT),), "csv"),
        )
    with pytest.raises(ValueError, match="report policy"):
        replace(report, decisions=(replace(decision, policy_version="2.0.0"),))


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"report_id": "bad"}, "report ID"),
        ({"schema_version": "decision-report/v3"}, "schema"),
        ({"session": "jp_close"}, "session"),
        ({"as_of": datetime(2026, 1, 1)}, "UTC offset"),
        ({"portfolio": object()}, "portfolio"),
        ({"policy_name": ""}, "policy identity"),
        ({"decisions": (object(),)}, "decisions"),
        ({"policy_settings": (("z", "1"), ("a", "2"))}, "settings"),
        ({"diagnostics": ("",)}, "diagnostics"),
        ({"previous_report_id": "g" * 64}, "previous report"),
        ({"input_report_ids": ("c" * 64,)}, "daily reports"),
    ],
)
def test_decision_report_rejects_noncanonical_values(
    changes: dict[str, object], error: str
) -> None:
    analysis = context(held=True)
    decision = BalancedMediumTermPolicy().evaluate(analysis)
    report = DecisionReport(
        "a" * 64,
        "decision-report/v2",
        MarketSession.JP_CLOSE,
        analysis.as_of,
        PortfolioSnapshot(analysis.as_of, (holding(),), (), "csv"),
        decision.policy_name,
        decision.policy_version,
        decision.policy_settings,
        (decision,),
    )

    with pytest.raises((TypeError, ValueError), match=error):
        replace(report, **changes)  # type: ignore[arg-type]


def test_weekly_report_requires_two_canonical_input_ids() -> None:
    analysis = context(held=True)
    decision = BalancedMediumTermPolicy().evaluate(analysis)
    report = DecisionReport(
        "a" * 64,
        "decision-report/v2",
        MarketSession.JP_CLOSE,
        analysis.as_of,
        PortfolioSnapshot(analysis.as_of, (holding(),), (), "csv"),
        decision.policy_name,
        decision.policy_version,
        decision.policy_settings,
        (decision,),
    )

    with pytest.raises(ValueError, match="exactly two"):
        replace(report, session=MarketSession.WEEKLY)
    with pytest.raises(ValueError, match="unique sorted"):
        replace(
            report,
            session=MarketSession.WEEKLY,
            input_report_ids=("d" * 64, "c" * 64),
        )


@pytest.mark.parametrize(
    "evidence",
    [
        ("", EvidenceDirection.SUPPORTING, None, None, ()),
        ("ok", "supporting", None, None, ()),
        ("ok", EvidenceDirection.SUPPORTING, "", None, ()),
        ("ok", EvidenceDirection.SUPPORTING, None, "", ()),
        ("ok", EvidenceDirection.SUPPORTING, None, None, ("same", "same")),
    ],
)
def test_decision_evidence_rejects_ambiguous_values(evidence: tuple[object, ...]) -> None:
    with pytest.raises((TypeError, ValueError)):
        DecisionEvidence(*evidence)  # type: ignore[arg-type]


def test_instrument_decision_rejects_a_vocabulary_for_the_wrong_state() -> None:
    decision = BalancedMediumTermPolicy().evaluate(context())

    with pytest.raises(ValueError, match="holding state"):
        replace(decision, held=True)
    with pytest.raises(TypeError, match="confidence"):
        replace(decision, confidence="high")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="settings"):
        replace(decision, policy_settings=(("z", "1"), ("a", "2")))


def test_portfolio_value_validation_rejects_private_or_invalid_shapes() -> None:
    observed = trend_bars(bullish=True, count=1)[0].available_at

    with pytest.raises(TypeError, match="Decimal"):
        Holding(JP_INSTRUMENT, 1, Decimal("1"), "taxable")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive"):
        Holding(JP_INSTRUMENT, Decimal("0"), Decimal("1"), "taxable")
    with pytest.raises(ValueError, match="account type"):
        Holding(JP_INSTRUMENT, Decimal("1"), Decimal("1"), " ")
    with pytest.raises(TypeError, match="instrument"):
        WatchItem("7203")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="UTC offset"):
        PortfolioSnapshot(datetime(2026, 1, 1), (), (), "csv")
    with pytest.raises(ValueError, match="source"):
        PortfolioSnapshot(observed, (), (), "")
    with pytest.raises(ValueError, match="unique"):
        PortfolioSnapshot(observed, (), (WatchItem(US_INSTRUMENT), WatchItem(US_INSTRUMENT)), "csv")
    with pytest.raises(ValueError, match="sorted"):
        PortfolioSnapshot(
            observed,
            (
                holding(),
                Holding(US_INSTRUMENT, Decimal("1"), Decimal("100"), "taxable"),
            ),
            (),
            "csv",
        )


def test_analysis_context_rejects_time_leaks_and_noncanonical_optional_values() -> None:
    analysis = context()

    with pytest.raises(ValueError, match="available at as_of"):
        replace(analysis, as_of=analysis.bars[-1].available_at - timedelta(days=2))
    with pytest.raises(ValueError, match="finite Decimal"):
        replace(analysis, revenue_growth=Decimal("NaN"))
    with pytest.raises(ValueError, match="valuation"):
        replace(analysis, valuation=(("pe", "20"), ("pe", "21")))
    with pytest.raises(ValueError, match="evidence IDs"):
        replace(analysis, input_evidence_ids=("same", "same"))


def test_policy_settings_reject_values_outside_the_public_contract() -> None:
    with pytest.raises(TypeError, match="integer"):
        BalancedMediumTermPolicy(earnings_wait_days=True)
    with pytest.raises(ValueError, match="non-negative"):
        BalancedMediumTermPolicy(earnings_wait_days=-1)
    with pytest.raises(ValueError, match="between"):
        BalancedMediumTermPolicy(atr_close_warning=Decimal("2"))
