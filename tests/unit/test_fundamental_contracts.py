from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from marketsieve.domain import Instrument
from marketsieve_extension_api import (
    AvailabilityBasis,
    Consolidation,
    CorporateEvent,
    CorporateEventType,
    FactFetchRequest,
    FilingDocument,
    FinancialFact,
    FinancialPeriod,
    ImportedEvents,
    ImportedFinancials,
    Revision,
    SourceConfiguration,
)

INSTRUMENT = Instrument.create(
    symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
)
REQUEST = FactFetchRequest("japan", INSTRUMENT, date(2026, 1, 1), date(2026, 7, 31), {})
PUBLISHED = datetime(2026, 7, 31, 6, tzinfo=UTC)
FILING = FilingDocument(
    "doc-2026",
    "issuer-7203",
    "annual-report",
    PUBLISHED,
    FinancialPeriod.ANNUAL,
    date(2025, 4, 1),
    date(2026, 3, 31),
    "J-GAAP",
    Consolidation.CONSOLIDATED,
    "JPY",
)
FACT = FinancialFact(
    "revenue",
    "Sales",
    None,
    FinancialPeriod.ANNUAL,
    "FY",
    date(2025, 4, 1),
    date(2026, 3, 31),
    PUBLISHED,
    PUBLISHED,
    AvailabilityBasis.PUBLISHED,
    Consolidation.CONSOLIDATED,
    Revision.REPORTED,
    "JPY",
    1,
    Decimal("1000"),
)
EVENT = CorporateEvent(
    CorporateEventType.EARNINGS,
    date(2026, 7, 31),
    date(2026, 7, 31),
    None,
    PUBLISHED,
    AvailabilityBasis.RETRIEVAL,
    (("quarter", "1Q"),),
)


def test_source_and_fetch_request_require_complete_ascending_identity() -> None:
    with pytest.raises(ValueError, match="currency"):
        SourceConfiguration("", "Asia/Tokyo", {})
    with pytest.raises(ValueError, match="ascending"):
        replace(REQUEST, start=date(2026, 8, 1))
    with pytest.raises(ValueError, match="profile"):
        replace(REQUEST, source_profile="")
    with pytest.raises(TypeError, match="strings"):
        SourceConfiguration("JPY", "Asia/Tokyo", {"page_size": 100})  # type: ignore[dict-item]
    with pytest.raises(TypeError, match="Instrument"):
        replace(REQUEST, instrument="7203")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="dates"):
        replace(REQUEST, start=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(TypeError, match="strings"):
        replace(REQUEST, settings={"page_size": 100})  # type: ignore[dict-item]


@pytest.mark.parametrize(
    "change",
    (
        {"concept": ""},
        {"provider_period": ""},
        {"fiscal_period_start": date(2027, 1, 1)},
        {"published_at": datetime(2026, 7, 31)},
        {"scale": 0},
        {"value": Decimal("NaN")},
    ),
)
def test_financial_fact_rejects_ambiguous_or_non_finite_values(
    change: dict[str, Any],
) -> None:
    with pytest.raises((ValueError, TypeError)):
        replace(FACT, **change)


def test_financial_fact_requires_contract_types_and_consistent_availability() -> None:
    with pytest.raises(TypeError, match="date or None"):
        replace(FACT, fiscal_period_start=datetime(2025, 4, 1, tzinfo=UTC))
    with pytest.raises(TypeError, match=r"decimal\.Decimal"):
        replace(FACT, value=1000)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="period and consolidation"):
        replace(FACT, period="annual")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="revision and availability"):
        replace(FACT, revision="reported")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="available_at"):
        replace(FACT, available_at=datetime(2026, 7, 31))
    with pytest.raises(ValueError, match="published_at as available_at"):
        replace(FACT, available_at=datetime(2026, 7, 31, 7, tzinfo=UTC))
    with pytest.raises(TypeError, match="integer"):
        replace(FACT, scale=True)
    with pytest.raises(ValueError, match="filing_id"):
        replace(FACT, filing_id="")


def test_filing_document_preserves_publication_period_and_amendment_identity() -> None:
    amendment = replace(
        FILING,
        filing_id="doc-2026-amended",
        document_type="annual-report-amendment",
        published_at=datetime(2026, 8, 1, 6, tzinfo=UTC),
        amends_filing_id=FILING.filing_id,
    )

    assert FILING.is_known_at(PUBLISHED)
    assert not amendment.is_known_at(PUBLISHED)
    with pytest.raises(ValueError, match="UTC offset"):
        FILING.is_known_at(datetime(2026, 7, 31, 6))
    with pytest.raises(ValueError, match="amend itself"):
        replace(FILING, amends_filing_id=FILING.filing_id)
    with pytest.raises(ValueError, match="ascending"):
        replace(FILING, fiscal_period_start=date(2026, 4, 1))
    with pytest.raises(TypeError, match="FinancialPeriod"):
        replace(FILING, period="annual")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Consolidation"):
        replace(FILING, consolidation="consolidated")  # type: ignore[arg-type]


def test_event_rejects_naive_publication_and_empty_value_identity() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        replace(EVENT, published_at=datetime(2026, 7, 31))
    with pytest.raises(ValueError, match="empty"):
        replace(EVENT, values=(("", "1Q"),))
    with pytest.raises(ValueError, match="unique"):
        replace(EVENT, values=(("quarter", "1Q"), ("quarter", "2Q")))


def test_event_requires_contract_types_and_consistent_availability() -> None:
    with pytest.raises(TypeError, match="dates"):
        replace(EVENT, observation_date=datetime(2026, 7, 31, tzinfo=UTC))
    with pytest.raises(TypeError, match="contract enums"):
        replace(EVENT, event_type="earnings")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="available_at"):
        replace(EVENT, available_at=datetime(2026, 7, 31))
    with pytest.raises(ValueError, match="require published_at"):
        replace(EVENT, availability_basis=AvailabilityBasis.PUBLISHED)
    with pytest.raises(ValueError, match="published_at as available_at"):
        replace(
            EVENT,
            published_at=datetime(2026, 7, 30, tzinfo=UTC),
            availability_basis=AvailabilityBasis.PUBLISHED,
        )


def test_imported_facts_require_evidence_or_explicit_missing_reason() -> None:
    financials = ImportedFinancials(
        REQUEST, "fixture", "v1", "financials", PUBLISHED, (FACT,), "a" * 64
    )
    events = ImportedEvents(REQUEST, "fixture", "v1", "events", PUBLISHED, (EVENT,), "b" * 64)

    assert financials.facts == (FACT,)
    assert events.events == (EVENT,)
    with pytest.raises(ValueError, match="facts, filings, or missing"):
        replace(financials, facts=())
    with pytest.raises(ValueError, match="events or missing"):
        replace(events, events=())
    assert replace(financials, facts=(), missing_reasons=("not_available",)).facts == ()
    assert replace(financials, facts=(), filings=(FILING,)).filings == (FILING,)
    assert replace(events, events=(), missing_reasons=("not_available",)).events == ()
    with pytest.raises(ValueError, match="after retrieval"):
        replace(
            financials,
            facts=(
                replace(
                    FACT,
                    published_at=datetime(2026, 8, 2, tzinfo=UTC),
                    available_at=datetime(2026, 8, 2, tzinfo=UTC),
                ),
            ),
        )
    with pytest.raises(ValueError, match="after retrieval"):
        replace(events, events=(replace(EVENT, available_at=datetime(2026, 8, 2, tzinfo=UTC)),))
    with pytest.raises(ValueError, match="unique"):
        replace(financials, missing_reasons=("missing", "missing"))
    with pytest.raises(ValueError, match="unique"):
        replace(events, missing_reasons=("missing", "missing"))
    with pytest.raises(TypeError, match="FactFetchRequest"):
        replace(financials, request="japan")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="FinancialFact"):
        replace(financials, facts=(EVENT,))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="FactFetchRequest"):
        replace(events, request="japan")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="CorporateEvent"):
        replace(events, events=(FACT,))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique provider observation"):
        replace(financials, facts=(FACT, FACT))
    with pytest.raises(ValueError, match="unique provider observation"):
        replace(events, events=(EVENT, EVENT))


def test_imported_financials_links_facts_to_ordered_filings_and_filters_knowledge() -> None:
    amendment = replace(
        FILING,
        filing_id="doc-2026-amended",
        published_at=datetime(2026, 8, 1, 6, tzinfo=UTC),
        amends_filing_id=FILING.filing_id,
    )
    reported = replace(FACT, filing_id=FILING.filing_id)
    restated = replace(
        FACT,
        value=Decimal("1050"),
        published_at=amendment.published_at,
        available_at=amendment.published_at,
        revision=Revision.RESTATED,
        filing_id=amendment.filing_id,
    )
    imported = ImportedFinancials(
        REQUEST,
        "fixture",
        "v1",
        "financials",
        datetime(2026, 8, 2, tzinfo=UTC),
        (reported, restated),
        "a" * 64,
        (),
        (FILING, amendment),
    )

    assert imported.filings_known_at(PUBLISHED) == (FILING,)
    assert imported.facts_known_at(PUBLISHED) == (reported,)
    with pytest.raises(ValueError, match="stable publication order"):
        replace(imported, filings=(amendment, FILING))
    with pytest.raises(ValueError, match="unique filing"):
        replace(imported, filings=(FILING, FILING))
    with pytest.raises(ValueError, match="included filing"):
        replace(imported, facts=(replace(reported, filing_id="missing"),))
    with pytest.raises(ValueError, match="publication must match"):
        replace(
            imported,
            facts=(
                replace(
                    reported,
                    published_at=amendment.published_at,
                    available_at=amendment.published_at,
                ),
            ),
        )
    with pytest.raises(ValueError, match="after retrieval"):
        replace(imported, retrieved_at=PUBLISHED)
    with pytest.raises(ValueError, match="UTC offset"):
        imported.facts_known_at(datetime(2026, 7, 31, 6))


@pytest.mark.parametrize("kind", ("financial", "event"))
def test_imported_facts_reject_naive_retrieval_and_empty_identity(kind: str) -> None:
    imported: ImportedFinancials | ImportedEvents
    if kind == "financial":
        imported = ImportedFinancials(
            REQUEST, "fixture", "v1", "financials", PUBLISHED, (FACT,), "a" * 64
        )
    else:
        imported = ImportedEvents(REQUEST, "fixture", "v1", "events", PUBLISHED, (EVENT,), "b" * 64)
    with pytest.raises(ValueError, match="identity"):
        replace(imported, source_name="")
    with pytest.raises(ValueError, match="SHA-256"):
        replace(imported, response_hash="not-a-digest")
    with pytest.raises(ValueError, match="UTC offset"):
        replace(imported, retrieved_at=datetime(2026, 7, 31))
