"""Credential-safe Alpha Vantage equity acquisition."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from marketsieve.data.daily import Adjustment, DailyBar, Provenance
from marketsieve.domain import Instrument
from marketsieve_extension_api import (
    AvailabilityBasis,
    Consolidation,
    CorporateEvent,
    CorporateEventType,
    DailyBarFetcher,
    DailyBarFetchRequest,
    DailyBarSourceConfiguration,
    EventFetcher,
    FactFetchRequest,
    FinancialFact,
    FinancialFetcher,
    FinancialPeriod,
    ImportedDailyBars,
    ImportedEvents,
    ImportedFinancials,
    InstrumentProfile,
    Revision,
    SourceConfiguration,
    SourceDiagnostic,
)

API_URL = "https://www.alphavantage.co/query"
API_KEY_ENV = "ALPHAVANTAGE_API_KEY"
SOURCE_VERSION = "alphavantage-query-api-v1"
SUPPORTED_MICS = frozenset({"XNAS", "XNYS"})
PROVIDER_EXCHANGES = {"NASDAQ": "XNAS", "NYSE": "XNYS"}
SUPPORTED_ASSET_TYPES = frozenset({"COMMON STOCK"})
NUMERIC_CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def get(
        self, url: str, *, query: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> HttpResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibTransport:
    def __init__(self, opener: OpenerDirector | None = None) -> None:
        self._opener = opener or build_opener(_NoRedirect())

    def get(
        self, url: str, *, query: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        request = Request(f"{url}?{urlencode(query)}", headers=dict(headers), method="GET")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.read())
        except HTTPError as error:
            return HttpResponse(error.code, error.read())
        except (TimeoutError, URLError):
            raise RuntimeError("Alpha Vantage request failed before receiving a response") from None


class AlphaVantageSource(DailyBarFetcher, FinancialFetcher, EventFetcher):
    """Fetch explicitly configured U.S. equity facts without fallback."""

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or UrllibTransport()
        self._environ = environ if environ is not None else os.environ
        self._clock = clock or (lambda: datetime.now(UTC))

    def doctor(self, configuration: DailyBarSourceConfiguration) -> SourceDiagnostic:
        return self._doctor(
            configuration.currency, configuration.timezone, configuration.settings, "daily"
        )

    def doctor_financials(self, configuration: SourceConfiguration) -> SourceDiagnostic:
        return self._doctor(
            configuration.currency, configuration.timezone, configuration.settings, "financials"
        )

    def doctor_events(self, configuration: SourceConfiguration) -> SourceDiagnostic:
        return self._doctor(
            configuration.currency, configuration.timezone, configuration.settings, "events"
        )

    def _doctor(
        self, currency: str, timezone: str, settings: Mapping[str, str], kind: str
    ) -> SourceDiagnostic:
        try:
            self._validate_market(currency, timezone)
            self._settings(settings, kind)
            if kind == "events":
                self._event_types(settings)
        except ValueError as error:
            return SourceDiagnostic(
                False, "invalid_configuration", str(error), "Fix marketsieve.toml."
            )
        try:
            credential = self._credential()
        except ValueError as error:
            return SourceDiagnostic(
                False, "invalid_credential", str(error), f"Set a valid {API_KEY_ENV} value."
            )
        if credential is None:
            return SourceDiagnostic(
                False,
                "missing_credential",
                f"Environment variable {API_KEY_ENV} is not set.",
                f"Set {API_KEY_ENV} for this command without writing it to a file.",
            )
        return SourceDiagnostic(True, "ready", "Alpha Vantage source is configured.")

    def fetch(self, request: DailyBarFetchRequest) -> ImportedDailyBars:
        timeout, plan, outputsize, _ = self._context(request, "daily")
        if request.adjustment is Adjustment.ADJUSTED and plan != "premium":
            raise RuntimeError("Alpha Vantage adjusted daily bars require plan=premium")
        if outputsize == "full" and plan != "premium":
            raise RuntimeError("Alpha Vantage outputsize=full requires plan=premium")
        overview, overview_body = self._query("OVERVIEW", request.instrument.symbol, timeout)
        self._validate_overview_identity(overview, request.instrument)
        function = (
            "TIME_SERIES_DAILY_ADJUSTED"
            if request.adjustment is Adjustment.ADJUSTED
            else "TIME_SERIES_DAILY"
        )
        prices, prices_body = self._query(
            function, request.instrument.symbol, timeout, outputsize=outputsize
        )
        retrieved_at = self._retrieved_at()
        bars = self._bars(prices, request, retrieved_at, outputsize)
        profile = self._profile(overview, request.instrument, retrieved_at.date())
        return ImportedDailyBars(
            request.source_profile,
            "alphavantage",
            SOURCE_VERSION,
            (
                f"OVERVIEW+{function}:ohlc-adjusted-close-factor:volume-split-factor"
                if request.adjustment is Adjustment.ADJUSTED
                else f"OVERVIEW+{function}"
            ),
            request.instrument,
            request.adjustment,
            retrieved_at,
            AvailabilityBasis.RETRIEVAL,
            bars,
            self._response_hash((overview_body, prices_body)),
            profile,
            request,
        )

    def fetch_financials(self, request: FactFetchRequest) -> ImportedFinancials:
        timeout, _, _, _ = self._context(request, "financials")
        overview, overview_body = self._query("OVERVIEW", request.instrument.symbol, timeout)
        self._validate_overview_identity(overview, request.instrument)
        responses = [
            self._query(function, request.instrument.symbol, timeout)
            for function in ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS")
        ]
        retrieved_at = self._retrieved_at()
        self._profile(overview, request.instrument, retrieved_at.date())
        facts = self._financial_facts(
            tuple(document for document, _ in responses), request, retrieved_at
        )
        concepts = {fact.concept for fact in facts}
        reasons = tuple(
            reason
            for concept, reason in (
                ("revenue", "revenue_not_present_in_selected_statements"),
                ("operating_income", "operating_income_not_present_in_selected_statements"),
                ("net_income", "net_income_not_present_in_selected_statements"),
                ("eps", "eps_not_present_in_selected_statements"),
                ("operating_cash_flow", "operating_cash_flow_not_present_in_selected_statements"),
                ("assets", "assets_not_present_in_selected_statements"),
                ("equity", "equity_not_present_in_selected_statements"),
                ("interest_bearing_debt", "debt_not_present_in_selected_statements"),
            )
            if concept not in concepts
        )
        reasons = (
            *(("no_financial_facts_in_requested_period",) if not facts else ()),
            *reasons,
            "fiscal_period_start_not_provided",
            "accounting_standard_not_identified",
            "consolidation_basis_not_identified",
            "revision_state_not_identified",
            "publication_instant_not_provided",
        )
        return ImportedFinancials(
            request,
            "alphavantage",
            SOURCE_VERSION,
            "OVERVIEW+INCOME_STATEMENT+BALANCE_SHEET+CASH_FLOW+EARNINGS",
            retrieved_at,
            facts,
            self._response_hash((overview_body, *(body for _, body in responses))),
            reasons,
        )

    def fetch_events(self, request: FactFetchRequest) -> ImportedEvents:
        timeout, _, _, event_types = self._context(request, "events")
        selected = self._event_types(request.settings)
        overview, overview_body = self._query("OVERVIEW", request.instrument.symbol, timeout)
        self._validate_overview_identity(overview, request.instrument)
        responses = {
            event_type: self._query(function, request.instrument.symbol, timeout)
            for event_type, function in (
                ("earnings", "EARNINGS"),
                ("dividend", "DIVIDENDS"),
                ("split", "SPLITS"),
            )
            if event_type in selected
        }
        retrieved_at = self._retrieved_at()
        self._profile(overview, request.instrument, retrieved_at.date())
        events = self._events(
            {key: document for key, (document, _) in responses.items()}, request, retrieved_at
        )
        missing = tuple(
            reason
            for event_type, reason in (
                ("earnings", "earnings_endpoint_not_selected"),
                ("dividend", "dividend_endpoint_not_selected"),
                ("split", "split_endpoint_not_selected"),
            )
            if event_type not in selected
        )
        if not events:
            missing = ("no_events_in_requested_period", *missing)
        return ImportedEvents(
            request,
            "alphavantage",
            SOURCE_VERSION,
            "+".join(("OVERVIEW", *event_types)),
            retrieved_at,
            events,
            self._response_hash((overview_body, *(body for _, body in responses.values()))),
            missing,
        )

    def _context(
        self, request: DailyBarFetchRequest | FactFetchRequest, kind: str
    ) -> tuple[float, str, str, tuple[str, ...]]:
        if request.instrument.mic not in SUPPORTED_MICS:
            raise ValueError("Alpha Vantage source supports XNAS and XNYS instruments")
        self._validate_market(request.instrument.currency, request.instrument.exchange_timezone.key)
        timeout, plan, outputsize = self._settings(request.settings, kind)
        credential = self._credential()
        if credential is None:
            raise RuntimeError(f"missing credential; set {API_KEY_ENV}")
        events = tuple(sorted(self._event_types(request.settings))) if kind == "events" else ()
        return timeout, plan, outputsize, events

    def _query(
        self, function: str, symbol: str, timeout: float, *, outputsize: str | None = None
    ) -> tuple[dict[str, Any], bytes]:
        credential = self._credential()
        if credential is None:
            raise RuntimeError(f"missing credential; set {API_KEY_ENV}")
        query = {"function": function, "symbol": symbol, "apikey": credential}
        if outputsize is not None:
            query["outputsize"] = outputsize
        response = self._transport.get(
            API_URL, query=query, headers={"Accept": "application/json"}, timeout=timeout
        )
        self._raise_for_status(response)
        return self._document(response.body), response.body

    @classmethod
    def _bars(
        cls,
        document: Mapping[str, Any],
        request: DailyBarFetchRequest,
        retrieved_at: datetime,
        outputsize: str,
    ) -> tuple[DailyBar, ...]:
        cls._validate_symbol(document, request.instrument.symbol)
        raw_series = document.get("Time Series (Daily)")
        if not isinstance(raw_series, dict) or any(
            not isinstance(key, str) or not isinstance(value, dict)
            for key, value in raw_series.items()
        ):
            raise ValueError("Alpha Vantage daily response must contain a time-series object")
        parsed_dates: list[date] = []
        for raw_date in raw_series:
            try:
                parsed_dates.append(date.fromisoformat(raw_date))
            except ValueError as error:
                raise ValueError("Alpha Vantage daily response contains an invalid date") from error
        if (
            outputsize == "compact"
            and len(parsed_dates) >= 100
            and request.start < min(parsed_dates)
        ):
            raise RuntimeError(
                "Alpha Vantage compact response does not cover the exact requested range; "
                "select outputsize=full with plan=premium"
            )
        split_products = (
            cls._split_products(raw_series) if request.adjustment is Adjustment.ADJUSTED else {}
        )
        bars: list[DailyBar] = []
        for trading_date, raw_date in sorted(zip(parsed_dates, raw_series, strict=True)):
            if not request.start <= trading_date <= request.end:
                continue
            row = raw_series[raw_date]
            try:
                raw_prices = tuple(
                    Decimal(str(row[f"{index}. {name}"]))
                    for index, name in enumerate(("open", "high", "low", "close"), 1)
                )
                raw_volume = Decimal(
                    str(
                        row[
                            "6. volume"
                            if request.adjustment is Adjustment.ADJUSTED
                            else "5. volume"
                        ]
                    )
                )
                if request.adjustment is Adjustment.ADJUSTED:
                    adjusted_close = Decimal(str(row["5. adjusted close"]))
                    with localcontext(NUMERIC_CONTEXT):
                        factor = adjusted_close / raw_prices[3]
                        prices = (*(+(value * factor) for value in raw_prices[:3]), adjusted_close)
                        volume = +(raw_volume * split_products[raw_date])
                else:
                    prices = raw_prices
                    volume = raw_volume
            except (KeyError, InvalidOperation, ZeroDivisionError) as error:
                raise ValueError(
                    "Alpha Vantage daily response contains an invalid OHLCV value"
                ) from error
            if not volume.is_finite():
                raise ValueError("Alpha Vantage daily-bar volume must be finite")
            if volume != volume.to_integral_value():
                raise ValueError("Alpha Vantage adjusted volume is not integral")
            bars.append(
                DailyBar(
                    trading_date,
                    prices[0],
                    prices[1],
                    prices[2],
                    prices[3],
                    int(volume),
                    request.adjustment,
                    retrieved_at,
                    Provenance(
                        "alphavantage",
                        (
                            "TIME_SERIES_DAILY_ADJUSTED:ohlc-adjusted-close-factor:"
                            "volume-split-factor"
                            if request.adjustment is Adjustment.ADJUSTED
                            else "TIME_SERIES_DAILY"
                        ),
                        SOURCE_VERSION,
                    ),
                )
            )
        if not bars:
            raise ValueError("Alpha Vantage returned no daily bars for the exact requested range")
        if len({bar.trading_date for bar in bars}) != len(bars):
            raise ValueError("Alpha Vantage returned duplicate daily-bar dates")
        return tuple(bars)

    @staticmethod
    def _split_products(series: Mapping[str, Any]) -> dict[str, Decimal]:
        products: dict[str, Decimal] = {}
        cumulative = Decimal(1)
        for raw_date in sorted(series, reverse=True):
            products[raw_date] = cumulative
            try:
                coefficient = Decimal(str(series[raw_date]["8. split coefficient"]))
            except (KeyError, InvalidOperation) as error:
                raise ValueError(
                    "Alpha Vantage adjusted response has an invalid split coefficient"
                ) from error
            if not coefficient.is_finite() or coefficient <= 0:
                raise ValueError("Alpha Vantage split coefficient must be finite and positive")
            with localcontext(NUMERIC_CONTEXT):
                cumulative = +(cumulative * coefficient)
        return products

    @classmethod
    def _profile(
        cls, overview: Mapping[str, Any], instrument: Instrument, retrieved_on: date
    ) -> InstrumentProfile:
        cls._validate_overview_identity(overview, instrument)
        names = (("en", str(overview["Name"])),) if overview.get("Name") else ()
        attributes = tuple(
            (name, str(overview[field]))
            for name, field in (
                ("asset_type", "AssetType"),
                ("exchange", "Exchange"),
                ("country", "Country"),
                ("sector", "Sector"),
                ("industry", "Industry"),
                ("trailing_per", "PERatio"),
                ("price_to_book", "PriceToBookRatio"),
                ("price_to_sales_ttm", "PriceToSalesRatioTTM"),
                ("dividend_yield", "DividendYield"),
                ("market_capitalization", "MarketCapitalization"),
            )
            if overview.get(field)
        )
        return InstrumentProfile(retrieved_on, None, names, attributes)

    @staticmethod
    def _validate_overview_identity(overview: Mapping[str, Any], instrument: Instrument) -> None:
        if str(overview.get("Symbol", "")) != instrument.symbol:
            raise ValueError("Alpha Vantage overview did not identify the exact requested symbol")
        provider_exchange = str(overview.get("Exchange", "")).upper()
        if PROVIDER_EXCHANGES.get(provider_exchange) != instrument.mic:
            raise ValueError("Alpha Vantage overview exchange does not match the requested MIC")
        asset_type = str(overview.get("AssetType", "")).upper()
        if asset_type not in SUPPORTED_ASSET_TYPES:
            raise ValueError("Alpha Vantage overview asset type is not a supported equity")

    @classmethod
    def _financial_facts(
        cls,
        documents: tuple[Mapping[str, Any], ...],
        request: FactFetchRequest,
        retrieved_at: datetime,
    ) -> tuple[FinancialFact, ...]:
        mappings = (
            {
                "totalRevenue": "revenue",
                "operatingIncome": "operating_income",
                "netIncome": "net_income",
            },
            {
                "totalAssets": "assets",
                "totalShareholderEquity": "equity",
                "shortLongTermDebtTotal": "interest_bearing_debt",
            },
            {"operatingCashflow": "operating_cash_flow"},
            {"reportedEPS": "eps"},
        )
        facts: list[FinancialFact] = []
        for document, mapping in zip(documents, mappings, strict=True):
            cls._validate_symbol(document, request.instrument.symbol)
            for list_name, period in (
                (
                    "annualReports" if "annualReports" in document else "annualEarnings",
                    FinancialPeriod.ANNUAL,
                ),
                (
                    "quarterlyReports" if "quarterlyReports" in document else "quarterlyEarnings",
                    FinancialPeriod.QUARTERLY,
                ),
            ):
                rows = document.get(list_name, [])
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("Alpha Vantage financial reports must be arrays of objects")
                for row in rows:
                    try:
                        period_end = date.fromisoformat(str(row["fiscalDateEnding"]))
                    except (KeyError, ValueError) as error:
                        raise ValueError("Alpha Vantage fiscal period end is invalid") from error
                    if not request.start <= period_end <= request.end:
                        continue
                    currency = str(row.get("reportedCurrency") or request.instrument.currency)
                    if currency != request.instrument.currency:
                        raise ValueError(
                            "Alpha Vantage financial currency does not match the instrument"
                        )
                    for provider_fact, concept in mapping.items():
                        raw = row.get(provider_fact)
                        if raw in (None, "", "None"):
                            continue
                        try:
                            value = Decimal(str(raw))
                        except InvalidOperation as error:
                            raise ValueError("Alpha Vantage financial value is invalid") from error
                        facts.append(
                            FinancialFact(
                                concept,
                                provider_fact,
                                None,
                                period,
                                list_name,
                                None,
                                period_end,
                                None,
                                retrieved_at,
                                AvailabilityBasis.RETRIEVAL,
                                Consolidation.UNKNOWN,
                                Revision.UNKNOWN,
                                currency,
                                1,
                                value,
                            )
                        )
        return tuple(
            sorted(facts, key=lambda fact: (fact.fiscal_period_end, fact.period, fact.concept))
        )

    @classmethod
    def _events(
        cls,
        documents: Mapping[str, Mapping[str, Any]],
        request: FactFetchRequest,
        retrieved_at: datetime,
    ) -> tuple[CorporateEvent, ...]:
        events: list[CorporateEvent] = []
        earnings = documents.get("earnings")
        if earnings is not None:
            cls._validate_symbol(earnings, request.instrument.symbol)
            rows = earnings.get("quarterlyEarnings")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Alpha Vantage earnings must be an array of objects")
            for row in rows:
                try:
                    reported = date.fromisoformat(str(row["reportedDate"]))
                except (KeyError, ValueError) as error:
                    raise ValueError("Alpha Vantage earnings report date is invalid") from error
                if request.start <= reported <= request.end:
                    events.append(
                        CorporateEvent(
                            CorporateEventType.EARNINGS,
                            reported,
                            reported,
                            None,
                            retrieved_at,
                            AvailabilityBasis.RETRIEVAL,
                            tuple(
                                (name, str(row[field]))
                                for name, field in (
                                    ("fiscal_date_ending", "fiscalDateEnding"),
                                    ("reported_eps", "reportedEPS"),
                                    ("estimated_eps", "estimatedEPS"),
                                    ("surprise", "surprise"),
                                    ("surprise_percentage", "surprisePercentage"),
                                )
                                if row.get(field) not in (None, "", "None")
                            ),
                        )
                    )
        for event_type, key, date_field, value_fields in (
            (
                CorporateEventType.DIVIDEND,
                "dividend",
                "ex_dividend_date",
                (
                    ("amount", "amount"),
                    ("payment_date", "payment_date"),
                    ("record_date", "record_date"),
                ),
            ),
            (
                CorporateEventType.SPLIT,
                "split",
                "effective_date",
                (("split_factor", "split_factor"),),
            ),
        ):
            document = documents.get(key)
            if document is None:
                continue
            cls._validate_symbol(document, request.instrument.symbol, optional=True)
            rows = document.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Alpha Vantage corporate actions must be arrays of objects")
            for row in rows:
                try:
                    effective = date.fromisoformat(str(row[date_field]))
                except (KeyError, ValueError) as error:
                    raise ValueError("Alpha Vantage corporate action date is invalid") from error
                if not request.start <= effective <= request.end:
                    continue
                observation = effective
                if event_type is CorporateEventType.DIVIDEND and row.get("declaration_date"):
                    try:
                        observation = date.fromisoformat(str(row["declaration_date"]))
                    except ValueError as error:
                        raise ValueError(
                            "Alpha Vantage dividend declaration date is invalid"
                        ) from error
                events.append(
                    CorporateEvent(
                        event_type,
                        observation,
                        effective,
                        None,
                        retrieved_at,
                        AvailabilityBasis.RETRIEVAL,
                        tuple(
                            (name, str(row[field]))
                            for name, field in value_fields
                            if row.get(field) not in (None, "", "None")
                        ),
                    )
                )
        return tuple(sorted(events, key=lambda event: (event.effective_date, event.event_type)))

    @staticmethod
    def _validate_symbol(
        document: Mapping[str, Any], expected: str, *, optional: bool = False
    ) -> None:
        symbol = document.get("symbol") or document.get("Symbol")
        if symbol is None:
            metadata = document.get("Meta Data")
            symbol = metadata.get("2. Symbol") if isinstance(metadata, dict) else None
        if symbol is None and optional:
            return
        if str(symbol) != expected:
            raise ValueError("Alpha Vantage returned a different symbol than requested")

    @staticmethod
    def _event_types(settings: Mapping[str, str]) -> frozenset[str]:
        selected = frozenset(
            item.strip() for item in settings.get("event_types", "earnings").split(",")
        )
        if not selected or not selected <= {"earnings", "dividend", "split"}:
            raise ValueError(
                "Alpha Vantage event_types must select earnings, dividend, and/or split"
            )
        return selected

    @staticmethod
    def _settings(settings: Mapping[str, str], kind: str) -> tuple[float, str, str]:
        allowed = {"base_url", "timeout_seconds", "plan"}
        if kind == "daily":
            allowed.add("outputsize")
        if kind == "events":
            allowed.add("event_types")
        unknown = set(settings) - allowed
        if unknown:
            raise ValueError(f"unsupported Alpha Vantage settings: {', '.join(sorted(unknown))}")
        if settings.get("base_url", API_URL).rstrip("/") != API_URL:
            raise ValueError(f"Alpha Vantage base_url must be {API_URL}")
        try:
            timeout = float(settings.get("timeout_seconds", "30"))
        except ValueError as error:
            raise ValueError("Alpha Vantage timeout_seconds must be numeric") from error
        if not 0 < timeout <= 120:
            raise ValueError("Alpha Vantage timeout_seconds must be greater than 0 and at most 120")
        plan = settings.get("plan", "free")
        if plan not in {"free", "premium"}:
            raise ValueError("Alpha Vantage plan must be free or premium")
        outputsize = settings.get("outputsize", "compact")
        if outputsize not in {"compact", "full"}:
            raise ValueError("Alpha Vantage outputsize must be compact or full")
        return timeout, plan, outputsize

    @staticmethod
    def _validate_market(currency: str, timezone: str) -> None:
        if currency != "USD":
            raise ValueError("Alpha Vantage U.S. instruments must use USD")
        if timezone != "America/New_York":
            raise ValueError("Alpha Vantage U.S. instruments must use America/New_York")

    def _credential(self) -> str | None:
        value = self._environ.get(API_KEY_ENV)
        if not value:
            return None
        if any(not 0x21 <= ord(character) <= 0x7E for character in value):
            raise ValueError("Alpha Vantage credential contains invalid URL characters")
        return value

    def _retrieved_at(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source clock must return an offset-aware datetime")
        return value

    @staticmethod
    def _raise_for_status(response: HttpResponse) -> None:
        if response.status == 200:
            return
        meaning = {
            400: "request was rejected",
            401: "API key was rejected",
            403: "plan does not permit the exact request",
            429: "rate limit was exceeded",
        }.get(response.status, "provider failed")
        raise RuntimeError(
            f"Alpha Vantage {meaning} (HTTP {response.status}); "
            "request was not shortened or retried"
        )

    @staticmethod
    def _document(body: bytes) -> dict[str, Any]:
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Alpha Vantage response is not valid JSON") from error
        if not isinstance(document, dict):
            raise ValueError("Alpha Vantage response must be a JSON object")
        if "Note" in document:
            raise RuntimeError("Alpha Vantage rate limit was exceeded; request was not retried")
        if "Information" in document:
            raise RuntimeError(
                "Alpha Vantage exact request is unavailable for the configured key or plan"
            )
        if "Error Message" in document:
            raise RuntimeError("Alpha Vantage rejected the exact request")
        return document

    @staticmethod
    def _response_hash(bodies: tuple[bytes, ...]) -> str:
        digest = hashlib.sha256()
        for body in bodies:
            digest.update(hashlib.sha256(body).digest())
        return digest.hexdigest()
