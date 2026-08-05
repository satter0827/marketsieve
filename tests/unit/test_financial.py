from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from marketsieve import FinancialObservation, analyze_financial_history


def observation(
    concept: str,
    value: str,
    *,
    start: date = date(2025, 4, 1),
    end: date = date(2026, 3, 31),
    available_at: datetime = datetime(2026, 5, 1, tzinfo=UTC),
    evidence_id: str | None = None,
    revision: str = "reported",
    standard: str | None = "IFRS",
    consolidation: str = "consolidated",
    currency: str = "JPY",
) -> FinancialObservation:
    return FinancialObservation(
        concept,
        Decimal(value),
        1,
        "annual",
        start,
        end,
        standard,
        consolidation,
        revision,
        currency,
        available_at,
        evidence_id or f"{end}:{concept}:{available_at.isoformat()}",
    )


def complete_period(
    *, start: date, end: date, available_at: datetime, suffix: str, multiplier: str
) -> tuple[FinancialObservation, ...]:
    factor = Decimal(multiplier)
    values = {
        "revenue": Decimal("100") * factor,
        "operating_income": Decimal("20") * factor,
        "net_income": Decimal("10") * factor,
        "eps": Decimal("5") * factor,
        "operating_cash_flow": Decimal("18") * factor,
        "capital_expenditure": Decimal("-3") * factor,
        "assets": Decimal("200") * factor,
        "equity": Decimal("100") * factor,
        "interest_bearing_debt": Decimal("25") * factor,
    }
    return tuple(
        observation(
            concept,
            str(value),
            start=start,
            end=end,
            available_at=available_at,
            evidence_id=f"{suffix}:{concept}",
        )
        for concept, value in values.items()
    )


def test_calculates_compatible_company_history_with_stable_identity() -> None:
    previous = complete_period(
        start=date(2024, 4, 1),
        end=date(2025, 3, 31),
        available_at=datetime(2025, 5, 1, tzinfo=UTC),
        suffix="previous",
        multiplier="1",
    )
    current = complete_period(
        start=date(2025, 4, 1),
        end=date(2026, 3, 31),
        available_at=datetime(2026, 5, 1, tzinfo=UTC),
        suffix="current",
        multiplier="1.2",
    )

    first = analyze_financial_history((*current, *previous), datetime(2026, 6, 1, tzinfo=UTC))
    second = analyze_financial_history((*previous, *reversed(current)), first.knowledge_at)

    assert first == second
    assert [period.fiscal_period_end for period in first.periods] == [
        date(2026, 3, 31),
        date(2025, 3, 31),
    ]
    assert first.metric("free_cash_flow").canonical_value == "18"  # type: ignore[union-attr]
    assert first.metric("revenue_growth").canonical_value == "0.2"  # type: ignore[union-attr]
    assert first.metric("eps_growth").canonical_value == "0.2"  # type: ignore[union-attr]
    assert first.metric("operating_margin").canonical_value == "0.2"  # type: ignore[union-attr]
    assert first.missing_reasons == ()


def test_knowledge_time_excludes_future_disclosure_and_selects_known_restatement() -> None:
    previous = observation(
        "revenue",
        "80",
        start=date(2024, 4, 1),
        end=date(2025, 3, 31),
        available_at=datetime(2025, 5, 1, tzinfo=UTC),
        evidence_id="previous",
    )
    reported = observation("revenue", "100", evidence_id="reported")
    restated = observation(
        "revenue",
        "120",
        available_at=datetime(2026, 7, 1, tzinfo=UTC),
        evidence_id="restated",
        revision="restated",
    )

    before = analyze_financial_history(
        (previous, reported, restated), datetime(2026, 6, 1, tzinfo=UTC)
    )
    after = analyze_financial_history(
        (previous, reported, restated), datetime(2026, 8, 1, tzinfo=UTC)
    )

    assert before.metric("revenue_growth").canonical_value == "0.25"  # type: ignore[union-attr]
    assert after.metric("revenue_growth").canonical_value == "0.5"  # type: ignore[union-attr]
    assert dict(before.periods[0].values)["revenue"] == Decimal("100")
    assert dict(after.periods[0].values)["revenue"] == Decimal("120")
    assert before.evidence_id != after.evidence_id


def test_incompatible_or_incomplete_periods_remain_explicitly_missing() -> None:
    facts = (
        observation("revenue", "100"),
        observation(
            "revenue",
            "80",
            start=date(2024, 4, 1),
            end=date(2025, 3, 31),
            available_at=datetime(2025, 5, 1, tzinfo=UTC),
            standard="J-GAAP",
        ),
        replace(observation("eps", "5"), consolidation="unknown"),
    )

    report = analyze_financial_history(facts, datetime(2026, 6, 1, tzinfo=UTC))

    assert report.metric("revenue_growth") is None
    assert "revenue_growth_inputs_not_compatible_or_missing" in report.missing_reasons
    assert len(report.periods) == 1


def test_conflicting_same_time_observations_are_rejected() -> None:
    first = observation("revenue", "100", evidence_id="a")
    second = observation("revenue", "101", evidence_id="b")

    with pytest.raises(ValueError, match="conflicting"):
        analyze_financial_history((first, second), datetime(2026, 6, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"concept": "unsupported"}, "concept"),
        ({"value": Decimal("NaN")}, "finite"),
        ({"scale": 0}, "scale"),
        ({"period": "monthly"}, "period"),
        ({"consolidation": "both"}, "consolidation"),
        ({"revision": "corrected"}, "revision"),
        ({"available_at": datetime(2026, 5, 1)}, "UTC offset"),
    ],
)
def test_observation_rejects_invalid_semantics(change: dict[str, object], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        replace(observation("revenue", "100"), **cast(Any, change))


def test_analysis_requires_aware_knowledge_time_and_reports_no_eligible_period() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        analyze_financial_history((), datetime(2026, 6, 1))

    report = analyze_financial_history(
        (replace(observation("revenue", "100"), accounting_standard=None),),
        datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert report.periods == ()
    assert report.missing_reasons == ("compatible_annual_financial_period_not_available",)
