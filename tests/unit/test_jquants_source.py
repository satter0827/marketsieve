from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from urllib.request import Request

import pytest

from marketsieve.data.daily import Adjustment
from marketsieve.domain import Instrument
from marketsieve_extension_api import DailyBarFetchRequest, DailyBarSourceConfiguration
from marketsieve_source_jquants.source import HttpResponse, JQuantsSource, _NoRedirect


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
    return HttpResponse(status, json.dumps(value).encode())


def request(adjustment: Adjustment = Adjustment.RAW) -> DailyBarFetchRequest:
    return DailyBarFetchRequest(
        source_profile="japan",
        instrument=Instrument.create(
            symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
        ),
        start=date(2026, 7, 30),
        end=date(2026, 7, 31),
        adjustment=adjustment,
        settings={},
    )


def configuration(
    settings: dict[str, str] | None = None,
    *,
    currency: str = "JPY",
    timezone: str = "Asia/Tokyo",
) -> DailyBarSourceConfiguration:
    return DailyBarSourceConfiguration(currency, timezone, settings or {})


def profile() -> dict[str, object]:
    return {
        "data": [
            {
                "Date": "2026-07-31",
                "Code": "72030",
                "CoName": "トヨタ自動車",
                "CoNameEn": "TOYOTA MOTOR CORPORATION",
                "S17": "3",
                "S33": "3700",
                "Mkt": "0111",
                "MarginCode": "2",
            }
        ]
    }


def bars() -> list[dict[str, object]]:
    return [
        {
            "Date": "2026-07-30",
            "Code": "72030",
            "O": "100",
            "H": "110",
            "L": "90",
            "C": "105",
            "Vo": "1000",
            "AdjO": "50",
            "AdjH": "55",
            "AdjL": "45",
            "AdjC": "52.5",
            "AdjVo": "2000",
        },
        {
            "Date": "2026-07-31",
            "Code": "72030",
            "O": "105",
            "H": "115",
            "L": "101",
            "C": "112",
            "Vo": "1200",
            "AdjO": "52.5",
            "AdjH": "57.5",
            "AdjL": "50.5",
            "AdjC": "56",
            "AdjVo": "2400",
        },
    ]


def test_fetches_profile_and_paginated_exact_daily_bars_without_storing_secret() -> None:
    transport = FakeTransport(
        [
            response(profile()),
            response({"data": bars()[:1], "pagination_key": "next"}),
            response({"data": bars()[1:]}),
        ]
    )
    source = JQuantsSource(
        transport=transport,
        environ={"JQUANTS_API_KEY": "example"},
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    )

    imported = source.fetch(request())

    assert [bar.close for bar in imported.bars] == [105, 112]
    assert imported.instrument_profile is not None
    assert dict(imported.instrument_profile.names)["ja"] == "トヨタ自動車"
    assert imported.fetch_request == request()
    assert transport.calls[1][1] == {
        "code": "7203",
        "from": "2026-07-30",
        "to": "2026-07-31",
    }
    assert transport.calls[2][1]["pagination_key"] == "next"
    assert all(call[2]["x-api-key"] == "example" for call in transport.calls)
    assert "example" not in repr(imported)


def test_adjusted_request_uses_only_adjusted_fields() -> None:
    source = JQuantsSource(
        transport=FakeTransport([response(profile()), response({"data": bars()})]),
        environ={"JQUANTS_API_KEY": "example"},
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    )

    imported = source.fetch(request(Adjustment.ADJUSTED))

    assert [str(bar.close) for bar in imported.bars] == ["52.5", "56"]
    assert [bar.volume for bar in imported.bars] == [2000, 2400]


@pytest.mark.parametrize("provider_code", ("72031", "720300", "7203", "172030"))
def test_response_issue_code_must_match_the_exact_provider_mapping(provider_code: str) -> None:
    profile_response = profile()
    profile_response["data"][0]["Code"] = provider_code  # type: ignore[index]
    source = JQuantsSource(
        transport=FakeTransport([response(profile_response)]),
        environ={"JQUANTS_API_KEY": "example"},
    )

    with pytest.raises(ValueError, match="exactly one requested issue"):
        source.fetch(request())

    bar_rows = bars()
    bar_rows[0]["Code"] = provider_code
    source = JQuantsSource(
        transport=FakeTransport([response(profile()), response({"data": bar_rows})]),
        environ={"JQUANTS_API_KEY": "example"},
    )

    with pytest.raises(ValueError, match="different issue"):
        source.fetch(request())


def test_doctor_is_offline_and_requires_only_environment_credential() -> None:
    transport = FakeTransport([])

    missing = JQuantsSource(transport=transport, environ={}).doctor(configuration())
    ready = JQuantsSource(transport=transport, environ={"JQUANTS_API_KEY": "example"}).doctor(
        configuration({"timeout_seconds": "15"})
    )

    assert missing.code == "missing_credential"
    assert ready.ready is True
    assert transport.calls == []


def test_malformed_credential_is_rejected_without_disclosure() -> None:
    malformed_value = "example\ninvalid"
    source = JQuantsSource(
        transport=FakeTransport([]), environ={"JQUANTS_API_KEY": malformed_value}
    )

    diagnostic = source.doctor(configuration())
    with pytest.raises(RuntimeError, match="invalid header") as raised:
        source.fetch(request())

    assert diagnostic.code == "invalid_credential"
    assert malformed_value not in diagnostic.message
    assert malformed_value not in str(raised.value)


@pytest.mark.parametrize(
    ("status", "message"),
    ((401, "API key"), (403, "plan"), (413, "too large"), (429, "rate limit"), (500, "failed")),
)
def test_provider_failures_are_explicit_and_never_shorten_request(
    status: int, message: str
) -> None:
    source = JQuantsSource(
        transport=FakeTransport([response({"message": "secret detail"}, status)]),
        environ={"JQUANTS_API_KEY": "example"},
    )

    with pytest.raises(RuntimeError, match=message) as raised:
        source.fetch(request())

    assert "not shortened" in str(raised.value)
    assert "example" not in str(raised.value)
    assert "secret detail" not in str(raised.value)


def test_malformed_response_and_repeated_pagination_are_rejected() -> None:
    malformed = JQuantsSource(
        transport=FakeTransport([HttpResponse(200, b"not-json")]),
        environ={"JQUANTS_API_KEY": "example"},
    )
    repeated = JQuantsSource(
        transport=FakeTransport(
            [
                response(profile() | {"pagination_key": "same"}),
                response(profile() | {"pagination_key": "same"}),
            ]
        ),
        environ={"JQUANTS_API_KEY": "example"},
    )

    with pytest.raises(ValueError, match="valid JSON"):
        malformed.fetch(request())
    with pytest.raises(ValueError, match="pagination_key"):
        repeated.fetch(request())


def test_configuration_and_market_are_restricted_before_network() -> None:
    source = JQuantsSource(transport=FakeTransport([]), environ={"JQUANTS_API_KEY": "example"})
    invalid_market = DailyBarFetchRequest(
        source_profile="japan",
        instrument=Instrument.create(
            symbol="AAPL", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
        ),
        start=date(2026, 7, 30),
        end=date(2026, 7, 31),
        adjustment=Adjustment.RAW,
        settings={},
    )

    with pytest.raises(ValueError, match="only XTKS"):
        source.fetch(invalid_market)
    assert (
        source.doctor(configuration({"base_url": "https://attacker.invalid"})).code
        == "invalid_configuration"
    )


@pytest.mark.parametrize(
    "settings",
    (
        {"unknown": "value"},
        {"timeout_seconds": "not-numeric"},
        {"timeout_seconds": "0"},
        {"timeout_seconds": "121"},
    ),
)
def test_invalid_provider_settings_are_diagnosed_offline(settings: dict[str, str]) -> None:
    result = JQuantsSource(transport=FakeTransport([]), environ={}).doctor(configuration(settings))

    assert result.code == "invalid_configuration"


@pytest.mark.parametrize(
    "source_configuration",
    (
        configuration(currency="USD"),
        configuration(timezone="UTC"),
    ),
)
def test_incompatible_market_profile_is_diagnosed_offline(
    source_configuration: DailyBarSourceConfiguration,
) -> None:
    result = JQuantsSource(transport=FakeTransport([]), environ={}).doctor(source_configuration)

    assert result.code == "invalid_configuration"


def test_fetch_rejects_incorrect_xtks_timezone_before_network() -> None:
    invalid_timezone = DailyBarFetchRequest(
        source_profile="japan",
        instrument=Instrument.create(
            symbol="7203", mic="XTKS", currency="JPY", exchange_timezone="UTC"
        ),
        start=date(2026, 7, 30),
        end=date(2026, 7, 31),
        adjustment=Adjustment.RAW,
        settings={},
    )
    source = JQuantsSource(transport=FakeTransport([]), environ={"JQUANTS_API_KEY": "example"})

    with pytest.raises(ValueError, match="Asia/Tokyo"):
        source.fetch(invalid_timezone)


def test_fetch_requires_credential_and_offset_aware_clock() -> None:
    missing = JQuantsSource(transport=FakeTransport([]), environ={})
    naive = JQuantsSource(
        transport=FakeTransport([response(profile()), response({"data": bars()})]),
        environ={"JQUANTS_API_KEY": "example"},
        clock=lambda: datetime(2026, 8, 1),
    )

    with pytest.raises(RuntimeError, match="missing credential"):
        missing.fetch(request())
    with pytest.raises(ValueError, match="offset-aware"):
        naive.fetch(request())


def test_retrieval_timestamp_is_captured_after_all_pages_arrive() -> None:
    transport = FakeTransport([response(profile()), response({"data": bars()})])

    def completed_clock() -> datetime:
        assert transport.responses == []
        return datetime(2026, 8, 1, tzinfo=UTC)

    imported = JQuantsSource(
        transport=transport,
        environ={"JQUANTS_API_KEY": "example"},
        clock=completed_clock,
    ).fetch(request())

    assert {bar.available_at for bar in imported.bars} == {imported.retrieved_at}


def test_standard_transport_rejects_redirects_before_forwarding_headers() -> None:
    _NoRedirect().redirect_request(
        Request("https://api.jquants.com/v2/equities/master"),
        None,
        302,
        "Found",
        {},
        "https://attacker.invalid/collect",
    )


@pytest.mark.parametrize(
    ("price_rows", "message"),
    (
        ([bars()[0] | {"Code": "99990"}], "different issue"),
        ([bars()[0] | {"Date": "2026-07-29"}], "outside"),
        ([bars()[0] | {"Vo": "1.5"}], "integer"),
        ([bars()[0], bars()[0]], "duplicate"),
        ([{key: value for key, value in bars()[0].items() if key != "O"}], "missing"),
        ([bars()[0] | {"O": None}], "partially null"),
        ([bars()[0] | {key: None for key in ("O", "H", "L", "C", "Vo")}], "no tradable"),
    ),
)
def test_daily_bar_contract_rejects_provider_substitution(
    price_rows: list[dict[str, object]], message: str
) -> None:
    source = JQuantsSource(
        transport=FakeTransport([response(profile()), response({"data": price_rows})]),
        environ={"JQUANTS_API_KEY": "example"},
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match=message):
        source.fetch(request())


def test_response_requires_data_array_and_exactly_one_valid_profile() -> None:
    invalid_data = JQuantsSource(
        transport=FakeTransport([response({"data": {}})]),
        environ={"JQUANTS_API_KEY": "example"},
    )
    ambiguous = JQuantsSource(
        transport=FakeTransport([response({"data": []}), response({"data": bars()})]),
        environ={"JQUANTS_API_KEY": "example"},
    )
    invalid_date_profile = profile()
    invalid_date_profile["data"][0]["Date"] = "invalid"  # type: ignore[index]
    invalid_date = JQuantsSource(
        transport=FakeTransport([response(invalid_date_profile), response({"data": bars()})]),
        environ={"JQUANTS_API_KEY": "example"},
    )

    with pytest.raises(ValueError, match="array of objects"):
        invalid_data.fetch(request())
    with pytest.raises(ValueError, match="exactly one"):
        ambiguous.fetch(request())
    with pytest.raises(ValueError, match="invalid Date"):
        invalid_date.fetch(request())
