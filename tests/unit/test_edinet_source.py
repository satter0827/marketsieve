from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.request import Request

import pytest

from marketsieve.domain import Instrument
from marketsieve_extension_api import (
    Consolidation,
    FactFetchRequest,
    FinancialFetcher,
    FinancialPeriod,
    Revision,
    SourceConfiguration,
)
from marketsieve_source_edinet import EdinetSource
from marketsieve_source_edinet import source as edinet_module
from marketsieve_source_edinet.source import HttpResponse, _NoRedirect

API_KEY = "a" * 32
EDINET_CODE = "E02144"
DOCUMENT_ID = "S1000001"


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], dict[str, str], float]] = []

    def get(
        self, url: str, *, query: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        self.calls.append((url, dict(query), dict(headers), timeout))
        return self.responses.pop(0)


def response(value: object, status: int = 200) -> HttpResponse:
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return HttpResponse(status, body)


def filing_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "docID": DOCUMENT_ID,
        "edinetCode": EDINET_CODE,
        "secCode": "72030",
        "docTypeCode": "120",
        "periodStart": "2025-04-01",
        "periodEnd": "2026-03-31",
        "submitDateTime": "2026-06-24 15:30",
        "parentDocID": None,
        "withdrawalStatus": "0",
        "disclosureStatus": "0",
        "xbrlFlag": "1",
        "csvFlag": "1",
        "legalStatus": "1",
    }
    row.update(changes)
    return row


def document_list(
    rows: list[dict[str, object]] | None = None, status: str = "200"
) -> dict[str, object]:
    return {
        "metadata": {"title": "提出された書類を把握するためのAPI", "status": status},
        "results": [filing_row()] if rows is None else rows,
    }


def tsv_row(
    element_id: str = "jppfs_cor:NetSales",
    value: str = "1,000",
    *,
    relative_year: str = "当期",
    consolidation: str = "連結",
    period_kind: str = "期間",
) -> dict[str, str]:
    return {
        "要素ID": element_id,
        "項目名": "売上高",
        "コンテキストID": "CurrentYearDuration",
        "相対年度": relative_year,
        "連結・個別": consolidation,
        "期間・時点": period_kind,
        "ユニットID": "JPY",
        "単位": "円",
        "値": value,
    }


def xbrl_csv_zip(
    rows: list[dict[str, str]] | None = None,
    *,
    path: str = "XBRL_TO_CSV/jppfs.csv",
    headers: tuple[str, ...] = edinet_module.TSV_HEADERS,
) -> bytes:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=headers, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in rows or [tsv_row(), tsv_row("jppfs_cor:Assets", "5,000", period_kind="時点")]:
        writer.writerow({header: row.get(header, "") for header in headers})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(path, stream.getvalue().encode("utf-16"))
    return output.getvalue()


def request(
    settings: dict[str, str] | None = None,
    *,
    start: date = date(2026, 6, 24),
    end: date = date(2026, 6, 24),
) -> FactFetchRequest:
    instrument = Instrument.create(
        symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
    )
    return FactFetchRequest(
        "edinet-jp",
        instrument,
        start,
        end,
        settings or {"edinet_code": EDINET_CODE},
    )


def source(
    responses: list[HttpResponse],
    *,
    environ: Mapping[str, str] | None = None,
    clock: datetime | None = None,
) -> EdinetSource:
    return EdinetSource(
        transport=FakeTransport(responses),
        environ={edinet_module.API_KEY_ENV: API_KEY} if environ is None else environ,
        clock=lambda: clock or datetime(2026, 6, 25, tzinfo=UTC),
        sleeper=lambda _: None,
    )


def test_fetches_explicit_filing_and_xbrl_derived_facts() -> None:
    transport = FakeTransport([response(document_list()), response(xbrl_csv_zip())])
    delays: list[float] = []
    provider = EdinetSource(
        transport=transport,
        environ={edinet_module.API_KEY_ENV: API_KEY},
        clock=lambda: datetime(2026, 6, 25, tzinfo=UTC),
        sleeper=delays.append,
    )

    imported = provider.fetch_financials(request())

    assert isinstance(provider, FinancialFetcher)
    assert [call[0] for call in transport.calls] == [
        f"{edinet_module.API_ORIGIN}/documents.json",
        f"{edinet_module.API_ORIGIN}/documents/{DOCUMENT_ID}",
    ]
    assert transport.calls[0][1] == {
        "date": "2026-06-24",
        "type": "2",
        "Subscription-Key": API_KEY,
    }
    assert transport.calls[1][1]["type"] == "5"
    assert delays == [edinet_module.MIN_REQUEST_INTERVAL_SECONDS]
    assert imported.filings[0].published_at.isoformat() == "2026-06-24T15:30:00+09:00"
    assert imported.filings[0].period is FinancialPeriod.ANNUAL
    assert {fact.concept for fact in imported.facts} == {"revenue", "assets"}
    revenue = next(fact for fact in imported.facts if fact.concept == "revenue")
    assets = next(fact for fact in imported.facts if fact.concept == "assets")
    assert revenue.value == Decimal("1000")
    assert revenue.accounting_standard == "J-GAAP"
    assert revenue.consolidation is Consolidation.CONSOLIDATED
    assert revenue.fiscal_period_start == date(2025, 4, 1)
    assert assets.fiscal_period_start is None
    assert all(fact.filing_id == DOCUMENT_ID for fact in imported.facts)
    assert API_KEY not in repr(imported)


def test_correction_uses_parent_document_and_restated_facts() -> None:
    row = filing_row(docID="S1000002", docTypeCode="130", parentDocID=DOCUMENT_ID)
    imported = source([response(document_list([row])), response(xbrl_csv_zip())]).fetch_financials(
        request()
    )

    assert imported.filings[0].amends_filing_id == DOCUMENT_ID
    assert all(fact.revision is Revision.RESTATED for fact in imported.facts)


def test_multiple_file_dates_are_explicit_and_later_metadata_wins() -> None:
    earlier = filing_row(docDescription="before")
    later = filing_row(docDescription="after")
    provider = source(
        [
            response(document_list([earlier])),
            response(document_list([later])),
            response(xbrl_csv_zip()),
        ]
    )

    imported = provider.fetch_financials(request(start=date(2026, 6, 24), end=date(2026, 6, 25)))

    assert len(imported.filings) == 1
    transport = provider._transport
    assert isinstance(transport, FakeTransport)
    assert [call[1]["date"] for call in transport.calls[:2]] == ["2026-06-24", "2026-06-25"]


def test_filters_other_issuers_unselected_types_and_unavailable_documents() -> None:
    rows = [
        filing_row(docID="S1000002", edinetCode="E00001"),
        filing_row(docID="S1000003", docTypeCode="180"),
        filing_row(docID="S1000004", csvFlag="0"),
        filing_row(docID="S1000005", withdrawalStatus="1"),
        filing_row(docID="S1000006", legalStatus="3"),
    ]

    imported = source([response(document_list(rows))]).fetch_financials(request())

    assert imported.filings == ()
    assert imported.facts == ()
    assert imported.missing_reasons == ("no_supported_financial_facts",)


def test_ignores_prior_year_unknown_taxonomy_and_preserves_scope() -> None:
    rows = [
        tsv_row(relative_year="前期"),
        tsv_row("issuer:CustomRevenue"),
        tsv_row(consolidation="個別"),
        tsv_row("ifrs-full:Revenue", "2,000", consolidation=""),
        tsv_row("us-gaap:Revenues", "△300", consolidation="連結"),
    ]
    imported = source([response(document_list()), response(xbrl_csv_zip(rows))]).fetch_financials(
        request()
    )

    assert [fact.value for fact in imported.facts] == [
        Decimal("2000"),
        Decimal("1000"),
        Decimal("-300"),
    ]
    assert {fact.accounting_standard for fact in imported.facts} == {"IFRS", "US-GAAP", "J-GAAP"}
    assert {fact.consolidation for fact in imported.facts} == {
        Consolidation.UNKNOWN,
        Consolidation.CONSOLIDATED,
        Consolidation.NON_CONSOLIDATED,
    }


@pytest.mark.parametrize(
    ("settings", "environ", "code"),
    (
        ({}, {edinet_module.API_KEY_ENV: API_KEY}, "invalid_configuration"),
        ({"edinet_code": "bad"}, {edinet_module.API_KEY_ENV: API_KEY}, "invalid_configuration"),
        (
            {"edinet_code": EDINET_CODE, "unknown": "1"},
            {edinet_module.API_KEY_ENV: API_KEY},
            "invalid_configuration",
        ),
        ({"edinet_code": EDINET_CODE}, {}, "invalid_credential"),
        (
            {"edinet_code": EDINET_CODE},
            {edinet_module.API_KEY_ENV: "bad key"},
            "invalid_credential",
        ),
    ),
)
def test_doctor_is_offline_and_requires_configuration_and_key(
    settings: dict[str, str], environ: dict[str, str], code: str
) -> None:
    transport = FakeTransport([])
    provider = EdinetSource(transport=transport, environ=environ)

    diagnostic = provider.doctor_financials(SourceConfiguration("JPY", "Asia/Tokyo", settings))

    assert diagnostic.code == code
    assert diagnostic.ready is False
    assert transport.calls == []


def test_doctor_accepts_bounded_settings_without_network() -> None:
    diagnostic = source([]).doctor_financials(
        SourceConfiguration(
            "JPY",
            "Asia/Tokyo",
            {
                "edinet_code": EDINET_CODE,
                "document_type_codes": "120,130",
                "max_days": "7",
                "max_documents": "5",
                "timeout_seconds": "5",
            },
        )
    )
    assert diagnostic.ready is True


@pytest.mark.parametrize(
    ("settings", "message"),
    (
        ({"edinet_code": EDINET_CODE, "document_type_codes": "120,120"}, "unique"),
        ({"edinet_code": EDINET_CODE, "document_type_codes": "180"}, "unsupported"),
        ({"edinet_code": EDINET_CODE, "max_days": "0"}, "max_days"),
        ({"edinet_code": EDINET_CODE, "max_documents": "101"}, "max_documents"),
        ({"edinet_code": EDINET_CODE, "timeout_seconds": "0"}, "timeout_seconds"),
        ({"edinet_code": EDINET_CODE, "max_days": "bad"}, "numeric"),
    ),
)
def test_rejects_invalid_settings(settings: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        source([]).fetch_financials(request(settings))


def test_rejects_range_and_document_count_over_budget() -> None:
    with pytest.raises(ValueError, match="exceeds max_days"):
        source([]).fetch_financials(
            request(
                {"edinet_code": EDINET_CODE, "max_days": "1"},
                start=date(2026, 6, 24),
                end=date(2026, 6, 25),
            )
        )
    with pytest.raises(ValueError, match="exceeds max_documents"):
        source(
            [response(document_list([filing_row(), filing_row(docID="S1000002")]))]
        ).fetch_financials(request({"edinet_code": EDINET_CODE, "max_documents": "1"}))


@pytest.mark.parametrize(
    ("status", "message"),
    (
        (302, "redirect"),
        (401, "credential"),
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
    ("document", "message"),
    (
        (b"not-json", "valid JSON"),
        ([], "JSON object"),
        ({"metadata": {"status": "400"}}, "application error"),
        ({"metadata": {"status": "200"}, "results": {}}, "array of objects"),
    ),
)
def test_rejects_invalid_list_responses(document: object, message: str) -> None:
    with pytest.raises((ValueError, RuntimeError), match=message):
        source([response(document)]).fetch_financials(request())


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"docID": "bad"}, "document ID"),
        ({"secCode": "99990"}, "different security"),
        ({"periodEnd": "invalid"}, "period or submission"),
        ({"submitDateTime": "invalid"}, "period or submission"),
        ({"parentDocID": "bad", "docTypeCode": "130"}, "parent document ID"),
    ),
)
def test_rejects_invalid_document_identity(change: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        source([response(document_list([filing_row(**change)]))]).fetch_financials(request())


def test_rejects_document_api_error_and_invalid_zip() -> None:
    with pytest.raises(RuntimeError, match="application error"):
        source(
            [response(document_list()), response({"metadata": {"status": "400"}})]
        ).fetch_financials(request())
    with pytest.raises(ValueError, match="valid ZIP"):
        source([response(document_list()), response(b"not-zip")]).fetch_financials(request())


def test_rejects_unsafe_zip_paths_headers_encoding_and_values() -> None:
    with pytest.raises(ValueError, match="unsafe path"):
        source(
            [response(document_list()), response(xbrl_csv_zip(path="../bad.csv"))]
        ).fetch_financials(request())
    with pytest.raises(ValueError, match="headers"):
        source(
            [response(document_list()), response(xbrl_csv_zip(headers=("要素ID",)))]
        ).fetch_financials(request())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("XBRL_TO_CSV/data.csv", b"not-utf16")
    with pytest.raises(ValueError, match="UTF-16"):
        source([response(document_list()), response(output.getvalue())]).fetch_financials(request())
    with pytest.raises(ValueError, match="financial value"):
        source(
            [response(document_list()), response(xbrl_csv_zip([tsv_row(value="NaN")]))]
        ).fetch_financials(request())


def test_rejects_conflicting_duplicate_facts_and_naive_clock() -> None:
    rows = [tsv_row(value="1000"), tsv_row(value="1001")]
    with pytest.raises(ValueError, match="conflicting duplicate"):
        source([response(document_list()), response(xbrl_csv_zip(rows))]).fetch_financials(
            request()
        )
    with pytest.raises(ValueError, match="offset-aware"):
        source(
            [response(document_list()), response(xbrl_csv_zip())],
            clock=datetime(2026, 6, 25),
        ).fetch_financials(request())


def test_rejects_unsupported_market_and_oversized_response() -> None:
    us_request = request()
    us_request = FactFetchRequest(
        us_request.source_profile,
        Instrument.create(
            symbol="AAPL", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
        ),
        us_request.start,
        us_request.end,
        us_request.settings,
    )
    with pytest.raises(ValueError, match="XTKS"):
        source([]).fetch_financials(us_request)
    with pytest.raises(RuntimeError, match="safety bound"):
        source([response(b"x" * (edinet_module.MAX_RESPONSE_BYTES + 1))]).fetch_financials(
            request()
        )


def test_redirect_handler_never_forwards_request() -> None:
    _NoRedirect().redirect_request(
        Request("https://api.edinet-fsa.go.jp"), None, 302, "", {}, "https://example.com"
    )
