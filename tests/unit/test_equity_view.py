from __future__ import annotations

from datetime import UTC, datetime

from marketsieve_cli.application.equity import comparison_document, financial_section


def financial_fact(concept: str, value: str, start: str, end: str) -> dict[str, object]:
    return {
        "concept": concept,
        "provider_fact_name": concept,
        "accounting_standard": "IFRS",
        "period": "annual",
        "fiscal_period_start": start,
        "fiscal_period_end": end,
        "consolidation": "consolidated",
        "revision": "reported",
        "currency": "JPY",
        "scale": 1,
        "value": value,
        "available_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
        "published_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
        "filing_id": f"{end}:{concept}",
        "provenance": {"source": "fixture"},
    }


def test_financial_ratios_require_compatible_periods_and_keep_missing_reasons() -> None:
    current = [
        financial_fact("revenue", "120", "2025-04-01", "2026-03-31"),
        financial_fact("operating_income", "24", "2025-04-01", "2026-03-31"),
        financial_fact("net_income", "12", "2025-04-01", "2026-03-31"),
        financial_fact("eps", "6", "2025-04-01", "2026-03-31"),
        financial_fact("operating_cash_flow", "20", "2025-04-01", "2026-03-31"),
        financial_fact("capital_expenditure", "-5", "2025-04-01", "2026-03-31"),
        financial_fact("assets", "200", "2025-04-01", "2026-03-31"),
        financial_fact("equity", "100", "2025-04-01", "2026-03-31"),
        financial_fact("interest_bearing_debt", "25", "2025-04-01", "2026-03-31"),
    ]
    previous = [
        financial_fact("revenue", "100", "2024-04-01", "2025-03-31"),
        financial_fact("eps", "5", "2024-04-01", "2025-03-31"),
    ]
    section = financial_section(
        {
            "status": "available",
            "as_of": "2026-07-31T06:00:00+00:00",
            "completeness": "1",
            "values": {"facts": [*current, *previous]},
            "warnings": [],
            "missing_reasons": [],
            "provenance": [],
            "evidence_id": "a" * 64,
        }
    )

    derived = section["values"]["derived"]
    assert derived["free_cash_flow"]["value"] == "15"
    assert derived["revenue_growth"]["value"] == "0.2"
    assert derived["operating_margin"]["value"] == "0.2"
    assert derived["debt_to_equity"]["value"] == "0.25"
    assert section["values"]["history"][0]["fiscal_period_end"] == "2026-03-31"
    assert section["status"] == "available"


def test_financial_section_excludes_facts_after_explicit_knowledge_time() -> None:
    known = financial_fact("revenue", "100", "2025-04-01", "2026-03-31")
    future = {
        **financial_fact("eps", "5", "2025-04-01", "2026-03-31"),
        "available_at": datetime(2026, 8, 2, tzinfo=UTC).isoformat(),
    }

    section = financial_section(
        {
            "status": "available",
            "as_of": datetime(2026, 8, 2, tzinfo=UTC).isoformat(),
            "completeness": "1",
            "values": {"facts": [known, future]},
            "warnings": [],
            "missing_reasons": [],
            "provenance": [],
            "evidence_id": "a" * 64,
        },
        knowledge_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert [fact["concept"] for fact in section["values"]["facts"]] == ["revenue"]
    assert "eps" not in section["values"]["history"][0]["values"]


def test_comparison_marks_currency_and_period_mismatches_without_ranking() -> None:
    def view(symbol: str, currency: str, period_end: str) -> dict[str, object]:
        empty_indicator = {"status": "insufficient_history", "values": {}}
        return {
            "instrument": {"mic": "XTKS", "symbol": symbol, "currency": currency},
            "source_profile": "fixture",
            "sections": {
                "price": {
                    "as_of": "2026-08-01T00:00:00+00:00",
                    "values": {"close": "100", "adjustment": "raw"},
                },
                "technical": {
                    "values": {
                        "rsi": empty_indicator,
                        "period_return": empty_indicator,
                        "maximum_drawdown": empty_indicator,
                    }
                },
                "valuation": {"values": {}},
                "financial": {
                    "values": {
                        "derived": {
                            "roe": {
                                "value": "0.1",
                                "currency": None,
                                "period_end": period_end,
                                "accounting_standard": "IFRS",
                                "consolidation": "consolidated",
                                "revision": "reported",
                            }
                        }
                    }
                },
            },
        }

    document = comparison_document(
        (view("7203", "JPY", "2026-03-31"), view("6758", "USD", "2025-03-31"))
    )

    close = next(item for item in document["metrics"] if item["metric"] == "close")
    roe = next(item for item in document["metrics"] if item["metric"] == "roe")
    assert close["comparable"] is False
    assert roe["comparable"] is False
    assert document["warnings"] == [
        "absolute financial amounts are not ranked or currency-converted"
    ]
