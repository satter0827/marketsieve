from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.request import Request

import pytest

from marketsieve_extension_api import (
    EconomicSeriesFetcher,
    EconomicSeriesFetchRequest,
    EconomicSeriesSourceConfiguration,
    ImportedEconomicSeries,
)
from marketsieve_source_fred import FredSource
from marketsieve_source_fred import source as fred_module
from marketsieve_source_fred.source import HttpResponse, _NoRedirect

API_KEY = "a" * 32


def credential_environment(value: str) -> dict[str, str]:
    return {fred_module.API_KEY_ENV: value}


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


def row(
    observation_date: str,
    value: str,
    *,
    realtime_start: str = "2026-07-01",
    realtime_end: str = "9999-12-31",
) -> dict[str, str]:
    return {
        "date": observation_date,
        "value": value,
        "realtime_start": realtime_start,
        "realtime_end": realtime_end,
    }


def page(
    observations: list[dict[str, str]],
    *,
    count: int | None = None,
    offset: int = 0,
    limit: int = 100000,
) -> dict[str, object]:
    return {
        "count": len(observations) if count is None else count,
        "offset": offset,
        "limit": limit,
        "observations": observations,
    }


def request(settings: dict[str, str] | None = None) -> EconomicSeriesFetchRequest:
    return EconomicSeriesFetchRequest(
        "macro",
        "DGS10",
        date(2026, 7, 1),
        date(2026, 7, 3),
        date(2026, 7, 31),
        settings or {},
    )


def source(
    responses: list[HttpResponse],
    *,
    environ: Mapping[str, str] | None = None,
    clock: datetime | None = None,
) -> FredSource:
    return FredSource(
        transport=FakeTransport(responses),
        environ=credential_environment(API_KEY) if environ is None else environ,
        clock=lambda: clock or datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_fetches_one_explicit_vintage_and_preserves_missing_observations() -> None:
    transport = FakeTransport([response(page([row("2026-07-01", "4.25"), row("2026-07-02", ".")]))])
    provider = FredSource(
        transport=transport,
        environ=credential_environment(API_KEY),
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    )

    imported = provider.fetch_economic_series(request())

    assert isinstance(provider, EconomicSeriesFetcher)
    assert imported.series.observations[0].value == Decimal("4.25")
    assert imported.series.missing_observation_dates == (date(2026, 7, 2),)
    assert imported.series.knowledge_date == date(2026, 7, 31)
    assert imported.retrieved_at == datetime(2026, 8, 1, tzinfo=UTC)
    query = transport.calls[0][1]
    assert query.pop("api_key") == API_KEY
    assert query == {
        "file_type": "json",
        "series_id": "DGS10",
        "observation_start": "2026-07-01",
        "observation_end": "2026-07-03",
        "realtime_start": "2026-07-31",
        "realtime_end": "2026-07-31",
        "output_type": "1",
        "units": "lin",
        "sort_order": "asc",
        "limit": "100000",
        "offset": "0",
    }
    assert API_KEY not in repr(imported)


def test_pagination_is_explicit_complete_and_part_of_response_identity() -> None:
    first_body = json.dumps(page([row("2026-07-01", "4.25")], count=2, limit=1)).encode()
    second_body = json.dumps(page([row("2026-07-02", "4.30")], count=2, offset=1, limit=1)).encode()
    transport = FakeTransport([HttpResponse(200, first_body), HttpResponse(200, second_body)])
    provider = FredSource(
        transport=transport,
        environ=credential_environment(API_KEY),
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    )

    imported = provider.fetch_economic_series(request({"page_size": "1"}))

    assert [call[1]["offset"] for call in transport.calls] == ["0", "1"]
    assert [item.observation_date for item in imported.series.observations] == [
        date(2026, 7, 1),
        date(2026, 7, 2),
    ]
    digest = hashlib.sha256()
    digest.update(hashlib.sha256(first_body).digest())
    digest.update(hashlib.sha256(second_body).digest())
    assert imported.response_hash == digest.hexdigest()


@pytest.mark.parametrize(
    ("settings", "environ", "code"),
    (
        ({}, {}, "missing_credential"),
        ({}, credential_environment("invalid"), "invalid_credential"),
        ({"unknown": "1"}, credential_environment(API_KEY), "invalid_configuration"),
        ({"page_size": "0"}, credential_environment(API_KEY), "invalid_configuration"),
    ),
)
def test_doctor_is_offline_and_credential_safe(
    settings: dict[str, str], environ: dict[str, str], code: str
) -> None:
    transport = FakeTransport([])
    provider = FredSource(transport=transport, environ=environ)

    diagnostic = provider.doctor_economic_series(EconomicSeriesSourceConfiguration(settings))

    assert diagnostic.code == code
    assert diagnostic.ready is False
    assert API_KEY not in repr(diagnostic)
    assert transport.calls == []


def test_doctor_accepts_valid_settings_without_network_access() -> None:
    provider = source([])

    diagnostic = provider.doctor_economic_series(
        EconomicSeriesSourceConfiguration({"timeout_seconds": "5", "page_size": "100"})
    )

    assert diagnostic.ready is True


@pytest.mark.parametrize(
    ("status", "message"),
    (
        (401, "credential"),
        (429, "rate limit"),
        (302, "redirect"),
        (500, "HTTP status 500"),
    ),
)
def test_http_failures_are_explicit_without_response_body(status: int, message: str) -> None:
    secret_body = b'{"message":"secret provider detail"}'

    with pytest.raises(RuntimeError, match=message) as error:
        source([HttpResponse(status, secret_body)]).fetch_economic_series(request())

    assert "secret provider detail" not in str(error.value)


@pytest.mark.parametrize(
    ("document", "message"),
    (
        (b"not-json", "invalid JSON"),
        ([], "JSON object"),
        ({"count": "1", "offset": 0, "limit": 1, "observations": []}, "count"),
        ({"count": 1, "offset": 1, "limit": 1, "observations": []}, "pagination"),
        ({"count": 1, "offset": 0, "limit": 1, "observations": "bad"}, "array"),
    ),
)
def test_malformed_documents_are_rejected(document: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        source([response(document)]).fetch_economic_series(request())


@pytest.mark.parametrize(
    ("rows", "message"),
    (
        ([{"date": "2026-07-01"}], "malformed"),
        ([row("2026-06-30", "4")], "requested range"),
        ([row("2026-07-01", "4", realtime_start="2026-08-01")], "knowledge date"),
        ([row("2026-07-01", "not-number")], "non-decimal"),
        ([{**row("2026-07-01", "4"), "value": 4}], "non-string"),
        ([row("2026-07-01", "4"), row("2026-07-01", "5")], "duplicate"),
        ([row("2026-07-02", "4"), row("2026-07-01", "5")], "ascending"),
        (
            [row("2026-07-01", "4"), row("2026-07-03", "."), row("2026-07-02", "5")],
            "ascending",
        ),
    ),
)
def test_malformed_observations_are_rejected(rows: list[dict[str, str]], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        source([response(page(rows))]).fetch_economic_series(request())


def test_fetch_rejects_missing_or_invalid_credentials_before_network() -> None:
    for environ in ({}, credential_environment("bad")):
        transport = FakeTransport([])
        provider = FredSource(transport=transport, environ=environ)
        with pytest.raises(RuntimeError, match=r"credential|FRED_API_KEY"):
            provider.fetch_economic_series(request())
        assert transport.calls == []


def test_pagination_rejects_stalled_changed_and_excessive_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stalled = page([], count=1)
    with pytest.raises(ValueError, match="no progress"):
        source([response(stalled)]).fetch_economic_series(request())

    changed = [
        response(page([row("2026-07-01", "4")], count=2, limit=1)),
        response(page([row("2026-07-02", "5")], count=3, offset=1, limit=1)),
    ]
    with pytest.raises(ValueError, match="count changed"):
        source(changed).fetch_economic_series(request({"page_size": "1"}))

    monkeypatch.setattr(fred_module, "MAX_PAGES", 1)
    with pytest.raises(RuntimeError, match="safety limit"):
        source([response(page([row("2026-07-01", "4")], count=2, limit=1))]).fetch_economic_series(
            request({"page_size": "1"})
        )


def test_fetch_rejects_an_empty_result_naive_clock_and_oversized_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="must contain"):
        source([response(page([]))]).fetch_economic_series(request())
    with pytest.raises(ValueError, match="offset-aware"):
        source(
            [response(page([row("2026-07-01", "4")]))],
            clock=datetime(2026, 8, 1),
        ).fetch_economic_series(request())
    monkeypatch.setattr(fred_module, "MAX_RESPONSE_BYTES", 2)
    with pytest.raises(RuntimeError, match="safety bound"):
        source([HttpResponse(200, b"{}x")]).fetch_economic_series(request())


def test_redirect_handler_never_forwards_the_request() -> None:
    handler = _NoRedirect()

    handler.redirect_request(
        Request("https://api.stlouisfed.org"),
        None,
        302,
        "redirect",
        {},
        "https://example.com",
    )


def test_request_contract_rejects_invalid_ranges_and_result_identity() -> None:
    with pytest.raises(ValueError, match="start must not exceed"):
        EconomicSeriesFetchRequest(
            "macro", "DGS10", date(2026, 8, 1), date(2026, 7, 1), date(2026, 8, 1), {}
        )


def test_request_contract_rejects_missing_identity_and_invalid_date_types() -> None:
    with pytest.raises(ValueError, match="profile"):
        EconomicSeriesFetchRequest(
            "", "DGS10", date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 31), {}
        )
    with pytest.raises(ValueError, match="series ID"):
        EconomicSeriesFetchRequest(
            "macro", "", date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 31), {}
        )
    with pytest.raises(TypeError, match="dates must use"):
        EconomicSeriesFetchRequest(
            "macro",
            "DGS10",
            "2026-07-01",  # type: ignore[arg-type]
            date(2026, 7, 2),
            date(2026, 7, 31),
            {},
        )


def test_imported_result_contract_rejects_identity_time_range_and_hash_drift() -> None:
    imported = source([response(page([row("2026-07-01", "4")]))]).fetch_economic_series(request())
    invalid_request = EconomicSeriesFetchRequest(
        "macro",
        "DGS2",
        date(2026, 7, 1),
        date(2026, 7, 3),
        date(2026, 7, 31),
        {},
    )
    with pytest.raises(ValueError, match="identity fields"):
        ImportedEconomicSeries(
            imported.request,
            "",
            imported.source_version,
            imported.dataset,
            imported.retrieved_at,
            imported.series,
            imported.response_hash,
        )
    with pytest.raises(ValueError, match="UTC offset"):
        ImportedEconomicSeries(
            imported.request,
            imported.source_name,
            imported.source_version,
            imported.dataset,
            datetime(2026, 8, 1),
            imported.series,
            imported.response_hash,
        )
    with pytest.raises(ValueError, match="series must match"):
        ImportedEconomicSeries(
            invalid_request,
            imported.source_name,
            imported.source_version,
            imported.dataset,
            imported.retrieved_at,
            imported.series,
            imported.response_hash,
        )
    with pytest.raises(ValueError, match="requested range"):
        ImportedEconomicSeries(
            EconomicSeriesFetchRequest(
                "macro",
                "DGS10",
                date(2026, 7, 2),
                date(2026, 7, 3),
                date(2026, 7, 31),
                {},
            ),
            imported.source_name,
            imported.source_version,
            imported.dataset,
            imported.retrieved_at,
            imported.series,
            imported.response_hash,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        ImportedEconomicSeries(
            imported.request,
            imported.source_name,
            imported.source_version,
            imported.dataset,
            imported.retrieved_at,
            imported.series,
            "not-a-hash",
        )
