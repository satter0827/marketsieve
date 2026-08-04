"""Credential-safe J-Quants API V2 daily-bar acquisition."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener
from zoneinfo import ZoneInfo

from marketsieve.data.daily import Adjustment, DailyBar, Provenance
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

API_BASE_URL = "https://api.jquants.com/v2"
API_KEY_ENV = "JQUANTS_API_KEY"
SOURCE_VERSION = "jquants-api-v2"
MAX_PAGES = 1000


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
        """Reject redirects so credential headers never reach another origin."""

        return None


class UrllibTransport:
    """Small standard-library transport; provider tests inject a fake instead."""

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
        except (TimeoutError, URLError) as error:
            raise RuntimeError("J-Quants request failed before receiving a response") from error


class JQuantsSource(DailyBarFetcher, FinancialFetcher, EventFetcher):
    """Fetch exact TSE daily bars and matching instrument profile facts."""

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
        return self._doctor(configuration.currency, configuration.timezone, configuration.settings)

    def doctor_financials(self, configuration: SourceConfiguration) -> SourceDiagnostic:
        return self._doctor(configuration.currency, configuration.timezone, configuration.settings)

    def doctor_events(self, configuration: SourceConfiguration) -> SourceDiagnostic:
        return self._doctor(
            configuration.currency,
            configuration.timezone,
            configuration.settings,
            validate_event_types=True,
        )

    def _doctor(
        self,
        currency: str,
        timezone: str,
        settings: Mapping[str, str],
        *,
        validate_event_types: bool = False,
    ) -> SourceDiagnostic:
        try:
            self._validate_market(currency, timezone)
            self._validated_settings(settings, allow_event_types=validate_event_types)
            if validate_event_types:
                self._event_types(settings)
        except ValueError as error:
            return SourceDiagnostic(
                False, "invalid_configuration", str(error), "Fix marketsieve.toml."
            )
        try:
            api_key = self._credential()
        except ValueError as error:
            return SourceDiagnostic(
                False,
                "invalid_credential",
                str(error),
                f"Set a valid {API_KEY_ENV} value for this command.",
            )
        if api_key is None:
            return SourceDiagnostic(
                False,
                "missing_credential",
                f"Environment variable {API_KEY_ENV} is not set.",
                f"Set {API_KEY_ENV} for this command without writing it to a file.",
            )
        return SourceDiagnostic(True, "ready", "J-Quants source is configured.")

    def fetch(self, request: DailyBarFetchRequest) -> ImportedDailyBars:
        if request.instrument.mic != "XTKS":
            raise ValueError("J-Quants daily bars support only XTKS instruments")
        self._validate_market(request.instrument.currency, request.instrument.exchange_timezone.key)
        base_url, timeout = self._validated_settings(request.settings)
        try:
            api_key = self._credential()
        except ValueError as error:
            raise RuntimeError(str(error)) from None
        if api_key is None:
            raise RuntimeError(f"missing credential; set {API_KEY_ENV}")
        headers = {"Accept": "application/json"}
        headers["x-api-key"] = api_key
        code = request.instrument.symbol
        profile_rows, profile_bodies = self._pages(
            f"{base_url}/equities/master", {"code": code}, headers, timeout
        )
        profile = self._profile(profile_rows, code)
        price_rows, price_bodies = self._pages(
            f"{base_url}/equities/bars/daily",
            {"code": code, "from": request.start.isoformat(), "to": request.end.isoformat()},
            headers,
            timeout,
        )
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("source clock must return an offset-aware datetime")
        bars = self._bars(price_rows, request, retrieved_at)
        if not bars:
            raise ValueError(
                "J-Quants returned no tradable daily bars for the exact requested range"
            )
        digest = hashlib.sha256()
        for body in (*profile_bodies, *price_bodies):
            digest.update(hashlib.sha256(body).digest())
        return ImportedDailyBars(
            source_profile=request.source_profile,
            source_name="jquants",
            source_version=SOURCE_VERSION,
            dataset="equities/master+equities/bars/daily",
            instrument=request.instrument,
            adjustment=request.adjustment,
            retrieved_at=retrieved_at,
            availability_basis=AvailabilityBasis.RETRIEVAL,
            bars=bars,
            bundle_hash=digest.hexdigest(),
            instrument_profile=profile,
            fetch_request=request,
        )

    def fetch_financials(self, request: FactFetchRequest) -> ImportedFinancials:
        base_url, timeout, headers = self._fact_request_context(request)
        rows, bodies = self._pages(
            f"{base_url}/fins/summary",
            {"code": request.instrument.symbol},
            headers,
            timeout,
        )
        retrieved_at = self._retrieved_at()
        facts = self._financial_facts(rows, request, retrieved_at)
        concepts = {fact.concept for fact in facts}
        reasons = (
            *(
                reason
                for concept, reason in (
                    ("revenue", "revenue_not_present_in_summary"),
                    ("operating_income", "operating_income_not_present_in_summary"),
                    ("net_income", "net_income_not_present_in_summary"),
                    ("eps", "eps_not_present_in_summary"),
                    ("operating_cash_flow", "operating_cash_flow_not_present_in_summary"),
                    ("assets", "assets_not_present_in_summary"),
                    ("equity", "equity_not_present_in_summary"),
                    ("interest_bearing_debt", "interest_bearing_debt_not_present_in_summary"),
                )
                if concept not in concepts
            ),
            "accounting_standard_not_provided_by_summary",
        )
        if not facts:
            reasons = ("no_financial_facts_in_requested_period", *reasons)
        return ImportedFinancials(
            request=request,
            source_name="jquants",
            source_version=SOURCE_VERSION,
            dataset="fins/summary",
            retrieved_at=retrieved_at,
            facts=facts,
            response_hash=self._response_hash(bodies),
            missing_reasons=reasons,
        )

    def fetch_events(self, request: FactFetchRequest) -> ImportedEvents:
        base_url, timeout, headers = self._fact_request_context(request, allow_event_types=True)
        event_types = self._event_types(request.settings)
        dividend_rows: list[dict[str, Any]] = []
        dividend_bodies: list[bytes] = []
        earnings_rows: list[dict[str, Any]] = []
        earnings_bodies: list[bytes] = []
        if "dividend" in event_types:
            dividend_rows, dividend_bodies = self._pages(
                f"{base_url}/fins/dividend",
                {
                    "code": request.instrument.symbol,
                    "from": request.start.isoformat(),
                    "to": request.end.isoformat(),
                },
                headers,
                timeout,
            )
        if "earnings" in event_types:
            earnings_rows, earnings_bodies = self._pages(
                f"{base_url}/equities/earnings-calendar", {}, headers, timeout
            )
        retrieved_at = self._retrieved_at()
        events = self._events(dividend_rows, earnings_rows, request, retrieved_at)
        return ImportedEvents(
            request=request,
            source_name="jquants",
            source_version=SOURCE_VERSION,
            dataset="+".join(
                endpoint
                for event_type, endpoint in (
                    ("dividend", "fins/dividend"),
                    ("earnings", "equities/earnings-calendar"),
                )
                if event_type in event_types
            ),
            retrieved_at=retrieved_at,
            events=events,
            response_hash=self._response_hash((*dividend_bodies, *earnings_bodies)),
            missing_reasons=tuple(
                reason
                for event_type, reason in (
                    ("dividend", "dividend_endpoint_not_selected"),
                    ("earnings", "earnings_endpoint_not_selected"),
                    ("split", "split_events_not_provided_by_selected_jquants_endpoints"),
                )
                if event_type not in event_types
            ),
        )

    def _fact_request_context(
        self, request: FactFetchRequest, *, allow_event_types: bool = False
    ) -> tuple[str, float, dict[str, str]]:
        if request.instrument.mic != "XTKS":
            raise ValueError("J-Quants facts support only XTKS instruments")
        self._validate_market(request.instrument.currency, request.instrument.exchange_timezone.key)
        base_url, timeout = self._validated_settings(
            request.settings, allow_event_types=allow_event_types
        )
        try:
            api_key = self._credential()
        except ValueError as error:
            raise RuntimeError(str(error)) from None
        if api_key is None:
            raise RuntimeError(f"missing credential; set {API_KEY_ENV}")
        headers = {"Accept": "application/json"}
        headers["x-api-key"] = api_key
        return base_url, timeout, headers

    def _retrieved_at(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source clock must return an offset-aware datetime")
        return value

    @staticmethod
    def _event_types(settings: Mapping[str, str]) -> frozenset[str]:
        selected = frozenset(
            item.strip() for item in settings.get("event_types", "earnings").split(",")
        )
        if not selected or not selected <= {"earnings", "dividend"}:
            raise ValueError("J-Quants event_types must select earnings and/or dividend")
        return selected

    @staticmethod
    def _response_hash(bodies: tuple[bytes, ...] | list[bytes]) -> str:
        digest = hashlib.sha256()
        for body in bodies:
            digest.update(hashlib.sha256(body).digest())
        return digest.hexdigest()

    @classmethod
    def _financial_facts(
        cls,
        rows: list[dict[str, Any]],
        request: FactFetchRequest,
        retrieved_at: datetime,
    ) -> tuple[FinancialFact, ...]:
        mappings = (
            (
                Consolidation.CONSOLIDATED,
                {
                    "Sales": "revenue",
                    "OP": "operating_income",
                    "NP": "net_income",
                    "EPS": "eps",
                    "CFO": "operating_cash_flow",
                    "TA": "assets",
                    "Eq": "equity",
                },
            ),
            (
                Consolidation.NON_CONSOLIDATED,
                {
                    "NCSales": "revenue",
                    "NCOP": "operating_income",
                    "NCNP": "net_income",
                    "NCEPS": "eps",
                    "NCTA": "assets",
                    "NCEq": "equity",
                },
            ),
        )
        provider_code = f"{request.instrument.symbol}0"
        facts: list[FinancialFact] = []
        for row in rows:
            if str(row.get("Code", "")) != provider_code:
                raise ValueError("J-Quants returned financials for a different issue")
            publication_date = cls._provider_date(row, "DiscDate")
            if not request.start <= publication_date <= request.end:
                continue
            published_at = cls._provider_datetime(row, "DiscDate", "DiscTime")
            available_at = published_at or retrieved_at
            availability_basis = (
                AvailabilityBasis.PUBLISHED
                if published_at is not None
                else AvailabilityBasis.RETRIEVAL
            )
            try:
                period_start = date.fromisoformat(str(row["CurPerSt"]))
                period_end = date.fromisoformat(str(row["CurPerEn"]))
            except (KeyError, ValueError) as error:
                raise ValueError("J-Quants financial period is invalid") from error
            provider_period = str(row.get("CurPerType", ""))
            if provider_period not in {"1Q", "2Q", "3Q", "FY"}:
                raise ValueError("J-Quants financial period type is unsupported")
            period = (
                FinancialPeriod.ANNUAL if provider_period == "FY" else FinancialPeriod.QUARTERLY
            )
            revision = (
                Revision.RESTATED
                if str(row.get("RetroRst", "")).lower() not in {"", "0", "false", "none"}
                else Revision.REPORTED
            )
            for consolidation, mapping in mappings:
                for provider_fact, concept in mapping.items():
                    value = row.get(provider_fact)
                    if value in (None, ""):
                        continue
                    try:
                        decimal = Decimal(str(value))
                    except InvalidOperation as error:
                        raise ValueError("J-Quants financial value is invalid") from error
                    facts.append(
                        FinancialFact(
                            concept=concept,
                            provider_fact=provider_fact,
                            accounting_standard=None,
                            period=period,
                            fiscal_period_start=period_start,
                            fiscal_period_end=period_end,
                            published_at=published_at,
                            available_at=available_at,
                            availability_basis=availability_basis,
                            consolidation=consolidation,
                            revision=revision,
                            currency=request.instrument.currency,
                            scale=1,
                            value=decimal,
                        )
                    )
        return tuple(sorted(facts, key=lambda fact: (fact.available_at, fact.concept)))

    @classmethod
    def _events(
        cls,
        dividends: list[dict[str, Any]],
        earnings: list[dict[str, Any]],
        request: FactFetchRequest,
        retrieved_at: datetime,
    ) -> tuple[CorporateEvent, ...]:
        provider_code = f"{request.instrument.symbol}0"
        events: list[CorporateEvent] = []
        for row in dividends:
            if str(row.get("Code", "")) != provider_code:
                raise ValueError("J-Quants returned a dividend for a different issue")
            publication_date = cls._provider_date(row, "PubDate")
            if not request.start <= publication_date <= request.end:
                continue
            published_at = cls._provider_datetime(row, "PubDate", "PubTime")
            effective = cls._provider_date(row, "ExDate", fallback="RecDate")
            values = tuple(
                (name, str(row[field]))
                for name, field in (("dividend_rate", "DivRate"), ("status_code", "StatCode"))
                if row.get(field) not in (None, "")
            )
            events.append(
                CorporateEvent(
                    CorporateEventType.DIVIDEND,
                    publication_date,
                    effective,
                    published_at,
                    published_at or retrieved_at,
                    AvailabilityBasis.PUBLISHED
                    if published_at is not None
                    else AvailabilityBasis.RETRIEVAL,
                    values,
                )
            )
        for row in earnings:
            if str(row.get("Code", "")) != provider_code:
                continue
            effective = cls._provider_date(row, "Date")
            if not request.start <= effective <= request.end:
                continue
            events.append(
                CorporateEvent(
                    CorporateEventType.EARNINGS,
                    effective,
                    effective,
                    None,
                    retrieved_at,
                    AvailabilityBasis.RETRIEVAL,
                    tuple(
                        (name, str(row[field]))
                        for name, field in (("fiscal_year", "FY"), ("quarter", "FQ"))
                        if row.get(field) not in (None, "")
                    ),
                )
            )
        return tuple(sorted(events, key=lambda event: (event.effective_date, event.event_type)))

    @staticmethod
    def _provider_datetime(
        row: Mapping[str, Any], date_field: str, time_field: str
    ) -> datetime | None:
        try:
            day = date.fromisoformat(str(row[date_field]))
            raw = row.get(time_field)
            if raw in (None, ""):
                return None
            raw_time = str(raw)
            parsed_time = datetime.fromisoformat(f"{day.isoformat()}T{raw_time}").time()
        except (KeyError, ValueError) as error:
            raise ValueError("J-Quants publication timestamp is invalid") from error
        return datetime.combine(day, parsed_time, ZoneInfo("Asia/Tokyo"))

    @staticmethod
    def _provider_date(row: Mapping[str, Any], field: str, *, fallback: str | None = None) -> date:
        raw = row.get(field)
        if raw in (None, "") and fallback is not None:
            raw = row.get(fallback)
        try:
            return date.fromisoformat(str(raw))
        except ValueError as error:
            raise ValueError("J-Quants event date is invalid") from error

    @staticmethod
    def _validate_market(currency: str, timezone: str) -> None:
        if currency != "JPY":
            raise ValueError("J-Quants XTKS instruments must use JPY")
        if timezone != "Asia/Tokyo":
            raise ValueError("J-Quants XTKS instruments must use Asia/Tokyo")

    def _credential(self) -> str | None:
        value = self._environ.get(API_KEY_ENV)
        if not value:
            return None
        if any(not 0x21 <= ord(character) <= 0x7E for character in value):
            raise ValueError("J-Quants credential contains invalid header characters")
        return value

    @staticmethod
    def _validated_settings(
        settings: Mapping[str, str], *, allow_event_types: bool = False
    ) -> tuple[str, float]:
        allowed = {"base_url", "timeout_seconds"}
        if allow_event_types:
            allowed.add("event_types")
        unknown = set(settings) - allowed
        if unknown:
            raise ValueError(f"unsupported J-Quants settings: {', '.join(sorted(unknown))}")
        base_url = settings.get("base_url", API_BASE_URL).rstrip("/")
        if base_url != API_BASE_URL:
            raise ValueError(f"J-Quants base_url must be {API_BASE_URL}")
        try:
            timeout = float(settings.get("timeout_seconds", "30"))
        except ValueError as error:
            raise ValueError("J-Quants timeout_seconds must be numeric") from error
        if not 0 < timeout <= 120:
            raise ValueError("J-Quants timeout_seconds must be greater than 0 and at most 120")
        return base_url, timeout

    def _pages(
        self,
        url: str,
        query: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float,
    ) -> tuple[list[dict[str, Any]], list[bytes]]:
        rows: list[dict[str, Any]] = []
        bodies: list[bytes] = []
        next_query = dict(query)
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            response = self._transport.get(url, query=next_query, headers=headers, timeout=timeout)
            self._raise_for_status(response)
            document = self._document(response.body)
            data = document.get("data")
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ValueError("J-Quants response data must be an array of objects")
            rows.extend(data)
            bodies.append(response.body)
            pagination = document.get("pagination_key")
            if pagination is None:
                return rows, bodies
            if not isinstance(pagination, str) or not pagination or pagination in seen:
                raise ValueError("J-Quants returned an invalid pagination_key")
            seen.add(pagination)
            next_query = {**query, "pagination_key": pagination}
        raise RuntimeError("J-Quants pagination exceeded the safety limit")

    @staticmethod
    def _raise_for_status(response: HttpResponse) -> None:
        if response.status == 200:
            return
        meanings = {
            400: "request was rejected",
            401: "API key was rejected",
            403: "plan does not permit the exact request",
            413: "exact request is too large",
            429: "rate limit was exceeded",
        }
        meaning = meanings.get(response.status, "provider failed")
        raise RuntimeError(
            f"J-Quants {meaning} (HTTP {response.status}); request was not shortened"
        )

    @staticmethod
    def _document(body: bytes) -> dict[str, Any]:
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("J-Quants response is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("J-Quants response must be a JSON object")
        return value

    @staticmethod
    def _profile(rows: list[dict[str, Any]], code: str) -> InstrumentProfile:
        provider_code = f"{code}0"
        matching = [item for item in rows if str(item.get("Code", "")) == provider_code]
        if len(matching) != 1:
            raise ValueError(
                "J-Quants instrument profile did not identify exactly one requested issue"
            )
        row = matching[0]
        try:
            observation_date = date.fromisoformat(str(row["Date"]))
        except (KeyError, ValueError) as error:
            raise ValueError("J-Quants instrument profile has an invalid Date") from error
        names = tuple(
            (key, str(row[field]))
            for key, field in (("ja", "CoName"), ("en", "CoNameEn"))
            if row.get(field)
        )
        attributes = tuple(
            (key, str(row[field]))
            for key, field in (
                ("sector17_code", "S17"),
                ("sector33_code", "S33"),
                ("market_code", "Mkt"),
                ("margin_code", "MarginCode"),
            )
            if row.get(field) is not None
        )
        return InstrumentProfile(observation_date, None, names, attributes)

    @staticmethod
    def _bars(
        rows: list[dict[str, Any]], request: DailyBarFetchRequest, retrieved_at: datetime
    ) -> tuple[DailyBar, ...]:
        prefix = "Adj" if request.adjustment is Adjustment.ADJUSTED else ""
        fields = tuple(f"{prefix}{name}" for name in ("O", "H", "L", "C", "Vo"))
        provider_code = f"{request.instrument.symbol}0"
        bars: list[DailyBar] = []
        for row in rows:
            if str(row.get("Code", "")) != provider_code:
                raise ValueError("J-Quants returned a different issue than requested")
            if any(field not in row for field in fields):
                raise ValueError("J-Quants daily bar is missing an OHLCV field")
            null_fields = tuple(row.get(field) is None for field in fields)
            if all(null_fields):
                continue
            if any(null_fields):
                raise ValueError("J-Quants daily bar contains partially null OHLCV values")
            try:
                trading_date = date.fromisoformat(str(row["Date"]))
                prices = tuple(Decimal(str(row[field])) for field in fields[:4])
                volume_decimal = Decimal(str(row[fields[4]]))
            except (KeyError, InvalidOperation, ValueError) as error:
                raise ValueError("J-Quants daily bar contains an invalid value") from error
            if not request.start <= trading_date <= request.end:
                raise ValueError("J-Quants returned a daily bar outside the exact requested range")
            if volume_decimal != volume_decimal.to_integral_value():
                raise ValueError("J-Quants daily-bar volume must be an integer")
            bars.append(
                DailyBar(
                    trading_date=trading_date,
                    open=prices[0],
                    high=prices[1],
                    low=prices[2],
                    close=prices[3],
                    volume=int(volume_decimal),
                    adjustment=request.adjustment,
                    available_at=retrieved_at,
                    provenance=Provenance("jquants", "equities/bars/daily", SOURCE_VERSION),
                )
            )
        ordered = tuple(sorted(bars, key=lambda item: item.trading_date))
        if len({item.trading_date for item in ordered}) != len(ordered):
            raise ValueError("J-Quants returned duplicate daily-bar dates")
        return ordered
