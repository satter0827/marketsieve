"""No-key yfinance batch acquisition."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from functools import lru_cache, partial
from importlib import metadata
from itertools import pairwise
from pathlib import Path
from threading import Event, Lock
from typing import Any, TypeVar

import exchange_calendars as _exchange_calendars  # type: ignore[import-untyped]
import yfinance as _yfinance  # type: ignore[import-untyped]
from curl_cffi.requests import Response, Session
from yfinance import multi as _yfinance_multi
from yfinance import utils as _yfinance_utils

from marketsieve.analysis.indicators import CONTEXT
from marketsieve.data.daily import Adjustment, DailyBar, Provenance
from marketsieve.domain import Instrument
from marketsieve_extension_api import (
    EquityAcquisitionFailure,
    EquityBatchInstrument,
    EquityBatchObservation,
    EquityBatchRequest,
    ImportedEquityBatch,
    ImportedMarketIndicators,
    ImportedSecurityResearch,
    MarketIndicatorFailure,
    MarketIndicatorObservation,
    MarketIndicatorRequest,
    ResearchEvent,
    ResearchFinancialFact,
    SecurityResearchRequest,
    SourceDiagnostic,
)

T = TypeVar("T")
type ProfileLoadResult = tuple[Any, tuple[Any | BaseException, ...]]
YFINANCE: Any = _yfinance
YFINANCE_MULTI: Any = _yfinance_multi
YFINANCE_UTILS: Any = _yfinance_utils
_ORIGINAL_DOWNLOAD: Any = _yfinance.download
_YFINANCE_RUNTIME_LOCK = Lock()
EXCHANGE_CALENDAR_BY_MIC = {
    "BATS": "XNYS",
    "XNAS": "XNYS",
    "XNYS": "XNYS",
    "XTKS": "XTKS",
}
MAX_MARKET_REFERENCE_LAG_DAYS = 7
MAX_INSTRUMENT_REFERENCE_LAG_DAYS = 1
PRICE_DATA_FIELDS = ("Open", "High", "Low", "Close")


class _ProfileAcquisitionCancelled(Exception):
    """Stop profile work cooperatively after the owning Snapshot run is interrupted."""


class _BatchDownloadError(Exception):
    """Retain yfinance's partial frame and per-symbol errors across bounded retries."""

    def __init__(self, frame: Any, errors: Mapping[str, object]) -> None:
        super().__init__("yfinance batch contained provider failures")
        self.frame = frame
        self.errors = dict(errors)


class _HistoryEmptyError(Exception):
    """Mark a symbol omitted from an otherwise successful yfinance response."""


class _CorporateActionMismatchError(Exception):
    """Reject an adjusted history that still contains a split-sized price discontinuity."""


PROFILE_FIELDS = {
    "shortName": "name",
    "longName": "long_name",
    "exchange": "exchange",
    "fullExchangeName": "exchange_name",
    "country": "country",
    "currency": "currency",
    "financialCurrency": "financial_currency",
    "sector": "sector",
    "industry": "industry",
    "quoteType": "quote_type",
    "marketCap": "market_cap",
    "enterpriseValue": "enterprise_value",
    "sharesOutstanding": "shares_outstanding",
}

FINANCIAL_FIELDS = {
    "totalRevenue": "revenue_ttm",
    "ebitda": "ebitda_ttm",
    "operatingIncome": "operating_income_ttm",
    "netIncomeToCommon": "net_income_ttm",
    "operatingCashflow": "operating_cash_flow_ttm",
    "freeCashflow": "free_cash_flow_ttm",
    "totalCash": "total_cash",
    "totalDebt": "total_debt",
    "revenueGrowth": "revenue_growth",
    "earningsGrowth": "earnings_growth",
    "earningsQuarterlyGrowth": "earnings_quarterly_growth",
    "grossMargins": "gross_margin",
    "operatingMargins": "operating_margin",
    "profitMargins": "net_margin",
    "returnOnEquity": "return_on_equity",
    "returnOnAssets": "return_on_assets",
    "debtToEquity": "debt_to_equity",
    "currentRatio": "current_ratio",
    "quickRatio": "quick_ratio",
    "trailingPE": "trailing_pe",
    "forwardPE": "forward_pe",
    "priceToBook": "price_to_book",
    "priceToSalesTrailing12Months": "price_to_sales",
    "enterpriseToRevenue": "enterprise_to_revenue",
    "enterpriseToEbitda": "enterprise_to_ebitda",
    "trailingEps": "trailing_eps",
    "forwardEps": "forward_eps",
    "dividendYield": "dividend_yield",
    "payoutRatio": "payout_ratio",
}
# yfinance exposes these fields as percentage points while MarketSieve stores
# every ratio as a unit interval value. Keep the conversion at the provider
# boundary so Snapshot and Research share one contract.
PERCENT_POINT_FIELDS = {"debtToEquity", "dividendYield"}

RESEARCH_STATEMENT_FIELDS = {
    "income": {
        "Total Revenue": "revenue",
        "Gross Profit": "gross_profit",
        "Operating Income": "operating_income",
        "EBITDA": "ebitda",
        "Pretax Income": "pretax_income",
        "Net Income": "net_income",
        "Diluted EPS": "diluted_eps",
    },
    "balance_sheet": {
        "Total Assets": "total_assets",
        "Current Assets": "current_assets",
        "Cash Cash Equivalents And Short Term Investments": "cash_and_short_term_investments",
        "Inventory": "inventory",
        "Accounts Receivable": "accounts_receivable",
        "Current Liabilities": "current_liabilities",
        "Total Debt": "total_debt",
        "Stockholders Equity": "stockholders_equity",
    },
    "cash_flow": {
        "Operating Cash Flow": "operating_cash_flow",
        "Capital Expenditure": "capital_expenditure",
        "Free Cash Flow": "free_cash_flow",
        "Cash Dividends Paid": "dividends_paid",
        "Repurchase Of Capital Stock": "share_repurchases",
        "Issuance Of Capital Stock": "share_issuance",
        "Issuance Of Debt": "debt_issuance",
        "Repayment Of Debt": "debt_repayment",
    },
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        rendered = format(number, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return "0" if rendered in {"", "-0"} else rendered
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.casefold() in {
            "nan",
            "+nan",
            "-nan",
            "inf",
            "+inf",
            "-inf",
            "infinity",
            "+infinity",
            "-infinity",
        }:
            return None
        return stripped or None
    return None


def _is_finite_number(value: object) -> bool:
    try:
        return Decimal(str(value)).is_finite()
    except (InvalidOperation, TypeError, ValueError):
        return False


def _failure_reason(error: BaseException | str) -> str:
    if isinstance(error, _HistoryEmptyError):
        return "history_empty"
    if isinstance(error, _CorporateActionMismatchError):
        return "corporate_action_mismatch"
    message = str(error).lower()
    name = type(error).__name__.lower()
    if (
        any(value in message for value in ("too many requests", "rate limit", "ratelimit"))
        or re.search(r"\b429\b", message)
        or "ratelimit" in name
    ):
        return "rate_limited"
    if any(
        value in message
        for value in (
            "possibly delisted",
            "no timezone found",
            "symbol not found",
            "no data found",
        )
    ):
        return "symbol_not_found"
    if (
        isinstance(error, (TimeoutError, ConnectionError))
        or any(value in name for value in ("timeout", "connection", "connecterror", "dns"))
        or any(
            value in message
            for value in (
                "timed out",
                "timeout",
                "could not resolve",
                "failed to resolve",
                "name or service not known",
                "temporary failure in name resolution",
                "failed to connect",
                "connection refused",
                "connection reset",
                "network is unreachable",
                "network error",
            )
        )
    ):
        return "network_error"
    return "provider_error"


def _download_batch(symbols: tuple[str, ...], **kwargs: Any) -> tuple[Any, Mapping[str, object]]:
    """Return a yfinance batch frame together with its otherwise-hidden symbol errors."""

    if YFINANCE.download is not _ORIGINAL_DOWNLOAD:
        return YFINANCE.download(symbols, **kwargs), {}
    context = YFINANCE_MULTI._DownloadCtx()
    logger: logging.Logger = YFINANCE_UTILS.get_yf_logger()
    logger_disabled = logger.disabled
    logger.disabled = True
    try:
        frame = YFINANCE_MULTI._download_impl(context, symbols, **kwargs)
    finally:
        logger.disabled = logger_disabled
    return frame, dict(context.errors)


def _symbol_frame(frame: Any, symbol: str) -> Any:
    try:
        return frame[symbol]
    except (KeyError, TypeError, AttributeError):
        return None


def _frame_has_market_data(frame: Any) -> bool:
    if frame is None or getattr(frame, "empty", True):
        return False
    return any(
        all(_is_finite_number(row.get(field)) for field in PRICE_DATA_FIELDS)
        for _, row in frame.iterrows()
    )


def _financial_text(source: str, value: object) -> str | None:
    try:
        with localcontext(CONTEXT):
            number = Decimal(str(value))
            if source in PERCENT_POINT_FIELDS:
                number /= Decimal(100)
            return _text(number)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _latest_statement_period(*frames: Any) -> str | None:
    """Return the newest provider statement period without inferring publication time."""

    periods: list[date] = []
    for frame in frames:
        if frame is None or getattr(frame, "empty", True):
            continue
        for value in getattr(frame, "columns", ()):
            try:
                periods.append(
                    value.date() if hasattr(value, "date") else date.fromisoformat(str(value))
                )
            except (TypeError, ValueError):
                continue
    return max(periods).isoformat() if periods else None


@lru_cache(maxsize=16)
def _exchange_calendar(mic: str, year: int) -> Any:
    name = EXCHANGE_CALENDAR_BY_MIC.get(mic)
    if name is None:
        return None
    return _exchange_calendars.get_calendar(
        name,
        start=date(year, 1, 1),
        end=date(year, 12, 31),
    )


def _session_is_complete(
    instrument: Instrument, trading_date: date, retrieved_at: datetime
) -> bool:
    """Reject a same-date daily row until that date's actual exchange session has closed."""

    local_retrieval = retrieved_at.astimezone(instrument.exchange_timezone)
    calendar = _exchange_calendar(instrument.mic, trading_date.year)
    if calendar is None or not calendar.is_session(trading_date):
        return False
    if trading_date < local_retrieval.date():
        return True
    if trading_date > local_retrieval.date():
        return False
    close: datetime = calendar.session_close(trading_date).to_pydatetime()
    return retrieved_at >= close


def _statement_series(
    frame: Any, labels: tuple[str, ...]
) -> tuple[tuple[date, Decimal | None], ...]:
    if frame is None or getattr(frame, "empty", True):
        return ()
    available = {
        re.sub(r"[^a-z0-9]", "", str(value).lower()): value for value in getattr(frame, "index", ())
    }
    for label in labels:
        source_label = available.get(re.sub(r"[^a-z0-9]", "", label.lower()), label)
        try:
            row = frame.loc[source_label]
        except (KeyError, TypeError):
            continue
        raw_values = getattr(row, "tolist", lambda: ())()
        columns = tuple(getattr(frame, "columns", ()))
        if len(raw_values) != len(columns):
            continue
        values: list[tuple[date, Decimal | None]] = []
        invalid_period = False
        for column, raw in zip(columns, raw_values, strict=True):
            try:
                period = (
                    column.date()
                    if hasattr(column, "date")
                    else date.fromisoformat(str(column)[:10])
                )
            except (TypeError, ValueError):
                invalid_period = True
                break
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError):
                values.append((period, None))
                continue
            values.append((period, value if value.is_finite() else None))
        if values and not invalid_period:
            ordered = tuple(sorted(values, key=lambda value: value[0], reverse=True))
            dates = tuple(value[0] for value in ordered)
            if len(dates) == len(set(dates)) and any(value is not None for _, value in ordered):
                return ordered
    return ()


def _statement_value(frame: Any, labels: tuple[str, ...]) -> Decimal | None:
    values = _statement_series(frame, labels)
    return values[0][1] if values and values[0][1] is not None else None


def _statement_sum(frame: Any, labels: tuple[str, ...], *, periods: int = 4) -> Decimal | None:
    values = _statement_series(frame, labels)
    selected = values[:periods]
    if (
        len(selected) < periods
        or any(value is None for _, value in selected)
        or any(not 70 <= (left[0] - right[0]).days <= 115 for left, right in pairwise(selected))
    ):
        return None
    with localcontext(CONTEXT):
        return +sum((value for _, value in selected if value is not None), start=Decimal(0))


def _statement_cagr(frame: Any, labels: tuple[str, ...]) -> Decimal | None:
    values = _statement_series(frame, labels)
    if (
        len(values) < 4
        or any(not 300 <= (left[0] - right[0]).days <= 430 for left, right in pairwise(values[:4]))
        or values[0][1] is None
        or values[3][1] is None
        or values[0][1] <= 0
        or values[3][1] <= 0
    ):
        return None
    latest = values[0][1]
    earliest = values[3][1]
    assert latest is not None and earliest is not None
    with localcontext(CONTEXT):
        return +(((latest / earliest).ln() / Decimal(3)).exp() - Decimal(1))


class _BoundedSession(Session[Response]):
    """Clamp every yfinance transport call to the configured timeout."""

    def __init__(self, timeout_seconds: int) -> None:
        super().__init__(impersonate="chrome")
        self.timeout_seconds = timeout_seconds

    def request(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["timeout"] = self.timeout_seconds
        return super().request(*args, **kwargs)


class YFinanceSource:
    """Fetch yfinance price and current company facts without credentials."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def doctor(self) -> SourceDiagnostic:
        try:
            version = metadata.version("yfinance")
        except metadata.PackageNotFoundError:
            return SourceDiagnostic(False, "dependency_missing", "yfinance is not installed")
        return SourceDiagnostic(True, "ready", f"yfinance {version} is available")

    def fetch(self, request: EquityBatchRequest) -> ImportedEquityBatch:
        with _YFINANCE_RUNTIME_LOCK:
            cache = Path(request.settings.get("cache_dir", ".marketsieve/cache/yfinance"))
            cache.mkdir(parents=True, exist_ok=True)
            YFINANCE.set_tz_cache_location(str(cache))
            version = metadata.version("yfinance")
            session = _BoundedSession(request.timeout_seconds)
            hide_exceptions = YFINANCE.config.debug.hide_exceptions
            YFINANCE.config.debug.hide_exceptions = False
            try:
                if "price" in request.evidence:
                    bars, price_failures = self._prices(request, version, session)
                else:
                    bars, price_failures = {}, ()
                if {"company", "financials"} & set(request.evidence):
                    profiles, profile_failures = self._profiles(request, session)
                else:
                    profiles, profile_failures = {}, ()
            finally:
                YFINANCE.config.debug.hide_exceptions = hide_exceptions
                session.close()
        retrieved_at = self._retrieved_at()
        observations: list[EquityBatchObservation] = []
        for item in request.instruments:
            identity = (item.instrument.mic, item.instrument.symbol)
            profile, financials = profiles.get(identity, ((), ()))
            if "company" not in request.evidence:
                profile = tuple(
                    (name, value) for name, value in profile if name == "financial_currency"
                )
            if "financials" not in request.evidence:
                financials = ()
            item_bars = bars.get(identity, ())
            semantic = {
                "instrument": identity,
                "provider_symbol": item.provider_symbol,
                "bars": [
                    [
                        value.trading_date.isoformat(),
                        str(value.open),
                        str(value.high),
                        str(value.low),
                        str(value.close),
                        value.volume,
                    ]
                    for value in item_bars
                ],
                "profile": profile,
                "financials": financials,
            }
            observations.append(
                EquityBatchObservation(
                    requested=item,
                    retrieved_at=retrieved_at,
                    bars=item_bars,
                    profile=profile,
                    financials=financials,
                    source_hash=_digest(semantic),
                )
            )
        failures = tuple(
            sorted(
                (*price_failures, *profile_failures),
                key=lambda value: (
                    value.instrument.mic,
                    value.instrument.symbol,
                    value.stage,
                    value.field,
                    value.reason,
                ),
            )
        )
        response_document = {
            "observations": [value.source_hash for value in observations],
            "failures": [
                [
                    value.instrument.mic,
                    value.instrument.symbol,
                    value.stage,
                    value.field,
                    value.reason,
                ]
                for value in failures
            ],
        }
        return ImportedEquityBatch(
            request=request,
            source_name="yfinance",
            source_version=version,
            dataset="equity-" + "-".join(request.evidence),
            retrieved_at=retrieved_at,
            observations=tuple(observations),
            failures=failures,
            response_hash=_digest(response_document),
        )

    def fetch_market_indicators(self, request: MarketIndicatorRequest) -> ImportedMarketIndicators:
        """Fetch price-only macro series without applying equity-specific checks."""

        requested = tuple(
            sorted(
                (
                    EquityBatchInstrument(
                        Instrument.create(
                            symbol=item.indicator_id.upper().replace("_", "")[:12],
                            mic="XNAS",
                            currency=("JPY" if item.unit == "JPY_per_USD" else "USD"),
                            exchange_timezone="America/New_York",
                        ),
                        item.provider_symbol,
                        (f"indicator:{item.indicator_id}",),
                        True,
                    )
                    for item in request.indicators
                ),
                key=lambda value: (value.instrument.mic, value.instrument.symbol),
            )
        )
        batch = self.fetch(
            EquityBatchRequest(
                source_profile=request.source_profile,
                instruments=requested,
                start=request.start,
                end=request.end,
                adjustment=Adjustment.ADJUSTED,
                batch_size=len(requested),
                profile_workers=1,
                timeout_seconds=request.timeout_seconds,
                max_retries=request.max_retries,
                retry_base_seconds=request.retry_base_seconds,
                settings=request.settings,
                evidence=("price",),
            )
        )
        by_id = {
            item.requested.memberships[0].removeprefix("indicator:"): item
            for item in batch.observations
        }
        observations = tuple(
            MarketIndicatorObservation(
                requested=item,
                retrieved_at=by_id[item.indicator_id].retrieved_at,
                bars=by_id[item.indicator_id].bars,
                source_hash=by_id[item.indicator_id].source_hash,
            )
            for item in request.indicators
        )
        indicator_id_by_instrument = {
            (
                item.requested.instrument.mic,
                item.requested.instrument.symbol,
            ): item.requested.memberships[0].removeprefix("indicator:")
            for item in batch.observations
        }
        failures = tuple(
            MarketIndicatorFailure(
                indicator_id=indicator_id_by_instrument[
                    (failure.instrument.mic, failure.instrument.symbol)
                ],
                stage=failure.stage,
                field=failure.field,
                reason=failure.reason,
            )
            for failure in batch.failures
            if failure.field not in {"volume_20d", "volume_60d"}
        )
        return ImportedMarketIndicators(
            request=request,
            source_name=batch.source_name,
            source_version=batch.source_version,
            retrieved_at=batch.retrieved_at,
            observations=observations,
            failures=failures,
            response_hash=_digest(
                {
                    "observations": [item.source_hash for item in observations],
                    "failures": [
                        [item.indicator_id, item.stage, item.field, item.reason]
                        for item in failures
                    ],
                }
            ),
        )

    def fetch_research(self, request: SecurityResearchRequest) -> ImportedSecurityResearch:
        """Fetch one detailed security evidence bundle without provider fallback."""

        item = EquityBatchInstrument(
            request.instrument,
            request.provider_symbol,
            ("research",),
        )
        batch_request = EquityBatchRequest(
            request.source_profile,
            (item,),
            request.start,
            request.end,
            request.adjustment,
            1,
            1,
            request.timeout_seconds,
            request.max_retries,
            request.retry_base_seconds,
            request.settings,
            tuple(sorted({"price", "company", "financials"} & set(request.evidence))) or ("price",),
        )
        with _YFINANCE_RUNTIME_LOCK:
            cache = Path(request.settings.get("cache_dir", ".marketsieve/cache/yfinance"))
            cache.mkdir(parents=True, exist_ok=True)
            YFINANCE.set_tz_cache_location(str(cache))
            version = metadata.version("yfinance")
            session = _BoundedSession(request.timeout_seconds)
            hide_exceptions = YFINANCE.config.debug.hide_exceptions
            YFINANCE.config.debug.hide_exceptions = False
            failures: list[EquityAcquisitionFailure] = []
            try:
                if "price" in request.evidence:
                    prices, price_failures = self._prices(batch_request, version, session)
                    failures.extend(price_failures)
                else:
                    prices = {}
                ticker = YFINANCE.Ticker(request.provider_symbol, session=session)
                info = (
                    self._research_attempt(
                        ticker.get_info,
                        batch_request,
                        failures,
                        request,
                        "company" if "company" in request.evidence else "financial_currency",
                    )
                    if {"company", "financials"} & set(request.evidence)
                    else None
                )
                frames = (
                    {
                        ("income", period): self._research_attempt(
                            partial(ticker.get_income_stmt, freq=period),
                            batch_request,
                            failures,
                            request,
                            f"income_{period}",
                        )
                        for period in ("yearly", "quarterly")
                    }
                    if "financials" in request.evidence
                    else {}
                )
                if "financials" in request.evidence:
                    frames.update(
                        {
                            ("balance_sheet", period): self._research_attempt(
                                partial(ticker.get_balance_sheet, freq=period),
                                batch_request,
                                failures,
                                request,
                                f"balance_sheet_{period}",
                            )
                            for period in ("yearly", "quarterly")
                        }
                    )
                    frames.update(
                        {
                            ("cash_flow", period): self._research_attempt(
                                partial(ticker.get_cash_flow, freq=period),
                                batch_request,
                                failures,
                                request,
                                f"cash_flow_{period}",
                            )
                            for period in ("yearly", "quarterly")
                        }
                    )
                for (statement, period), frame in frames.items():
                    if frame is not None and getattr(frame, "empty", True):
                        failures.append(
                            EquityAcquisitionFailure(
                                request.instrument,
                                "research",
                                f"{statement}_{period}",
                                "financials_unavailable",
                            )
                        )
                actions = (
                    self._research_attempt(
                        lambda: ticker.get_actions(period="10y"),
                        batch_request,
                        failures,
                        request,
                        "actions",
                    )
                    if "events" in request.evidence
                    else None
                )
                earnings = (
                    self._research_attempt(
                        lambda: ticker.get_earnings_dates(limit=100),
                        batch_request,
                        failures,
                        request,
                        "earnings",
                    )
                    if "events" in request.evidence
                    else None
                )
                if (
                    "events" in request.evidence
                    and earnings is None
                    and not any(
                        failure.stage == "research" and failure.field == "earnings"
                        for failure in failures
                    )
                ):
                    failures.append(
                        EquityAcquisitionFailure(
                            request.instrument,
                            "research",
                            "earnings",
                            "field_absent",
                        )
                    )
            finally:
                YFINANCE.config.debug.hide_exceptions = hide_exceptions
                session.close()
        retrieved_at = self._retrieved_at()
        company_source = info if isinstance(info, Mapping) else {}
        if (
            "company" in request.evidence
            and not company_source
            and not any(
                failure.stage == "research" and failure.field == "company" for failure in failures
            )
        ):
            failures.append(
                EquityAcquisitionFailure(
                    request.instrument,
                    "research",
                    "company",
                    "provider_error",
                )
            )
        company = tuple(
            sorted(
                (
                    *(
                        (target, rendered)
                        for source, target in PROFILE_FIELDS.items()
                        if (rendered := _text(company_source.get(source))) is not None
                    ),
                    *(
                        (target, rendered)
                        for source, target in FINANCIAL_FIELDS.items()
                        if (rendered := _financial_text(source, company_source.get(source)))
                        is not None
                    ),
                )
            )
        )
        if "company" not in request.evidence:
            company = ()
        financial_currency = _text(company_source.get("financialCurrency"))
        if financial_currency is None and any(
            frame is not None and not getattr(frame, "empty", True) for frame in frames.values()
        ):
            failures.append(
                EquityAcquisitionFailure(
                    request.instrument,
                    "research",
                    "financial_currency",
                    "field_absent",
                )
            )
        financials = (
            self._research_financials(frames, financial_currency)
            if financial_currency is not None
            else ()
        )
        events = self._research_events(actions, earnings, request.start, request.end)
        bars = prices.get((request.instrument.mic, request.instrument.symbol), ())
        semantic = {
            "instrument": [request.instrument.mic, request.instrument.symbol],
            "bars": [
                [
                    bar.trading_date.isoformat(),
                    str(bar.open),
                    str(bar.high),
                    str(bar.low),
                    str(bar.close),
                    bar.volume,
                    bar.adjustment.value,
                ]
                for bar in bars
            ],
            "company": company,
            "financials": [
                [
                    fact.concept,
                    fact.statement,
                    fact.period,
                    fact.fiscal_period_end.isoformat(),
                    fact.currency,
                    str(fact.value),
                ]
                for fact in financials
            ],
            "events": [
                [event.event_type, event.effective_date.isoformat(), event.values]
                for event in events
            ],
            "failures": [[value.stage, value.field, value.reason] for value in failures],
        }
        return ImportedSecurityResearch(
            request,
            "yfinance",
            version,
            retrieved_at,
            bars,
            company,
            financials,
            events,
            tuple(sorted(failures, key=lambda value: (value.stage, value.field, value.reason))),
            _digest(semantic),
        )

    def _research_attempt(
        self,
        function: Callable[[], Any],
        batch_request: EquityBatchRequest,
        failures: list[EquityAcquisitionFailure],
        request: SecurityResearchRequest,
        field: str,
    ) -> Any:
        try:
            return self._retry(function, batch_request)
        except Exception as error:
            failures.append(
                EquityAcquisitionFailure(
                    request.instrument,
                    "research",
                    field,
                    _failure_reason(error),
                )
            )
            return None

    @staticmethod
    def _research_financials(
        frames: Mapping[tuple[str, str], Any], currency: str
    ) -> tuple[ResearchFinancialFact, ...]:
        facts: list[ResearchFinancialFact] = []
        for (statement, provider_period), frame in frames.items():
            if frame is None or getattr(frame, "empty", True):
                continue
            period = "annual" if provider_period == "yearly" else "quarterly"
            for provider_name, concept in RESEARCH_STATEMENT_FIELDS[statement].items():
                for fiscal_end, value in _statement_series(frame, (provider_name,)):
                    if value is not None:
                        facts.append(
                            ResearchFinancialFact(
                                concept,
                                statement,
                                period,
                                fiscal_end,
                                currency,
                                value,
                            )
                        )
        return tuple(
            sorted(
                facts,
                key=lambda value: (
                    value.fiscal_period_end,
                    value.period,
                    value.statement,
                    value.concept,
                ),
            )
        )

    @staticmethod
    def _research_events(
        actions: Any, earnings: Any, start: date, end: date
    ) -> tuple[ResearchEvent, ...]:
        events: list[ResearchEvent] = []
        if actions is not None and not getattr(actions, "empty", True):
            for index, row in actions.iterrows():
                effective = (
                    index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
                )
                if not start <= effective <= end:
                    continue
                dividend = _text(row.get("Dividends"))
                if dividend is not None and dividend != "0":
                    dividend_values = [("amount", dividend)]
                    if (currency := _text(row.get("Dividends FX"))) is not None:
                        dividend_values.append(("currency", currency))
                    events.append(
                        ResearchEvent("dividend", effective, tuple(sorted(dividend_values)))
                    )
                split = _text(row.get("Stock Splits"))
                if split is not None and split != "0":
                    events.append(ResearchEvent("split", effective, (("ratio", split),)))
        if earnings is not None and not getattr(earnings, "empty", True):
            for index, row in earnings.iterrows():
                effective = (
                    index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
                )
                if not start <= effective <= end:
                    continue
                values = tuple(
                    sorted(
                        (target, rendered)
                        for source, target in (
                            ("EPS Estimate", "estimated_eps"),
                            ("Reported EPS", "reported_eps"),
                            ("Surprise(%)", "surprise_percent"),
                        )
                        if (rendered := _text(row.get(source))) is not None
                    )
                )
                events.append(ResearchEvent("earnings", effective, values))
        return tuple(sorted(events, key=lambda value: (value.effective_date, value.event_type)))

    def _prices(
        self, request: EquityBatchRequest, version: str, session: Session[Response]
    ) -> tuple[dict[tuple[str, str], tuple[DailyBar, ...]], tuple[EquityAcquisitionFailure, ...]]:
        output: dict[tuple[str, str], tuple[DailyBar, ...]] = {}
        failures: list[EquityAcquisitionFailure] = []
        session_as_of = self._retrieved_at()
        for offset in range(0, len(request.instruments), request.batch_size):
            batch = request.instruments[offset : offset + request.batch_size]
            symbols = tuple(value.provider_symbol for value in batch)
            batch_error: Exception | None = None
            symbol_errors: dict[str, object] = {}
            frames: dict[str, tuple[Any, datetime]] = {}
            frame, primary_errors, batch_error = self._price_batch(
                symbols,
                request=request,
                session=session,
            )
            symbol_errors.update(primary_errors)
            batch_retrieved_at = self._retrieved_at()
            for symbol in symbols:
                symbol_frame = _symbol_frame(frame, symbol)
                if _frame_has_market_data(symbol_frame):
                    frames[symbol] = (symbol_frame, batch_retrieved_at)

            recoverable = tuple(
                value
                for value in batch
                if value.provider_symbol not in frames
                and isinstance(
                    symbol_errors.get(value.provider_symbol.upper()),
                    _HistoryEmptyError,
                )
            )
            if batch_error is None and recoverable:
                groups: dict[str, list[EquityBatchInstrument]] = {}
                for item in recoverable:
                    groups.setdefault(self._market(item.instrument), []).append(item)
                for market in sorted(groups):
                    self._recover_prices(
                        tuple(groups[market]),
                        request=request,
                        session=session,
                        frames=frames,
                        errors=symbol_errors,
                    )

            for value in batch:
                identity = (value.instrument.mic, value.instrument.symbol)
                if batch_error is not None:
                    output[identity] = ()
                    failures.append(
                        EquityAcquisitionFailure(
                            value.instrument,
                            "price",
                            "history",
                            _failure_reason(batch_error),
                        )
                    )
                    continue
                symbol_frame, retrieved_at = frames.get(
                    value.provider_symbol,
                    (None, batch_retrieved_at),
                )
                if not self._adjusted_prices_match_splits(symbol_frame, request.adjustment):
                    symbol_errors[value.provider_symbol.upper()] = _CorporateActionMismatchError(
                        value.provider_symbol
                    )
                    symbol_frame = None
                item_bars = self._bars(
                    symbol_frame,
                    instrument=value.instrument,
                    adjustment=request.adjustment,
                    retrieved_at=retrieved_at,
                    session_as_of=session_as_of,
                    version=version,
                )
                output[identity] = item_bars
                if not item_bars:
                    provider_error = symbol_errors.get(value.provider_symbol.upper())
                    failures.append(
                        EquityAcquisitionFailure(
                            value.instrument,
                            "price",
                            "history",
                            _failure_reason(
                                provider_error
                                if isinstance(provider_error, BaseException)
                                else str(provider_error)
                            )
                            if provider_error is not None
                            else "history_empty",
                        )
                    )
        failures.extend(self._reject_stale_histories(output, request))
        failures.extend(self._missing_volume_failures(output, request))
        return output, tuple(failures)

    def _price_batch(
        self,
        symbols: tuple[str, ...],
        *,
        request: EquityBatchRequest,
        session: Session[Response],
    ) -> tuple[Any, dict[str, object], Exception | None]:
        def download() -> tuple[Any, Mapping[str, object]]:
            frame, raw_errors = _download_batch(
                symbols,
                start=request.start.isoformat(),
                end=(request.end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=request.adjustment is Adjustment.ADJUSTED,
                actions=True,
                group_by="ticker",
                threads=False,
                progress=False,
                timeout=request.timeout_seconds,
                session=session,
                multi_level_index=True,
            )
            errors = {str(symbol).upper(): error for symbol, error in raw_errors.items()}
            for symbol in symbols:
                symbol_frame = _symbol_frame(frame, symbol)
                if symbol.upper() not in errors and not _frame_has_market_data(symbol_frame):
                    errors[symbol.upper()] = _HistoryEmptyError(symbol)
            if errors:
                raise _BatchDownloadError(frame, errors)
            return frame, errors

        try:
            frame, errors = self._retry(download, request)
            return frame, dict(errors), None
        except _BatchDownloadError as error:
            return error.frame, error.errors, None
        except Exception as error:
            return None, {}, error

    def _recover_prices(
        self,
        items: tuple[EquityBatchInstrument, ...],
        *,
        request: EquityBatchRequest,
        session: Session[Response],
        frames: dict[str, tuple[Any, datetime]],
        errors: dict[str, object],
    ) -> None:
        """Retry one bounded same-market group from a silently omitted batch."""

        if not items:
            return
        symbols = tuple(value.provider_symbol for value in items)
        frame, recovered_errors, batch_error = self._price_batch(
            symbols,
            request=request,
            session=session,
        )
        retrieved_at = self._retrieved_at()
        for item in items:
            symbol = item.provider_symbol
            symbol_frame = _symbol_frame(frame, symbol)
            if _frame_has_market_data(symbol_frame):
                frames[symbol] = (symbol_frame, retrieved_at)
                errors.pop(symbol.upper(), None)
                continue
            if batch_error is not None:
                errors[symbol.upper()] = batch_error
                continue
            error = recovered_errors.get(symbol.upper(), _HistoryEmptyError(symbol))
            errors[symbol.upper()] = error

    @staticmethod
    def _market(instrument: Instrument) -> str:
        return "jp" if instrument.currency == "JPY" else "us"

    @classmethod
    def _reject_stale_histories(
        cls,
        output: dict[tuple[str, str], tuple[DailyBar, ...]],
        request: EquityBatchRequest,
    ) -> tuple[EquityAcquisitionFailure, ...]:
        """Reject histories that do not reach the latest observed market session."""

        latest_by_market: dict[str, date] = {}
        for item in request.instruments:
            identity = (item.instrument.mic, item.instrument.symbol)
            bars = output.get(identity, ())
            if bars:
                market = cls._market(item.instrument)
                latest_by_market[market] = max(
                    latest_by_market.get(market, bars[-1].trading_date),
                    bars[-1].trading_date,
                )

        failures: list[EquityAcquisitionFailure] = []
        for item in request.instruments:
            identity = (item.instrument.mic, item.instrument.symbol)
            bars = output.get(identity, ())
            if not bars:
                continue
            reference = latest_by_market[cls._market(item.instrument)]
            market_reference_is_stale = (
                request.end - reference
            ).days > MAX_MARKET_REFERENCE_LAG_DAYS
            instrument_lag_days = (reference - bars[-1].trading_date).days
            if market_reference_is_stale or instrument_lag_days > MAX_INSTRUMENT_REFERENCE_LAG_DAYS:
                output[identity] = ()
                failures.append(
                    EquityAcquisitionFailure(
                        item.instrument,
                        "price",
                        "history",
                        "stale_history",
                    )
                )
        return tuple(failures)

    @staticmethod
    def _missing_volume_failures(
        output: Mapping[tuple[str, str], tuple[DailyBar, ...]],
        request: EquityBatchRequest,
    ) -> tuple[EquityAcquisitionFailure, ...]:
        """Treat yfinance zero volume as unavailable because the provider zero-fills NaN."""

        failures: list[EquityAcquisitionFailure] = []
        for item in request.instruments:
            bars = output.get((item.instrument.mic, item.instrument.symbol), ())
            if any(bar.volume == 0 for bar in bars[-20:]):
                failures.append(
                    EquityAcquisitionFailure(
                        item.instrument,
                        "volume",
                        "volume_20d",
                        "field_absent",
                    )
                )
            elif any(bar.volume == 0 for bar in bars[-60:]):
                failures.append(
                    EquityAcquisitionFailure(
                        item.instrument,
                        "volume",
                        "volume_60d",
                        "field_absent",
                    )
                )
        return tuple(failures)

    @staticmethod
    def _bars(
        frame: Any,
        *,
        instrument: Instrument,
        adjustment: Adjustment,
        retrieved_at: datetime,
        session_as_of: datetime | None = None,
        version: str,
    ) -> tuple[DailyBar, ...]:
        if frame is None or getattr(frame, "empty", True):
            return ()
        volume_factors = YFinanceSource._split_volume_factors(frame, adjustment)
        if volume_factors is None:
            return ()
        output: list[DailyBar] = []
        provenance = Provenance("yfinance", "equity-history", version)
        for index, row in frame.iterrows():
            try:
                prices = [Decimal(str(row[name])) for name in ("Open", "High", "Low", "Close")]
                if any(not value.is_finite() or value <= 0 for value in prices):
                    continue
                opened, high, low, close = prices
                if high < max(opened, low, close) or low > min(opened, high, close):
                    continue
                raw_volume = Decimal(str(row["Volume"]))
                if (
                    not raw_volume.is_finite()
                    or raw_volume < 0
                    or raw_volume != raw_volume.to_integral_value()
                ):
                    continue
                adjusted_volume = raw_volume * volume_factors[index]
                volume = int(adjusted_volume.to_integral_value(rounding=ROUND_HALF_EVEN))
                trading_date = (
                    index.date() if hasattr(index, "date") else date.fromisoformat(str(index))
                )
                if not _session_is_complete(
                    instrument,
                    trading_date,
                    session_as_of or retrieved_at,
                ):
                    continue
                output.append(
                    DailyBar(
                        trading_date,
                        opened,
                        high,
                        low,
                        close,
                        volume,
                        adjustment,
                        retrieved_at,
                        provenance,
                    )
                )
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        return tuple(sorted(output, key=lambda value: value.trading_date))

    @staticmethod
    def _split_volume_factors(frame: Any, adjustment: Adjustment) -> dict[Any, Decimal] | None:
        """Keep adjusted-price liquidity measures comparable across stock splits."""

        rows = tuple(frame.iterrows())
        if adjustment is not Adjustment.ADJUSTED:
            return {index: Decimal(1) for index, _ in rows}
        factor = Decimal(1)
        factors: dict[Any, Decimal] = {}
        for index, row in reversed(rows):
            has_price = any(_is_finite_number(row.get(field)) for field in PRICE_DATA_FIELDS)
            try:
                split = Decimal(str(row.get("Stock Splits", 0)))
            except (InvalidOperation, TypeError, ValueError):
                return None
            if split.is_nan() and not has_price:
                continue
            if not split.is_finite() or split < 0:
                return None
            if has_price:
                factors[index] = factor
            if split > 0:
                factor *= split
        return factors

    @staticmethod
    def _adjusted_prices_match_splits(frame: Any, adjustment: Adjustment) -> bool:
        """Detect near-exact inverse split jumps while tolerating ordinary invalid rows."""

        if frame is None or getattr(frame, "empty", True) or adjustment is not Adjustment.ADJUSTED:
            return True
        previous_close: Decimal | None = None
        pending_split = Decimal(1)
        for _, row in frame.iterrows():
            try:
                close = Decimal(str(row.get("Close")))
                close_is_valid = close.is_finite() and close > 0
            except (InvalidOperation, TypeError, ValueError):
                close = Decimal("NaN")
                close_is_valid = False
            try:
                split = Decimal(str(row.get("Stock Splits", 0)))
            except (InvalidOperation, TypeError, ValueError):
                return False
            if split.is_nan() and not close_is_valid:
                continue
            if not split.is_finite() or split < 0:
                return False
            if split > 0:
                pending_split *= split
            if not close_is_valid:
                continue
            if previous_close is not None and pending_split != 1:
                ratio = close / previous_close
                split_scaled = ratio * pending_split
                # Price returns alone cannot prove a corporate-action mismatch. Reject only a
                # near-exact inverse of the provider's reported split; less exact moves remain
                # valid market returns.
                if abs(split_scaled - Decimal(1)) <= Decimal("0.005"):
                    return False
            previous_close = close
            pending_split = Decimal(1)
        return True

    def _profiles(
        self, request: EquityBatchRequest, session: Session[Response]
    ) -> tuple[
        dict[tuple[str, str], tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]],
        tuple[EquityAcquisitionFailure, ...],
    ]:
        output: dict[
            tuple[str, str], tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]
        ] = {}
        failures: list[EquityAcquisitionFailure] = []
        cancelled = Event()

        def load(item: Any) -> ProfileLoadResult:
            if item.is_benchmark:
                return item, ({}, None, None, None, None)
            ticker = YFINANCE.Ticker(item.provider_symbol, session=session)

            def attempt(method: str, *, freq: str | None = None) -> Any | BaseException:
                def fetch() -> Any:
                    function = getattr(ticker, method)
                    return function() if freq is None else function(freq=freq)

                try:
                    return self._retry(fetch, request, cancelled=cancelled)
                except _ProfileAcquisitionCancelled:
                    raise
                except Exception as error:
                    return error

            return item, (
                attempt("get_info") if {"company", "financials"} & set(request.evidence) else {},
                (
                    attempt("get_income_stmt", freq="yearly")
                    if "financials" in request.evidence
                    else None
                ),
                (
                    attempt("get_income_stmt", freq="quarterly")
                    if "financials" in request.evidence
                    else None
                ),
                (
                    attempt("get_balance_sheet", freq="quarterly")
                    if "financials" in request.evidence
                    else None
                ),
                (
                    attempt("get_cash_flow", freq="quarterly")
                    if "financials" in request.evidence
                    else None
                ),
            )

        completed: list[ProfileLoadResult] = []
        iterator = iter(request.instruments)
        executor = ThreadPoolExecutor(max_workers=request.profile_workers)
        pending: set[Future[ProfileLoadResult]] = set()

        def submit_next() -> None:
            try:
                item = next(iterator)
            except StopIteration:
                return
            pending.add(executor.submit(load, item))

        for _ in range(request.profile_workers):
            submit_next()
        try:
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.remove(future)
                    completed.append(future.result())
                    submit_next()
        except BaseException:
            cancelled.set()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

        for item, result in sorted(
            completed,
            key=lambda value: (value[0].instrument.mic, value[0].instrument.symbol),
        ):
            identity = (item.instrument.mic, item.instrument.symbol)
            info, annual_income, quarterly_income, balance, quarterly_cash_flow = result
            if isinstance(info, BaseException):
                failures.append(
                    EquityAcquisitionFailure(
                        item.instrument,
                        "profile" if "company" in request.evidence else "financials",
                        "company" if "company" in request.evidence else "financial_currency",
                        _failure_reason(info),
                    )
                )
                info = {}
            elif not isinstance(info, Mapping):
                failures.append(
                    EquityAcquisitionFailure(
                        item.instrument,
                        "profile" if "company" in request.evidence else "financials",
                        "company" if "company" in request.evidence else "financial_currency",
                        "provider_error",
                    )
                )
                info = {}
            for statement, field in (
                (annual_income, "annual_income"),
                (quarterly_income, "quarterly_income"),
                (balance, "balance_sheet"),
                (quarterly_cash_flow, "quarterly_cash_flow"),
            ):
                if isinstance(statement, BaseException):
                    failures.append(
                        EquityAcquisitionFailure(
                            item.instrument,
                            "financials",
                            field,
                            _failure_reason(statement),
                        )
                    )
            if item.is_benchmark:
                output[identity] = ((), ())
                continue
            annual_income = None if isinstance(annual_income, BaseException) else annual_income
            quarterly_income = (
                None if isinstance(quarterly_income, BaseException) else quarterly_income
            )
            balance = None if isinstance(balance, BaseException) else balance
            quarterly_cash_flow = (
                None if isinstance(quarterly_cash_flow, BaseException) else quarterly_cash_flow
            )
            profile = tuple(
                sorted(
                    (target, rendered)
                    for source, target in PROFILE_FIELDS.items()
                    if (rendered := _text(info.get(source))) is not None
                )
            )
            financial_values = {
                target: rendered
                for source, target in FINANCIAL_FIELDS.items()
                if (rendered := _financial_text(source, info.get(source))) is not None
            }
            statement_values = {
                "revenue_ttm": _statement_sum(quarterly_income, ("Total Revenue",)),
                "ebitda_ttm": _statement_sum(quarterly_income, ("EBITDA", "Normalized EBITDA")),
                "operating_income_ttm": _statement_sum(quarterly_income, ("Operating Income",)),
                "net_income_ttm": _statement_sum(
                    quarterly_income, ("Net Income", "Net Income Common Stockholders")
                ),
                "operating_cash_flow_ttm": _statement_sum(
                    quarterly_cash_flow,
                    ("Operating Cash Flow", "Total Cash From Operating Activities"),
                ),
                "capital_expenditure_ttm": _statement_sum(
                    quarterly_cash_flow, ("Capital Expenditure", "Capital Expenditures")
                ),
                "free_cash_flow_ttm": _statement_sum(quarterly_cash_flow, ("Free Cash Flow",)),
                "total_assets": _statement_value(balance, ("Total Assets",)),
                "total_equity": _statement_value(
                    balance,
                    ("Stockholders Equity", "Total Equity Gross Minority Interest"),
                ),
                "total_cash": _statement_value(
                    balance,
                    (
                        "Cash Cash Equivalents And Short Term Investments",
                        "Cash And Cash Equivalents",
                    ),
                ),
                "total_debt": _statement_value(balance, ("Total Debt",)),
                "revenue_cagr_3y": _statement_cagr(annual_income, ("Total Revenue",)),
                "earnings_cagr_3y": _statement_cagr(
                    annual_income, ("Net Income", "Net Income Common Stockholders")
                ),
            }
            financial_values.update(
                {
                    name: rendered
                    for name, value in statement_values.items()
                    if name not in financial_values and (rendered := _text(value)) is not None
                }
            )
            latest_financial_period = _latest_statement_period(
                annual_income, quarterly_income, balance, quarterly_cash_flow
            )
            if latest_financial_period is not None:
                financial_values["_financial_period_end"] = latest_financial_period
                financial_values["_financial_period_type"] = "mixed_latest"
                financial_values["_availability_basis"] = "retrieval"
            financials = tuple(sorted(financial_values.items()))
            if (
                "company" in request.evidence
                and not profile
                and not any(
                    failure.instrument == item.instrument and failure.stage == "profile"
                    for failure in failures
                )
            ):
                failures.append(
                    EquityAcquisitionFailure(item.instrument, "profile", "company", "field_absent")
                )
            if (
                "financials" in request.evidence
                and not financials
                and not any(
                    failure.instrument == item.instrument and failure.stage == "financials"
                    for failure in failures
                )
            ):
                failures.append(
                    EquityAcquisitionFailure(
                        item.instrument,
                        "financials",
                        "company_financials",
                        "financials_unavailable",
                    )
                )
            output[identity] = (profile, financials)
        return output, tuple(failures)

    @staticmethod
    def _retry(
        function: Callable[[], T],
        request: EquityBatchRequest,
        *,
        cancelled: Event | None = None,
    ) -> T:
        last_error: Exception | None = None
        best_batch_error: _BatchDownloadError | None = None
        for attempt in range(request.max_retries):
            if cancelled is not None and cancelled.is_set():
                raise _ProfileAcquisitionCancelled
            try:
                return function()
            except Exception as error:
                last_error = error
                if isinstance(error, _BatchDownloadError) and (
                    best_batch_error is None or len(error.errors) < len(best_batch_error.errors)
                ):
                    best_batch_error = error
                if attempt + 1 < request.max_retries:
                    delay = request.retry_base_seconds * (2**attempt)
                    if cancelled is None:
                        time.sleep(delay)
                    elif cancelled.wait(delay):
                        raise _ProfileAcquisitionCancelled from error
        if best_batch_error is not None:
            raise best_batch_error
        assert last_error is not None
        raise last_error

    def _retrieved_at(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source clock must return an offset-aware datetime")
        return value
