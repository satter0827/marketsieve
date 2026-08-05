from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.request import Request

import pytest

from marketsieve.domain import Instrument
from marketsieve_extension_api import (
    FactFetchRequest,
    FinancialFetcher,
    FinancialPeriod,
    Revision,
    SourceConfiguration,
)
from marketsieve_source_sec import SecSource
from marketsieve_source_sec import source as sec_module
from marketsieve_source_sec.source import HttpResponse, _NoRedirect

CIK = "0000320193"
USER_AGENT = "MarketSieve maintainer@example.com"


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        self.calls.append((url, dict(headers), timeout))
        return self.responses.pop(0)


def response(value: object, status: int = 200) -> HttpResponse:
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return HttpResponse(status, body)


def submission_table(
    *,
    accessions: list[str] | None = None,
    filing_dates: list[str] | None = None,
    report_dates: list[str] | None = None,
    accepted: list[str] | None = None,
    forms: list[str] | None = None,
) -> dict[str, list[str]]:
    return {
        "accessionNumber": (
            ["0000320193-26-000001", "0000320193-26-000002"] if accessions is None else accessions
        ),
        "filingDate": ["2026-07-30", "2026-07-31"] if filing_dates is None else filing_dates,
        "reportDate": ["2026-06-30", "2026-06-30"] if report_dates is None else report_dates,
        "acceptanceDateTime": (
            ["2026-07-30T20:00:00Z", "2026-07-31T20:00:00Z"] if accepted is None else accepted
        ),
        "form": ["10-Q", "10-Q/A"] if forms is None else forms,
    }


def submissions(
    table: dict[str, list[str]] | None = None,
    *,
    files: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {"cik": 320193, "filings": {"recent": table or submission_table(), "files": files or []}}


def fact_row(
    *,
    accession: str = "0000320193-26-000001",
    value: str = "1000",
    form: str = "10-Q",
    start: str | None = "2026-04-01",
    end: str = "2026-06-30",
    fp: str = "Q2",
) -> dict[str, object]:
    result: dict[str, object] = {
        "end": end,
        "val": value,
        "accn": accession,
        "fy": 2026,
        "fp": fp,
        "form": form,
        "filed": "2026-07-30",
    }
    if start is not None:
        result["start"] = start
    return result


def companyfacts(
    rows: list[dict[str, object]] | None = None, *, include_assets: bool = True
) -> dict[str, object]:
    concepts: dict[str, object] = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {"USD": rows or [fact_row()]}
        }
    }
    if include_assets:
        concepts["Assets"] = {"units": {"USD": [fact_row(start=None, value="5000")]}}
    return {
        "cik": 320193,
        "entityName": "Fixture Inc.",
        "facts": {"us-gaap": concepts},
    }


def request(settings: dict[str, str] | None = None) -> FactFetchRequest:
    instrument = Instrument.create(
        symbol="AAPL", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
    )
    return FactFetchRequest(
        "sec-us",
        instrument,
        date(2026, 7, 1),
        date(2026, 7, 31),
        settings or {"cik": CIK},
    )


def source(
    responses: list[HttpResponse],
    *,
    environ: Mapping[str, str] | None = None,
    clock: datetime | None = None,
) -> SecSource:
    return SecSource(
        transport=FakeTransport(responses),
        environ={sec_module.USER_AGENT_ENV: USER_AGENT} if environ is None else environ,
        clock=lambda: clock or datetime(2026, 8, 1, tzinfo=UTC),
        sleeper=lambda _: None,
    )


def test_fetches_filings_and_current_period_facts_with_exact_publication_time() -> None:
    document = companyfacts([fact_row(), fact_row(value="900", end="2025-06-30")])
    transport = FakeTransport([response(submissions()), response(document)])
    delays: list[float] = []
    provider = SecSource(
        transport=transport,
        environ={sec_module.USER_AGENT_ENV: USER_AGENT},
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
        sleeper=delays.append,
    )

    imported = provider.fetch_financials(request())

    assert isinstance(provider, FinancialFetcher)
    assert [call[0] for call in transport.calls] == [
        f"{sec_module.SUBMISSIONS_URL}/CIK{CIK}.json",
        f"{sec_module.COMPANY_FACTS_URL}/CIK{CIK}.json",
    ]
    assert transport.calls[0][1] == {"Accept": "application/json", "User-Agent": USER_AGENT}
    assert delays == [sec_module.MIN_REQUEST_INTERVAL_SECONDS]
    assert imported.filings[1].amends_filing_id == imported.filings[0].filing_id
    assert imported.filings[0].accounting_standard == "US-GAAP"
    assert imported.filings[0].currency == "USD"
    assert imported.filings[0].fiscal_period_start == date(2026, 4, 1)
    assert {fact.concept for fact in imported.facts} == {"revenue", "assets"}
    assert Decimal("900") not in {fact.value for fact in imported.facts}
    assert all(fact.filing_id == imported.filings[0].filing_id for fact in imported.facts)
    assert all(fact.available_at == imported.filings[0].published_at for fact in imported.facts)
    assert imported.facts[0].period is FinancialPeriod.QUARTERLY
    assert USER_AGENT not in repr(imported)


def test_amended_fact_is_restated_and_knowledge_time_keeps_original_value() -> None:
    rows = [
        fact_row(),
        fact_row(accession="0000320193-26-000002", value="1100", form="10-Q/A"),
    ]
    imported = source([response(submissions()), response(companyfacts(rows))]).fetch_financials(
        request()
    )

    revenue = [fact for fact in imported.facts if fact.concept == "revenue"]
    assert [fact.revision for fact in revenue] == [Revision.REPORTED, Revision.RESTATED]
    before_amendment = datetime(2026, 7, 31, 19, 59, tzinfo=UTC)
    known = imported.facts_known_at(before_amendment)
    assert [fact.value for fact in known if fact.concept == "revenue"] == [Decimal("1000")]


def test_fetches_only_archived_submission_pages_overlapping_request() -> None:
    files = [
        {
            "name": "CIK0000320193-submissions-001.json",
            "filingFrom": "2026-01-01",
            "filingTo": "2026-07-01",
        },
        {
            "name": "CIK0000320193-submissions-002.json",
            "filingFrom": "2025-01-01",
            "filingTo": "2025-12-31",
        },
    ]
    recent = submission_table(
        accessions=[], filing_dates=[], report_dates=[], accepted=[], forms=[]
    )
    archived = submission_table(
        accessions=["0000320193-26-000001"],
        filing_dates=["2026-07-01"],
        report_dates=["2026-06-30"],
        accepted=["2026-07-01T20:00:00Z"],
        forms=["10-Q"],
    )
    transport = FakeTransport(
        [response(submissions(recent, files=files)), response(archived), response(companyfacts())]
    )
    provider = SecSource(
        transport=transport,
        environ={sec_module.USER_AGENT_ENV: USER_AGENT},
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
        sleeper=lambda _: None,
    )

    imported = provider.fetch_financials(request())

    assert len(imported.filings) == 1
    assert "submissions-001.json" in transport.calls[1][0]
    assert len(transport.calls) == 3
    assert len(imported.response_hash) == 64


@pytest.mark.parametrize(
    ("settings", "environ", "code"),
    (
        ({}, {sec_module.USER_AGENT_ENV: USER_AGENT}, "invalid_configuration"),
        ({"cik": "123"}, {sec_module.USER_AGENT_ENV: USER_AGENT}, "invalid_configuration"),
        (
            {"cik": CIK, "unknown": "1"},
            {sec_module.USER_AGENT_ENV: USER_AGENT},
            "invalid_configuration",
        ),
        ({"cik": CIK}, {}, "invalid_user_agent"),
        ({"cik": CIK}, {sec_module.USER_AGENT_ENV: "anonymous"}, "invalid_user_agent"),
    ),
)
def test_doctor_is_offline_and_requires_explicit_identity(
    settings: dict[str, str], environ: dict[str, str], code: str
) -> None:
    transport = FakeTransport([])
    provider = SecSource(transport=transport, environ=environ)

    diagnostic = provider.doctor_financials(
        SourceConfiguration("USD", "America/New_York", settings)
    )

    assert diagnostic.code == code
    assert diagnostic.ready is False
    assert transport.calls == []


def test_doctor_accepts_supported_forms_and_timeout_without_network() -> None:
    provider = source([])

    diagnostic = provider.doctor_financials(
        SourceConfiguration(
            "USD", "America/New_York", {"cik": CIK, "forms": "10-K,10-Q", "timeout_seconds": "5"}
        )
    )

    assert diagnostic.ready is True


@pytest.mark.parametrize(
    ("settings", "message"),
    (
        ({"cik": CIK, "forms": "10-Q,10-Q"}, "unique"),
        ({"cik": CIK, "forms": "8-K"}, "unsupported SEC form"),
        ({"cik": CIK, "timeout_seconds": "slow"}, "numeric"),
        ({"cik": CIK, "timeout_seconds": "0"}, "greater than zero"),
        ({"cik": CIK, "timeout_seconds": "61"}, "at most 60"),
    ),
)
def test_rejects_ambiguous_or_unbounded_settings(settings: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        source([]).fetch_financials(request(settings))


@pytest.mark.parametrize(
    ("status", "message"),
    (
        (302, "redirect"),
        (403, "fair-access"),
        (404, "not found"),
        (429, "rate limit"),
        (500, "HTTP status 500"),
    ),
)
def test_http_failures_are_explicit_without_exposing_body(status: int, message: str) -> None:
    provider = source([response({"private": "provider detail"}, status)])

    with pytest.raises(RuntimeError, match=message) as raised:
        provider.fetch_financials(request())

    assert "provider detail" not in str(raised.value)


@pytest.mark.parametrize(
    ("first", "second", "message"),
    (
        (
            {"cik": 999, "filings": {"recent": submission_table(), "files": []}},
            None,
            "different CIK",
        ),
        (
            submissions(
                {
                    "accessionNumber": [],
                    "filingDate": [],
                    "reportDate": [],
                    "acceptanceDateTime": [],
                    "form": ["10-Q"],
                }
            ),
            None,
            "different lengths",
        ),
        (submissions(), {"cik": 999, "facts": {}}, "different CIK"),
        (submissions(), {"cik": 320193, "facts": []}, "object is missing"),
    ),
)
def test_rejects_malformed_or_cross_company_documents(
    first: dict[str, object], second: dict[str, object] | None, message: str
) -> None:
    responses = [response(first)]
    if second is not None:
        responses.append(response(second))
    provider = source(responses)

    with pytest.raises(ValueError, match=message):
        provider.fetch_financials(request())


@pytest.mark.parametrize(
    ("files", "message"),
    (
        ([{"name": "unsafe.json", "filingFrom": "2026-01-01", "filingTo": "2026-07-01"}], "unsafe"),
        (
            [
                {
                    "name": "CIK0000320193-submissions-001.json",
                    "filingFrom": "invalid",
                    "filingTo": "2026-07-01",
                }
            ],
            "metadata",
        ),
        (
            [
                {
                    "name": "CIK0000320193-submissions-001.json",
                    "filingFrom": "2026-07-02",
                    "filingTo": "2026-07-01",
                }
            ],
            "ascending",
        ),
        (
            [
                {
                    "name": "CIK0000320193-submissions-001.json",
                    "filingFrom": "2026-01-01",
                    "filingTo": "2026-07-01",
                },
                {
                    "name": "CIK0000320193-submissions-001.json",
                    "filingFrom": "2026-01-01",
                    "filingTo": "2026-07-01",
                },
            ],
            "unique",
        ),
    ),
)
def test_rejects_unsafe_submission_history_metadata(
    files: list[dict[str, str]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        source([response(submissions(files=files))]).fetch_financials(request())


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"accessionNumber": ["invalid", "0000320193-26-000002"]}, "accession"),
        ({"filingDate": ["invalid", "2026-07-31"]}, "filing date"),
        ({"reportDate": ["invalid", "2026-06-30"]}, "report date"),
        ({"acceptanceDateTime": ["invalid", "2026-07-31T20:00:00Z"]}, "acceptance time"),
        ({"acceptanceDateTime": ["2026-07-30T20:00:00", "2026-07-31T20:00:00Z"]}, "UTC offset"),
    ),
)
def test_rejects_invalid_filing_identity_and_time(
    change: dict[str, list[str]], message: str
) -> None:
    table = submission_table()
    table.update(change)
    with pytest.raises(ValueError, match=message):
        source([response(submissions(table))]).fetch_financials(request())


def test_rejects_duplicate_accessions_and_accepts_no_supported_facts() -> None:
    duplicate = submission_table(accessions=["0000320193-26-000001", "0000320193-26-000001"])
    with pytest.raises(ValueError, match="duplicate accession"):
        source([response(submissions(duplicate))]).fetch_financials(request())

    imported = source(
        [response(submissions()), response({"cik": 320193, "facts": {}})]
    ).fetch_financials(request())
    assert imported.facts == ()
    assert imported.missing_reasons == ("no_supported_financial_facts",)


@pytest.mark.parametrize(
    ("facts", "message"),
    (
        ({"us-gaap": []}, "taxonomy facts"),
        (
            {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": []}}},
            "concept units",
        ),
        (
            {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {"USD": ["bad"]}
                    }
                }
            },
            "unit rows",
        ),
    ),
)
def test_rejects_malformed_company_fact_shapes(facts: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        source(
            [response(submissions()), response({"cik": 320193, "facts": facts})]
        ).fetch_financials(request())


@pytest.mark.parametrize(
    ("row_change", "message"),
    (
        ({"val": "NaN"}, "finite"),
        ({"val": "invalid"}, "value or period"),
        ({"form": "10-K"}, "form does not match"),
    ),
)
def test_rejects_invalid_company_fact_values(row_change: dict[str, object], message: str) -> None:
    row = fact_row()
    row.update(row_change)
    with pytest.raises(ValueError, match=message):
        source([response(submissions()), response(companyfacts([row]))]).fetch_financials(request())


def test_classifies_annual_and_interim_ytd_periods() -> None:
    annual_table = submission_table(
        accessions=["0000320193-26-000001"],
        filing_dates=["2026-07-30"],
        report_dates=["2026-06-30"],
        accepted=["2026-07-30T20:00:00Z"],
        forms=["10-K"],
    )
    annual = source(
        [
            response(submissions(annual_table)),
            response(companyfacts([fact_row(form="10-K")], include_assets=False)),
        ]
    ).fetch_financials(request())
    assert (
        next(fact for fact in annual.facts if fact.concept == "revenue").period
        is FinancialPeriod.ANNUAL
    )

    interim = source(
        [
            response(submissions()),
            response(companyfacts([fact_row(start="2026-01-01")])),
        ]
    ).fetch_financials(request())
    assert (
        next(fact for fact in interim.facts if fact.concept == "revenue").period
        is FinancialPeriod.INTERIM_YTD
    )


def test_rejects_conflicting_duplicates_and_future_publication() -> None:
    duplicate = companyfacts([fact_row(value="1000"), fact_row(value="1001")])
    with pytest.raises(ValueError, match="conflicting duplicate"):
        source([response(submissions()), response(duplicate)]).fetch_financials(request())

    with pytest.raises(ValueError, match="published after retrieval"):
        source(
            [response(submissions()), response(companyfacts())],
            clock=datetime(2026, 7, 1, tzinfo=UTC),
        ).fetch_financials(request())


def test_rejects_unsupported_market_and_unsafe_transport_values() -> None:
    jp = request()
    jp = FactFetchRequest(
        jp.source_profile,
        Instrument.create(
            symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
        ),
        jp.start,
        jp.end,
        jp.settings,
    )
    with pytest.raises(ValueError, match="XNAS and XNYS"):
        source([]).fetch_financials(jp)

    with pytest.raises(ValueError, match="valid JSON"):
        source([response(b"not-json")]).fetch_financials(request())
    with pytest.raises(RuntimeError, match="safety bound"):
        source([response(b"x" * (sec_module.MAX_RESPONSE_BYTES + 1))]).fetch_financials(request())


def test_redirect_handler_never_forwards_request() -> None:
    _NoRedirect().redirect_request(
        Request("https://data.sec.gov"), None, 302, "", {}, "https://example.com"
    )
