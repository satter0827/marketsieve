from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, getcontext
from urllib.request import Request

import pytest

from marketsieve.data.daily import Adjustment
from marketsieve.domain import Instrument
from marketsieve_extension_api import (
    DailyBarFetchRequest,
    DailyBarSourceConfiguration,
    FactFetchRequest,
    SourceConfiguration,
)
from marketsieve_source_alphavantage.source import (
    AlphaVantageSource,
    HttpResponse,
    _NoRedirect,
)


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


def instrument() -> Instrument:
    return Instrument.create(
        symbol="MSFT", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
    )


def request(
    adjustment: Adjustment = Adjustment.RAW, settings: dict[str, str] | None = None
) -> DailyBarFetchRequest:
    return DailyBarFetchRequest(
        "us",
        instrument(),
        date(2026, 7, 30),
        date(2026, 7, 31),
        adjustment,
        settings or {},
    )


def fact_request(settings: dict[str, str] | None = None) -> FactFetchRequest:
    return FactFetchRequest("us", instrument(), date(2025, 1, 1), date(2026, 7, 31), settings or {})


def configuration(settings: dict[str, str] | None = None) -> DailyBarSourceConfiguration:
    return DailyBarSourceConfiguration("USD", "America/New_York", settings or {})


def overview() -> dict[str, str]:
    return {
        "Symbol": "MSFT",
        "Name": "Microsoft Corporation",
        "AssetType": "Common Stock",
        "Exchange": "NASDAQ",
        "Country": "USA",
        "Sector": "TECHNOLOGY",
        "Industry": "SOFTWARE",
        "LatestQuarter": "2026-06-30",
        "PERatio": "35.1",
        "PriceToBookRatio": "11.2",
        "PriceToSalesRatioTTM": "12.5",
        "DividendYield": "0.0068",
        "MarketCapitalization": "3800000000000",
    }


def raw_prices() -> dict[str, object]:
    return {
        "Meta Data": {"2. Symbol": "MSFT", "3. Last Refreshed": "2026-07-31"},
        "Time Series (Daily)": {
            "2026-07-31": {
                "1. open": "105",
                "2. high": "115",
                "3. low": "101",
                "4. close": "112",
                "5. volume": "1200",
            },
            "2026-07-30": {
                "1. open": "100",
                "2. high": "110",
                "3. low": "90",
                "4. close": "105",
                "5. volume": "1000",
            },
        },
    }


def adjusted_prices() -> dict[str, object]:
    document = raw_prices()
    series = document["Time Series (Daily)"]
    assert isinstance(series, dict)
    rows = list(series.values())
    assert all(isinstance(row, dict) for row in rows)
    rows[0].update({"5. adjusted close": "56", "6. volume": "1200", "8. split coefficient": "2"})
    rows[1].update({"5. adjusted close": "52.5", "6. volume": "1000", "8. split coefficient": "1"})
    return document


def source(responses: list[HttpResponse], *, clock: datetime | None = None) -> AlphaVantageSource:
    return AlphaVantageSource(
        transport=FakeTransport(responses),
        environ={"ALPHAVANTAGE_API_KEY": "example"},
        clock=lambda: clock or datetime(2026, 8, 1, tzinfo=UTC),
    )


def assert_overview_rejected_for_every_data_kind(
    profile: dict[str, str], requested_instrument: Instrument, message: str
) -> None:
    daily = DailyBarFetchRequest(
        "us",
        requested_instrument,
        date(2026, 7, 30),
        date(2026, 7, 31),
        Adjustment.RAW,
        {},
    )
    facts = FactFetchRequest("us", requested_instrument, date(2025, 1, 1), date(2026, 7, 31), {})
    for operation, request_value in (
        ("daily", daily),
        ("financials", facts),
        ("events", facts),
    ):
        transport = FakeTransport([response(profile)])
        provider = AlphaVantageSource(
            transport=transport, environ={"ALPHAVANTAGE_API_KEY": "example"}
        )
        with pytest.raises(ValueError, match=message):
            if operation == "daily":
                assert isinstance(request_value, DailyBarFetchRequest)
                provider.fetch(request_value)
            elif operation == "financials":
                assert isinstance(request_value, FactFetchRequest)
                provider.fetch_financials(request_value)
            else:
                assert isinstance(request_value, FactFetchRequest)
                provider.fetch_events(request_value)
        assert [call[1]["function"] for call in transport.calls] == ["OVERVIEW"]


def test_fetches_raw_daily_bars_and_profile_without_exposing_query_credential() -> None:
    transport = FakeTransport([response(overview()), response(raw_prices())])
    provider = AlphaVantageSource(
        transport=transport,
        environ={"ALPHAVANTAGE_API_KEY": "example"},
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    )

    imported = provider.fetch(request())

    assert [bar.close for bar in imported.bars] == [Decimal("105"), Decimal("112")]
    assert imported.fetch_request == request()
    assert imported.instrument_profile is not None
    assert dict(imported.instrument_profile.names)["en"] == "Microsoft Corporation"
    assert dict(imported.instrument_profile.attributes)["trailing_per"] == "35.1"
    assert [call[1]["function"] for call in transport.calls] == ["OVERVIEW", "TIME_SERIES_DAILY"]
    assert all(call[1]["apikey"] == "example" for call in transport.calls)
    assert "example" not in repr(imported)


def test_fetches_the_bats_constituent_emitted_by_the_matrix() -> None:
    cboe = Instrument.create(
        symbol="CBOE",
        mic="BATS",
        currency="USD",
        exchange_timezone="America/New_York",
    )
    cboe_request = DailyBarFetchRequest(
        "us",
        cboe,
        date(2026, 7, 30),
        date(2026, 7, 31),
        Adjustment.RAW,
        {},
    )
    cboe_overview = overview() | {
        "Symbol": "CBOE",
        "Name": "Cboe Global Markets",
        "Exchange": "CBOE",
    }
    cboe_prices = raw_prices()
    metadata = cboe_prices["Meta Data"]
    assert isinstance(metadata, dict)
    metadata["2. Symbol"] = "CBOE"

    imported = source([response(cboe_overview), response(cboe_prices)]).fetch(cboe_request)

    assert imported.instrument == cboe
    assert len(imported.bars) == 2


def test_every_data_kind_rejects_a_provider_exchange_that_does_not_match_the_mic() -> None:
    wrong_mic = Instrument.create(
        symbol="MSFT", mic="XNYS", currency="USD", exchange_timezone="America/New_York"
    )
    assert_overview_rejected_for_every_data_kind(overview(), wrong_mic, "requested MIC")


def test_every_data_kind_rejects_non_equity_provider_assets() -> None:
    etf = overview() | {"AssetType": "ETF"}
    assert_overview_rejected_for_every_data_kind(etf, instrument(), "supported equity")


def test_adjusted_daily_bars_use_fixed_context_and_split_adjusted_volume() -> None:
    original = getcontext().prec
    try:
        getcontext().prec = 6
        first = source([response(overview()), response(adjusted_prices())]).fetch(
            request(Adjustment.ADJUSTED, {"plan": "premium"})
        )
        getcontext().prec = 50
        second = source([response(overview()), response(adjusted_prices())]).fetch(
            request(Adjustment.ADJUSTED, {"plan": "premium"})
        )
    finally:
        getcontext().prec = original

    assert first.bars == second.bars
    assert [bar.close for bar in first.bars] == [Decimal("52.5"), Decimal("56")]
    assert [bar.volume for bar in first.bars] == [2000, 1200]


@pytest.mark.parametrize(
    ("adjustment", "settings", "message"),
    (
        (Adjustment.ADJUSTED, {}, "require plan=premium"),
        (Adjustment.RAW, {"outputsize": "full"}, "requires plan=premium"),
    ),
)
def test_premium_daily_capabilities_fail_before_network(
    adjustment: Adjustment, settings: dict[str, str], message: str
) -> None:
    transport = FakeTransport([])
    provider = AlphaVantageSource(transport=transport, environ={"ALPHAVANTAGE_API_KEY": "example"})

    with pytest.raises(RuntimeError, match=message):
        provider.fetch(request(adjustment, settings))
    assert transport.calls == []


def test_compact_response_does_not_claim_an_uncovered_exact_range() -> None:
    end = date(2026, 7, 31)
    series = {
        (end - timedelta(days=index)).isoformat(): {
            "1. open": "1",
            "2. high": "1",
            "3. low": "1",
            "4. close": "1",
            "5. volume": "1",
        }
        for index in range(100)
    }
    prices = {"Meta Data": {"2. Symbol": "MSFT"}, "Time Series (Daily)": series}
    wide = DailyBarFetchRequest("us", instrument(), date(2025, 1, 1), end, Adjustment.RAW, {})

    with pytest.raises(RuntimeError, match="does not cover"):
        source([response(overview()), response(prices)]).fetch(wide)


def test_financial_statements_preserve_unknown_dimensions_and_provider_period() -> None:
    income = {
        "symbol": "MSFT",
        "annualReports": [
            {
                "fiscalDateEnding": "2025-12-31",
                "reportedCurrency": "USD",
                "totalRevenue": "1000",
                "operatingIncome": "300",
                "netIncome": "200",
            }
        ],
        "quarterlyReports": [],
    }
    balance = {
        "symbol": "MSFT",
        "annualReports": [
            {
                "fiscalDateEnding": "2025-12-31",
                "reportedCurrency": "USD",
                "totalAssets": "5000",
                "totalShareholderEquity": "2500",
                "shortLongTermDebtTotal": "400",
            }
        ],
        "quarterlyReports": [],
    }
    cash = {
        "symbol": "MSFT",
        "annualReports": [
            {
                "fiscalDateEnding": "2025-12-31",
                "reportedCurrency": "USD",
                "operatingCashflow": "350",
            }
        ],
        "quarterlyReports": [],
    }
    earnings = {
        "symbol": "MSFT",
        "annualEarnings": [{"fiscalDateEnding": "2025-12-31", "reportedEPS": "10.25"}],
        "quarterlyEarnings": [],
    }

    imported = source(
        [
            response(overview()),
            response(income),
            response(balance),
            response(cash),
            response(earnings),
        ]
    ).fetch_financials(fact_request())

    assert {fact.concept for fact in imported.facts} == {
        "revenue",
        "operating_income",
        "net_income",
        "eps",
        "operating_cash_flow",
        "assets",
        "equity",
        "interest_bearing_debt",
    }
    revenue = next(fact for fact in imported.facts if fact.concept == "revenue")
    assert revenue.fiscal_period_start is None
    assert revenue.period.value == "annual"
    assert revenue.provider_period == "annualReports"
    assert revenue.consolidation.value == "unknown"
    assert revenue.revision.value == "unknown"
    assert revenue.available_at == imported.retrieved_at
    assert "fiscal_period_start_not_provided" in imported.missing_reasons


def test_event_endpoints_are_explicit_and_use_retrieval_availability() -> None:
    earnings = {
        "symbol": "MSFT",
        "quarterlyEarnings": [
            {
                "fiscalDateEnding": "2026-06-30",
                "reportedDate": "2026-07-25",
                "reportedEPS": "2.5",
            }
        ],
    }
    dividends = {
        "symbol": "MSFT",
        "data": [
            {
                "declaration_date": "2026-07-01",
                "ex_dividend_date": "2026-07-20",
                "record_date": "2026-07-21",
                "payment_date": "2026-08-01",
                "amount": "0.75",
            }
        ],
    }
    splits = {"symbol": "MSFT", "data": [{"effective_date": "2026-07-10", "split_factor": "2:1"}]}
    selected = {"event_types": "earnings,dividend,split"}

    imported = source(
        [response(overview()), response(earnings), response(dividends), response(splits)]
    ).fetch_events(
        FactFetchRequest("us", instrument(), date(2026, 7, 1), date(2026, 7, 31), selected)
    )

    assert {event.event_type.value for event in imported.events} == {
        "earnings",
        "dividend",
        "split",
    }
    assert {event.availability_basis.value for event in imported.events} == {"retrieval"}
    assert imported.missing_reasons == ()


def test_default_event_selection_calls_only_earnings() -> None:
    transport = FakeTransport(
        [response(overview()), response({"symbol": "MSFT", "quarterlyEarnings": []})]
    )
    provider = AlphaVantageSource(
        transport=transport,
        environ={"ALPHAVANTAGE_API_KEY": "example"},
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    )

    imported = provider.fetch_events(fact_request())

    assert [call[1]["function"] for call in transport.calls] == ["OVERVIEW", "EARNINGS"]
    assert imported.missing_reasons == (
        "no_events_in_requested_period",
        "dividend_endpoint_not_selected",
        "split_endpoint_not_selected",
    )


def test_doctors_are_offline_and_validate_settings_and_credential() -> None:
    transport = FakeTransport([])
    missing = AlphaVantageSource(transport=transport, environ={}).doctor(configuration())
    ready = AlphaVantageSource(
        transport=transport, environ={"ALPHAVANTAGE_API_KEY": "example"}
    ).doctor(configuration({"plan": "premium", "outputsize": "full"}))
    invalid = AlphaVantageSource(transport=transport, environ={}).doctor_events(
        SourceConfiguration("USD", "America/New_York", {"event_types": "news"})
    )

    assert missing.code == "missing_credential"
    assert ready.ready is True
    assert invalid.code == "invalid_configuration"
    assert transport.calls == []


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({"Note": "secret provider message"}, "rate limit"),
        ({"Information": "secret provider message"}, "unavailable"),
        ({"Error Message": "secret provider message"}, "rejected"),
    ),
)
def test_provider_control_documents_are_explicit_and_redacted(
    payload: dict[str, str], message: str
) -> None:
    provider = source([response(payload)])

    with pytest.raises(RuntimeError, match=message) as raised:
        provider.fetch(request())
    assert "secret provider message" not in str(raised.value)
    assert "example" not in str(raised.value)


@pytest.mark.parametrize("status", (400, 401, 403, 429, 500))
def test_http_failures_do_not_retry_or_disclose_body(status: int) -> None:
    transport = FakeTransport([response({"detail": "secret"}, status)])
    provider = AlphaVantageSource(transport=transport, environ={"ALPHAVANTAGE_API_KEY": "example"})

    with pytest.raises(RuntimeError, match="not shortened or retried") as raised:
        provider.fetch(request())
    assert len(transport.calls) == 1
    assert "secret" not in str(raised.value)


def test_malformed_response_symbol_clock_and_credential_are_rejected() -> None:
    with pytest.raises(ValueError, match="valid JSON"):
        source([HttpResponse(200, b"not-json")]).fetch(request())
    wrong = overview() | {"Symbol": "AAPL"}
    with pytest.raises(ValueError, match="exact requested symbol"):
        source([response(wrong), response(raw_prices())]).fetch(request())
    naive = source([response(overview()), response(raw_prices())], clock=datetime(2026, 8, 1))
    with pytest.raises(ValueError, match="offset-aware"):
        naive.fetch(request())
    invalid_value = "line\nbreak"
    invalid = AlphaVantageSource(
        transport=FakeTransport([]), environ={"ALPHAVANTAGE_API_KEY": invalid_value}
    ).doctor(configuration())
    assert invalid.code == "invalid_credential"


def test_market_and_unknown_settings_are_rejected_before_network() -> None:
    transport = FakeTransport([])
    provider = AlphaVantageSource(transport=transport, environ={"ALPHAVANTAGE_API_KEY": "example"})
    unsupported = DailyBarFetchRequest(
        "us",
        Instrument.create(
            symbol="MSFT", mic="ARCX", currency="USD", exchange_timezone="America/New_York"
        ),
        date(2026, 7, 30),
        date(2026, 7, 31),
        Adjustment.RAW,
        {},
    )

    with pytest.raises(ValueError, match="BATS, XNAS, and XNYS"):
        provider.fetch(unsupported)
    assert (
        provider.doctor(configuration({"base_url": "https://attacker.invalid"})).code
        == "invalid_configuration"
    )
    assert provider.doctor(configuration({"unknown": "value"})).code == "invalid_configuration"
    assert transport.calls == []


@pytest.mark.parametrize(
    "settings",
    (
        {"timeout_seconds": "invalid"},
        {"timeout_seconds": "0"},
        {"timeout_seconds": "121"},
        {"plan": "enterprise"},
        {"outputsize": "medium"},
    ),
)
def test_invalid_daily_setting_values_are_diagnosed(settings: dict[str, str]) -> None:
    result = AlphaVantageSource(transport=FakeTransport([]), environ={}).doctor(
        configuration(settings)
    )

    assert result.code == "invalid_configuration"


@pytest.mark.parametrize(
    ("currency", "timezone"),
    (("JPY", "America/New_York"), ("USD", "UTC")),
)
def test_incompatible_market_profile_is_diagnosed(currency: str, timezone: str) -> None:
    result = AlphaVantageSource(transport=FakeTransport([]), environ={}).doctor(
        DailyBarSourceConfiguration(currency, timezone, {})
    )

    assert result.code == "invalid_configuration"


def test_missing_credential_fetch_is_rejected_before_network() -> None:
    transport = FakeTransport([])

    with pytest.raises(RuntimeError, match="missing credential"):
        AlphaVantageSource(transport=transport, environ={}).fetch(request())
    assert transport.calls == []


@pytest.mark.parametrize(
    ("prices", "message"),
    (
        ({"Meta Data": {"2. Symbol": "MSFT"}}, "time-series object"),
        (
            {
                "Meta Data": {"2. Symbol": "MSFT"},
                "Time Series (Daily)": {"not-a-date": {}},
            },
            "invalid date",
        ),
        (
            {
                "Meta Data": {"2. Symbol": "MSFT"},
                "Time Series (Daily)": {
                    "2026-07-31": {
                        "1. open": "invalid",
                        "2. high": "1",
                        "3. low": "1",
                        "4. close": "1",
                        "5. volume": "1",
                    }
                },
            },
            "invalid OHLCV",
        ),
        (
            {
                "Meta Data": {"2. Symbol": "MSFT"},
                "Time Series (Daily)": {
                    "2025-01-01": {
                        "1. open": "1",
                        "2. high": "1",
                        "3. low": "1",
                        "4. close": "1",
                        "5. volume": "1",
                    }
                },
            },
            "no daily bars",
        ),
    ),
)
def test_malformed_or_out_of_range_daily_payload_is_rejected(
    prices: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        source([response(overview()), response(prices)]).fetch(request())


@pytest.mark.parametrize("coefficient", ("invalid", "0"))
def test_invalid_split_coefficient_is_rejected(coefficient: str) -> None:
    prices = adjusted_prices()
    series = prices["Time Series (Daily)"]
    assert isinstance(series, dict)
    row = series["2026-07-31"]
    assert isinstance(row, dict)
    row["8. split coefficient"] = coefficient

    with pytest.raises(ValueError, match="split coefficient"):
        source([response(overview()), response(prices)]).fetch(
            request(Adjustment.ADJUSTED, {"plan": "premium"})
        )


def test_nonintegral_adjusted_volume_is_rejected() -> None:
    prices = adjusted_prices()
    series = prices["Time Series (Daily)"]
    assert isinstance(series, dict)
    row = series["2026-07-30"]
    assert isinstance(row, dict)
    row["6. volume"] = "0.25"

    with pytest.raises(ValueError, match="not integral"):
        source([response(overview()), response(prices)]).fetch(
            request(Adjustment.ADJUSTED, {"plan": "premium"})
        )


@pytest.mark.parametrize(
    ("adjustment", "field", "settings"),
    (
        (Adjustment.RAW, "5. volume", {}),
        (Adjustment.ADJUSTED, "6. volume", {"plan": "premium"}),
    ),
)
def test_nonfinite_volume_is_rejected_before_integer_conversion(
    adjustment: Adjustment, field: str, settings: dict[str, str]
) -> None:
    prices = adjusted_prices() if adjustment is Adjustment.ADJUSTED else raw_prices()
    series = prices["Time Series (Daily)"]
    assert isinstance(series, dict)
    row = series["2026-07-30"]
    assert isinstance(row, dict)
    row[field] = "Infinity"

    with pytest.raises(ValueError, match="volume must be finite"):
        source([response(overview()), response(prices)]).fetch(request(adjustment, settings))


def test_profile_uses_retrieval_date_when_provider_has_no_profile_publication_instant() -> None:
    profile = overview()
    profile.pop("LatestQuarter")
    imported = source([response(profile), response(raw_prices())]).fetch(request())
    assert imported.instrument_profile is not None
    assert imported.instrument_profile.observation_date == date(2026, 8, 1)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ({"annualReports": "invalid"}, "arrays of objects"),
        ({"annualReports": [{"fiscalDateEnding": "invalid"}]}, "period end"),
        (
            {
                "annualReports": [
                    {
                        "fiscalDateEnding": "2025-12-31",
                        "reportedCurrency": "EUR",
                        "totalRevenue": "1",
                    }
                ]
            },
            "currency",
        ),
        (
            {
                "annualReports": [
                    {
                        "fiscalDateEnding": "2025-12-31",
                        "reportedCurrency": "USD",
                        "totalRevenue": "invalid",
                    }
                ]
            },
            "financial value",
        ),
    ),
)
def test_malformed_financial_statement_is_rejected(
    mutation: dict[str, object], message: str
) -> None:
    income: dict[str, object] = {
        "symbol": "MSFT",
        "annualReports": [],
        "quarterlyReports": [],
    }
    income.update(mutation)
    empty_statement = {"symbol": "MSFT", "annualReports": [], "quarterlyReports": []}
    empty_earnings = {"symbol": "MSFT", "annualEarnings": [], "quarterlyEarnings": []}

    with pytest.raises(ValueError, match=message):
        source(
            [
                response(overview()),
                response(income),
                response(empty_statement),
                response(empty_statement),
                response(empty_earnings),
            ]
        ).fetch_financials(fact_request())


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({"symbol": "MSFT", "quarterlyEarnings": "invalid"}, "earnings"),
        (
            {"symbol": "MSFT", "quarterlyEarnings": [{"reportedDate": "invalid"}]},
            "report date",
        ),
    ),
)
def test_malformed_earnings_event_is_rejected(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        source([response(overview()), response(payload)]).fetch_events(fact_request())


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({"symbol": "MSFT", "data": "invalid"}, "corporate actions"),
        ({"symbol": "MSFT", "data": [{"effective_date": "invalid"}]}, "action date"),
    ),
)
def test_malformed_split_event_is_rejected(payload: dict[str, object], message: str) -> None:
    selected = {"event_types": "split"}
    request_value = FactFetchRequest(
        "us", instrument(), date(2026, 7, 1), date(2026, 7, 31), selected
    )
    with pytest.raises(ValueError, match=message):
        source([response(overview()), response(payload)]).fetch_events(request_value)


def test_json_array_response_is_rejected() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        source([response([])]).fetch(request())


def test_redirects_are_rejected() -> None:
    handler = _NoRedirect()
    handler.redirect_request(
        Request("https://www.alphavantage.co/query"),
        None,
        302,
        "Found",
        {},
        "https://attacker.invalid",
    )
