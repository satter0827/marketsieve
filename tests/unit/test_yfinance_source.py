from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest
from curl_cffi.requests import Session

from marketsieve.model import Adjustment, Instrument
from marketsieve_extension_api import (
    AcquisitionProgress,
    AcquisitionProgressState,
    EquityBatchInstrument,
    EquityBatchRequest,
    MarketIndicatorKind,
    MarketIndicatorRequest,
    MarketIndicatorSpec,
    SecurityResearchRequest,
)
from marketsieve_source_yfinance import YFinanceSource
from marketsieve_source_yfinance import source as source_module


def _instrument(
    symbol: str = "MSFT",
    *,
    mic: str = "XNAS",
    currency: str = "USD",
    timezone: str = "America/New_York",
) -> Instrument:
    return Instrument.create(
        symbol=symbol,
        mic=mic,
        currency=currency,
        exchange_timezone=timezone,
    )


def _request(*items: EquityBatchInstrument) -> EquityBatchRequest:
    instruments = items or (EquityBatchInstrument(_instrument(), "MSFT", ("sp500",)),)
    return EquityBatchRequest(
        "market-yfinance",
        tuple(
            sorted(instruments, key=lambda value: (value.instrument.mic, value.instrument.symbol))
        ),
        date(2026, 8, 1),
        date(2026, 8, 7),
        Adjustment.ADJUSTED,
        50,
        2,
        30,
        3,
        0.0,
        {"cache_dir": ".marketsieve/cache/yfinance-test"},
    )


def test_market_indicator_adapter_sorts_internal_equity_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RequestObserved(RuntimeError):
        pass

    def observe_request(_source: YFinanceSource, request: EquityBatchRequest) -> Any:
        identities = tuple(
            (item.instrument.mic, item.instrument.symbol) for item in request.instruments
        )
        assert identities == tuple(sorted(identities))
        assert len(identities) == len(set(identities))
        raise RequestObserved

    monkeypatch.setattr(YFinanceSource, "fetch", observe_request)
    specs = tuple(
        sorted(
            (
                MarketIndicatorSpec(
                    "us_rate_10y",
                    "^TNX",
                    "U.S. 10-year yield",
                    MarketIndicatorKind.YIELD,
                    "percent",
                ),
                MarketIndicatorSpec(
                    "usd_jpy", "JPY=X", "USD/JPY", MarketIndicatorKind.FX_RATE, "JPY_per_USD"
                ),
            ),
            key=lambda value: value.indicator_id,
        )
    )
    request = MarketIndicatorRequest(
        "market-indicators-yfinance",
        specs,
        date(2026, 8, 1),
        date(2026, 8, 7),
        30,
        3,
        0.0,
        {},
    )

    with pytest.raises(RequestObserved):
        YFinanceSource().fetch_market_indicators(request)


def _history(symbols: tuple[str, ...]) -> pd.DataFrame:
    dates = pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-05"])
    columns: dict[tuple[str, str], list[float]] = {}
    for offset, symbol in enumerate(symbols):
        columns[(symbol, "Open")] = [100 + offset, 101 + offset, 102 + offset]
        columns[(symbol, "High")] = [102 + offset, 103 + offset, 104 + offset]
        columns[(symbol, "Low")] = [99 + offset, 100 + offset, 101 + offset]
        columns[(symbol, "Close")] = [101 + offset, 102 + offset, 103 + offset]
        columns[(symbol, "Volume")] = [1000, 1100, 1200]
    return pd.DataFrame(columns, index=dates)


def _statement(values: dict[str, list[float]], *, quarterly: bool = False) -> pd.DataFrame:
    periods = (
        ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]
        if quarterly
        else ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]
    )
    return pd.DataFrame(
        values,
        index=pd.to_datetime(periods),
    ).T


class _Ticker:
    def __init__(self, symbol: str, session: Any = None) -> None:
        self.symbol = symbol
        self.session = session

    def history(self, **kwargs: Any) -> pd.DataFrame:
        del kwargs
        return pd.DataFrame()

    def get_info(self) -> dict[str, Any]:
        return {
            "shortName": "Microsoft",
            "exchange": "NMS",
            "currency": "USD",
            "financialCurrency": "USD",
            "marketCap": 1000,
            "sharesOutstanding": 100,
            "trailingPE": 10,
            "freeCashflow": 20,
            "debtToEquity": 29.118,
            "dividendYield": 0.75,
        }

    def get_income_stmt(self, *, freq: str) -> pd.DataFrame:
        assert freq in {"yearly", "quarterly"}
        return _statement(
            {
                "TotalRevenue": [160, 140, 120, 100],
                "OperatingIncome": [40, 35, 30, 25],
                "NetIncome": [32, 28, 24, 20],
            },
            quarterly=freq == "quarterly",
        )

    def get_balance_sheet(self, *, freq: str) -> pd.DataFrame:
        assert freq in {"yearly", "quarterly"}
        return _statement(
            {
                "TotalAssets": [500, 480, 460, 440],
                "StockholdersEquity": [300, 280, 260, 240],
                "TotalDebt": [50, 55, 60, 65],
            },
            quarterly=freq == "quarterly",
        )

    def get_cash_flow(self, *, freq: str) -> pd.DataFrame:
        assert freq in {"yearly", "quarterly"}
        return _statement(
            {
                "OperatingCashFlow": [45, 40, 35, 30],
                "CapitalExpenditure": [-10, -9, -8, -7],
                "FreeCashFlow": [35, 31, 27, 23],
            },
            quarterly=freq == "quarterly",
        )

    def get_actions(self, *, period: str) -> pd.DataFrame:
        assert period == "10y"
        return pd.DataFrame(
            {"Dividends": [Decimal("0.75")], "Stock Splits": [0]},
            index=pd.to_datetime(["2026-08-04"]),
        )

    def get_earnings_dates(self, *, limit: int) -> pd.DataFrame:
        assert limit == 100
        return pd.DataFrame(
            {
                "EPS Estimate": [Decimal("2.9")],
                "Reported EPS": [Decimal("3.1")],
                "Surprise(%)": [Decimal("6.9")],
            },
            index=pd.to_datetime(["2026-08-05"]),
        )


def _research_request(tmp_path: Path, evidence: tuple[str, ...]) -> SecurityResearchRequest:
    return SecurityResearchRequest(
        "market-yfinance",
        _instrument(),
        "MSFT",
        date(2023, 8, 8),
        date(2026, 8, 7),
        Adjustment.ADJUSTED,
        30,
        1,
        0.0,
        {"cache_dir": str(tmp_path / "cache")},
        evidence,
    )


def test_yfinance_research_honors_selected_evidence_domains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE,
        "download",
        lambda symbols, **kwargs: _history(tuple(symbols)),
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    price = YFinanceSource().fetch_research(_research_request(tmp_path, ("price",)))
    financials = YFinanceSource().fetch_research(_research_request(tmp_path, ("financials",)))

    assert price.bars and not price.company and not price.financials and not price.events
    assert not price.failures
    assert financials.financials and not financials.company and not financials.events
    assert not any(failure.field == "financial_currency" for failure in financials.failures)


def test_yfinance_batch_financials_preserve_only_required_currency_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    request = replace(_request(), evidence=("financials",))

    observation = YFinanceSource().fetch(request).observations[0]

    assert dict(observation.profile) == {"financial_currency": "USD"}
    assert observation.financials


def test_yfinance_source_fetches_adjusted_batches_profiles_and_statements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    def download(symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        calls.append({"symbols": symbols, **kwargs})
        return _history(symbols)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert imported.source_name == "yfinance"
    assert len(imported.observations) == 1
    observation = imported.observations[0]
    assert len(observation.bars) == 3
    assert observation.bars[-1].close == 103
    assert calls[0]["auto_adjust"] is True
    assert calls[0]["actions"] is True
    assert calls[0]["interval"] == "1d"
    assert calls[0]["threads"] is False
    assert dict(observation.profile)["market_cap"] == "1000"
    assert dict(observation.profile)["financial_currency"] == "USD"
    financials = dict(observation.financials)
    assert financials["total_assets"] == "500"
    assert financials["total_equity"] == "300"
    assert financials["capital_expenditure_ttm"] == "-34"
    assert financials["debt_to_equity"] == "0.29118"
    assert financials["dividend_yield"] == "0.0075"
    assert financials["revenue_ttm"] == "520"
    assert float(financials["revenue_cagr_3y"]) == pytest.approx(0.169607, rel=1e-5)


def test_yfinance_source_bounds_provider_bars_to_the_exact_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dates = pd.to_datetime(["2026-07-31", "2026-08-03", "2026-08-08"])
    columns = {
        ("MSFT", "Open"): [100, 101, 102],
        ("MSFT", "High"): [102, 103, 104],
        ("MSFT", "Low"): [99, 100, 101],
        ("MSFT", "Close"): [101, 102, 103],
        ("MSFT", "Volume"): [1000, 1100, 1200],
    }
    monkeypatch.setattr(
        source_module.YFINANCE,
        "download",
        lambda symbols, **kwargs: pd.DataFrame(columns, index=dates),
    )
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    request = replace(
        _request(),
        start=date(2026, 8, 1),
        end=date(2026, 8, 7),
        settings={"cache_dir": str(tmp_path / "cache")},
        evidence=("price",),
    )

    observation = (
        YFinanceSource(clock=lambda: datetime(2026, 8, 9, tzinfo=UTC))
        .fetch(request)
        .observations[0]
    )

    assert [bar.trading_date for bar in observation.bars] == [date(2026, 8, 3)]


def test_yfinance_source_fetches_detailed_security_research(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE,
        "download",
        lambda symbols, **kwargs: _history(tuple(symbols)),
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    request = SecurityResearchRequest(
        "market-yfinance",
        _instrument(),
        "MSFT",
        date(2023, 8, 8),
        date(2026, 8, 7),
        Adjustment.ADJUSTED,
        30,
        3,
        0.0,
        {"cache_dir": str(tmp_path / "cache")},
    )

    imported = YFinanceSource().fetch_research(request)

    assert imported.request == request
    assert len(imported.bars) == 3
    assert dict(imported.company)["name"] == "Microsoft"
    assert dict(imported.company)["debt_to_equity"] == "0.29118"
    assert {fact.period for fact in imported.financials} == {"annual", "quarterly"}
    assert {fact.concept for fact in imported.financials} >= {
        "revenue",
        "total_assets",
        "free_cash_flow",
    }
    assert {(event.event_type, event.effective_date) for event in imported.events} == {
        ("dividend", date(2026, 8, 4)),
        ("earnings", date(2026, 8, 5)),
    }
    assert imported.failures == ()


def test_yfinance_research_preserves_financial_and_dividend_currencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class CrossCurrencyTicker(_Ticker):
        def get_info(self) -> dict[str, Any]:
            info = super().get_info()
            info["financialCurrency"] = "EUR"
            return info

        def get_actions(self, *, period: str) -> pd.DataFrame:
            assert period == "10y"
            return pd.DataFrame(
                {
                    "Dividends": [Decimal("0.75")],
                    "Dividends FX": ["GBP"],
                    "Stock Splits": [0],
                },
                index=pd.to_datetime(["2026-08-04"]),
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE,
        "download",
        lambda symbols, **kwargs: _history(tuple(symbols)),
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", CrossCurrencyTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    request = SecurityResearchRequest(
        "market-yfinance",
        _instrument(),
        "MSFT",
        date(2023, 8, 8),
        date(2026, 8, 7),
        Adjustment.ADJUSTED,
        30,
        3,
        0.0,
        {"cache_dir": str(tmp_path / "cache")},
    )

    imported = YFinanceSource().fetch_research(request)

    assert {fact.currency for fact in imported.financials} == {"EUR"}
    dividend = next(event for event in imported.events if event.event_type == "dividend")
    assert dict(dividend.values) == {"amount": "0.75", "currency": "GBP"}


def test_yfinance_research_records_an_empty_company_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class EmptyInfoTicker(_Ticker):
        def get_info(self) -> dict[str, Any]:
            return {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE,
        "download",
        lambda symbols, **kwargs: _history(tuple(symbols)),
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", EmptyInfoTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    request = SecurityResearchRequest(
        "market-yfinance",
        _instrument(),
        "MSFT",
        date(2023, 8, 8),
        date(2026, 8, 7),
        Adjustment.ADJUSTED,
        30,
        3,
        0.0,
        {"cache_dir": str(tmp_path / "cache")},
    )

    imported = YFinanceSource().fetch_research(request)

    assert imported.company == ()
    assert any(
        failure.stage == "research"
        and failure.field == "company"
        and failure.reason == "provider_error"
        for failure in imported.failures
    )
    assert imported.financials == ()
    assert any(
        failure.stage == "research"
        and failure.field == "financial_currency"
        and failure.reason == "field_absent"
        for failure in imported.failures
    )


def test_yfinance_research_does_not_duplicate_a_failed_company_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class BrokenInfoTicker(_Ticker):
        def get_info(self) -> dict[str, Any]:
            raise TimeoutError("connection timed out")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE,
        "download",
        lambda symbols, **kwargs: _history(tuple(symbols)),
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", BrokenInfoTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    request = SecurityResearchRequest(
        "market-yfinance",
        _instrument(),
        "MSFT",
        date(2023, 8, 8),
        date(2026, 8, 7),
        Adjustment.ADJUSTED,
        30,
        1,
        0.0,
        {"cache_dir": str(tmp_path / "cache")},
    )

    imported = YFinanceSource().fetch_research(request)
    company_failures = [failure for failure in imported.failures if failure.field == "company"]

    assert len(company_failures) == 1
    assert company_failures[0].reason == "network_error"


def test_yfinance_research_records_unavailable_earnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class NoEarningsTicker(_Ticker):
        def get_earnings_dates(self, *, limit: int) -> Any:
            assert limit == 100
            return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE,
        "download",
        lambda symbols, **kwargs: _history(tuple(symbols)),
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", NoEarningsTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    request = SecurityResearchRequest(
        "market-yfinance",
        _instrument(),
        "MSFT",
        date(2023, 8, 8),
        date(2026, 8, 7),
        Adjustment.ADJUSTED,
        30,
        1,
        0.0,
        {"cache_dir": str(tmp_path / "cache")},
    )

    imported = YFinanceSource().fetch_research(request)

    assert any(
        failure.field == "earnings" and failure.reason == "field_absent"
        for failure in imported.failures
    )
    assert not any(event.event_type == "earnings" for event in imported.events)


def test_yfinance_research_does_not_label_share_counts_as_currency() -> None:
    frame = _statement({"Ordinary Shares Number": [100, 90, 80, 70]})

    facts = YFinanceSource._research_financials({("balance_sheet", "yearly"): frame}, "USD")

    assert not any(fact.concept == "shares_outstanding" for fact in facts)


@pytest.mark.parametrize(
    "value",
    (
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        "NaN",
        "Infinity",
    ),
)
def test_yfinance_source_rejects_non_finite_financial_values(value: object) -> None:
    assert source_module._text(value) is None
    assert source_module._financial_text("debtToEquity", value) is None
    assert source_module._financial_text("marketCap", value) is None


def test_yfinance_source_records_empty_partial_and_retry_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts = 0

    def download(symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        nonlocal attempts
        del symbols, kwargs
        attempts += 1
        if attempts == 1:
            raise RuntimeError("too many requests")
        return pd.DataFrame()

    class BrokenTicker(_Ticker):
        def get_info(self) -> dict[str, Any]:
            raise TimeoutError("connection timed out")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", BrokenTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())
    reasons = {(failure.stage, failure.reason) for failure in imported.failures}

    assert attempts == 6
    assert imported.observations[0].bars == ()
    assert imported.observations[0].profile == ()
    assert imported.observations[0].financials
    assert ("price", "history_empty") in reasons
    assert ("profile", "network_error") in reasons
    assert not any(
        failure.stage == "profile" and failure.reason == "field_absent"
        for failure in imported.failures
    )


def test_yfinance_progress_is_bounded_and_does_not_change_response_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    def clock() -> datetime:
        return datetime(2026, 8, 8, tzinfo=UTC)

    events: list[AcquisitionProgress] = []

    without_progress = YFinanceSource(clock=clock).fetch(_request())
    with_progress = YFinanceSource(clock=clock).fetch(_request(), progress=events.append)

    assert with_progress.response_hash == without_progress.response_hash
    assert [item.phase for item in events if item.state is AcquisitionProgressState.STARTED] == [
        "price",
        "company_financials",
    ]
    assert all(0 <= item.completed <= item.total for item in events)
    assert all(0 <= item.failure_count <= item.completed for item in events)
    for phase in {item.phase for item in events}:
        assert len([item for item in events if item.phase == phase]) <= 22


def test_yfinance_retry_progress_reports_the_bounded_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts = 0

    def download(symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        nonlocal attempts
        del kwargs
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Too Many Requests")
        return _history(symbols)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    monkeypatch.setattr("marketsieve_source_yfinance.source.time.sleep", lambda seconds: None)
    events: list[AcquisitionProgress] = []

    YFinanceSource().fetch(replace(_request(), retry_base_seconds=15.0), progress=events.append)

    retry = next(item for item in events if item.state is AcquisitionProgressState.RETRYING)
    assert (retry.attempt, retry.max_attempts, retry.retry_after_seconds) == (2, 3, 15.0)


@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (TimeoutError(), "network_error"),
        (RuntimeError("Could not resolve host query2.finance.yahoo.com"), "network_error"),
        (RuntimeError("Failed to connect to query2.finance.yahoo.com"), "network_error"),
        (RuntimeError("Corporate action data malformed"), "provider_error"),
        (RuntimeError("Too Many Requests"), "rate_limited"),
        (RuntimeError("possibly delisted; no timezone found"), "symbol_not_found"),
    ),
)
def test_yfinance_source_normalizes_failure_reasons(error: BaseException, reason: str) -> None:
    assert source_module._failure_reason(error) == reason


def test_yfinance_source_records_null_profile_as_provider_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class NullInfoTicker(_Ticker):
        def get_info(self) -> Any:
            return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", NullInfoTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert imported.observations[0].profile == ()
    assert any(
        failure.stage == "profile"
        and failure.field == "company"
        and failure.reason == "provider_error"
        for failure in imported.failures
    )
    assert not any(
        failure.stage == "profile" and failure.reason == "field_absent"
        for failure in imported.failures
    )


def test_yfinance_source_cancels_unstarted_profiles_on_interruption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started: list[str] = []

    class InterruptedTicker(_Ticker):
        def __init__(self, symbol: str, session: Any = None) -> None:
            super().__init__(symbol, session)
            started.append(symbol)

        def get_info(self) -> dict[str, Any]:
            raise KeyboardInterrupt

    instruments = (
        EquityBatchInstrument(_instrument("AAA"), "AAA", ("sp500",)),
        EquityBatchInstrument(_instrument("ZZZ"), "ZZZ", ("sp500",)),
    )
    request = replace(_request(*instruments), profile_workers=1)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", InterruptedTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    with pytest.raises(KeyboardInterrupt):
        YFinanceSource().fetch(request)

    assert started == ["AAA"]


def test_yfinance_source_stops_active_profile_after_interruption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = Event()
    release = Event()
    calls: list[str] = []
    submitted: list[Any] = []

    class RecordingExecutor(ThreadPoolExecutor):
        def submit(self, function: Any, /, *args: Any, **kwargs: Any) -> Any:
            future = super().submit(function, *args, **kwargs)
            submitted.append(future)
            return future

    class InterruptedTicker(_Ticker):
        def get_info(self) -> dict[str, Any]:
            calls.append("get_info")
            started.set()
            assert release.wait(1)
            return {}

        def get_income_stmt(self, *, freq: str) -> pd.DataFrame:
            calls.append(f"get_income_stmt:{freq}")
            return super().get_income_stmt(freq=freq)

    def interrupt_wait(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        assert started.wait(1)
        raise KeyboardInterrupt

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", InterruptedTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)
    monkeypatch.setattr(source_module, "ThreadPoolExecutor", RecordingExecutor)
    monkeypatch.setattr(source_module, "wait", interrupt_wait)

    with pytest.raises(KeyboardInterrupt):
        YFinanceSource().fetch(replace(_request(), profile_workers=1))

    release.set()
    with pytest.raises(source_module._ProfileAcquisitionCancelled):
        submitted[0].result(timeout=1)
    assert calls == ["get_info"]


def test_yfinance_source_bounds_batch_failure_without_per_symbol_price_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    download_attempts = 0
    history_attempts = 0

    class RateLimitedTicker(_Ticker):
        def history(self, **kwargs: Any) -> pd.DataFrame:
            nonlocal history_attempts
            del kwargs
            history_attempts += 1
            raise AssertionError("per-symbol price fallback must not run")

    def rate_limited_download(symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        nonlocal download_attempts
        del symbols, kwargs
        download_attempts += 1
        raise RuntimeError("too many requests")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", rate_limited_download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", RateLimitedTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert download_attempts == 3
    assert history_attempts == 0
    assert any(
        failure.stage == "price" and failure.reason == "rate_limited"
        for failure in imported.failures
    )
    assert not any(failure.reason == "history_empty" for failure in imported.failures)


def test_yfinance_source_preserves_best_partial_batch_when_retries_get_worse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts = 0
    instruments = (
        EquityBatchInstrument(_instrument("AAA"), "AAA", ("sp500",)),
        EquityBatchInstrument(_instrument("ZZZ"), "ZZZ", ("sp500",)),
    )

    def download(symbols: tuple[str, ...], **kwargs: Any) -> tuple[pd.DataFrame, dict[str, object]]:
        nonlocal attempts
        del kwargs
        assert symbols == ("AAA", "ZZZ")
        attempts += 1
        if attempts == 1:
            return _history(("AAA",)), {"ZZZ": RuntimeError("symbol not found")}
        raise RuntimeError("too many requests")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module, "_download_batch", download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request(*instruments))
    observations = {
        observation.requested.provider_symbol: observation for observation in imported.observations
    }

    assert attempts == 3
    assert observations["AAA"].bars
    assert observations["ZZZ"].bars == ()
    assert any(
        failure.instrument.symbol == "ZZZ"
        and failure.stage == "price"
        and failure.reason == "symbol_not_found"
        for failure in imported.failures
    )
    assert not any(
        failure.instrument.symbol == "AAA" and failure.stage == "price"
        for failure in imported.failures
    )


def test_yfinance_source_recovers_a_silently_empty_mixed_market_batch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []
    instruments = (
        EquityBatchInstrument(_instrument("AAA"), "AAA", ("sp500",)),
        EquityBatchInstrument(_instrument("BBB"), "BBB", ("sp500",)),
        EquityBatchInstrument(
            Instrument.create(
                symbol="CCC",
                mic="XTKS",
                currency="JPY",
                exchange_timezone="Asia/Tokyo",
            ),
            "CCC",
            ("topix500",),
        ),
        EquityBatchInstrument(
            Instrument.create(
                symbol="DDD",
                mic="XTKS",
                currency="JPY",
                exchange_timezone="Asia/Tokyo",
            ),
            "DDD",
            ("topix500",),
        ),
    )

    def download(symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        del kwargs
        calls.append(symbols)
        if any(symbol in {"AAA", "BBB"} for symbol in symbols) and any(
            symbol in {"CCC", "DDD"} for symbol in symbols
        ):
            return pd.DataFrame()
        return _history(symbols)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request(*instruments))

    assert calls == [
        ("AAA", "BBB", "CCC", "DDD"),
        ("AAA", "BBB", "CCC", "DDD"),
        ("AAA", "BBB", "CCC", "DDD"),
        ("CCC", "DDD"),
        ("AAA", "BBB"),
    ]
    assert all(observation.bars for observation in imported.observations)
    assert not any(failure.stage == "price" for failure in imported.failures)


def test_yfinance_source_caps_persistent_empty_batch_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0
    instruments = tuple(
        EquityBatchInstrument(_instrument(symbol), symbol, ("sp500",))
        for symbol in ("AAA", "BBB", "CCC", "DDD")
    )

    def download(symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        nonlocal calls
        del symbols, kwargs
        calls += 1
        return pd.DataFrame()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request(*instruments))

    assert calls == 6
    assert all(observation.bars == () for observation in imported.observations)
    assert {failure.reason for failure in imported.failures if failure.stage == "price"} == {
        "history_empty"
    }


def test_yfinance_source_recovers_only_a_silently_omitted_symbol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []
    instruments = (
        EquityBatchInstrument(_instrument("AAA"), "AAA", ("sp500",)),
        EquityBatchInstrument(_instrument("ZZZ"), "ZZZ", ("sp500",)),
    )

    def download(symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        del kwargs
        calls.append(symbols)
        if symbols == ("ZZZ",):
            return _history(symbols)
        frame = _history(symbols)
        for column in frame["ZZZ"].columns:
            frame[("ZZZ", column)] = float("nan")
        return frame

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request(*instruments))

    assert calls == [("AAA", "ZZZ"), ("AAA", "ZZZ"), ("AAA", "ZZZ"), ("ZZZ",)]
    assert all(observation.bars for observation in imported.observations)
    assert not any(failure.stage == "price" for failure in imported.failures)


def test_download_batch_exposes_yfinance_per_symbol_error_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Context:
        def __init__(self) -> None:
            self.errors: dict[str, object] = {}

    frame = pd.DataFrame()

    def download(context: Context, symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        del kwargs
        assert symbols == ("MSFT",)
        context.errors["MSFT"] = "DNSError('Could not resolve host')"
        return frame

    monkeypatch.setattr(source_module.YFINANCE_MULTI, "_DownloadCtx", Context)
    monkeypatch.setattr(source_module.YFINANCE_MULTI, "_download_impl", download)

    result, errors = source_module._download_batch(("MSFT",), timeout=30)

    assert result is frame
    assert errors == {"MSFT": "DNSError('Could not resolve host')"}


def test_download_batch_suppresses_provider_error_logs_and_restores_logger(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Context:
        def __init__(self) -> None:
            self.errors: dict[str, object] = {}

    logger = source_module.YFINANCE_UTILS.get_yf_logger()
    logger.disabled = False

    def download(context: Context, symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        del symbols, kwargs
        logger.error("raw provider exception must not escape")
        context.errors["MSFT"] = RuntimeError("too many requests")
        return pd.DataFrame()

    monkeypatch.setattr(source_module.YFINANCE_MULTI, "_DownloadCtx", Context)
    monkeypatch.setattr(source_module.YFINANCE_MULTI, "_download_impl", download)

    _, errors = source_module._download_batch(("MSFT",), timeout=30)

    assert set(errors) == {"MSFT"}
    assert str(errors["MSFT"]) == "too many requests"
    assert "raw provider exception" not in caplog.text
    assert logger.disabled is False


def test_yfinance_source_retries_and_classifies_swallowed_symbol_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts = 0

    def download(symbols: tuple[str, ...], **kwargs: Any) -> tuple[pd.DataFrame, dict[str, str]]:
        nonlocal attempts
        del kwargs
        attempts += 1
        return pd.DataFrame(), {
            symbols[0]: (
                "DNSError('Failed to perform: Could not resolve host query2.finance.yahoo.com')"
            )
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module, "_download_batch", download)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert attempts == 3
    assert any(
        failure.stage == "price" and failure.reason == "network_error"
        for failure in imported.failures
    )
    assert not any(failure.reason == "history_empty" for failure in imported.failures)


def test_yfinance_source_surfaces_hidden_financial_statement_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed_hide_values: list[bool] = []
    original_hide_value = source_module.YFINANCE.config.debug.hide_exceptions

    class HiddenErrorTicker(_Ticker):
        def get_cash_flow(self, *, freq: str) -> pd.DataFrame:
            assert freq == "quarterly"
            hidden = source_module.YFINANCE.config.debug.hide_exceptions
            observed_hide_values.append(hidden)
            if hidden:
                return pd.DataFrame()
            raise RuntimeError("too many requests")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", HiddenErrorTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert observed_hide_values == [False, False, False]
    assert source_module.YFINANCE.config.debug.hide_exceptions is original_hide_value
    assert any(
        failure.stage == "financials"
        and failure.field == "quarterly_cash_flow"
        and failure.reason == "rate_limited"
        for failure in imported.failures
    )


def test_yfinance_source_does_not_compress_missing_statement_periods(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    columns = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31", "2021-12-31"])

    class MissingPeriodsTicker(_Ticker):
        def get_income_stmt(self, *, freq: str) -> pd.DataFrame:
            if freq == "quarterly":
                return pd.DataFrame(
                    [[160.0, float("nan"), 120.0, 100.0, 80.0]],
                    index=["TotalRevenue"],
                    columns=columns,
                )
            return pd.DataFrame(
                [[float("nan"), 140.0, 120.0, 100.0, 80.0]],
                index=["TotalRevenue"],
                columns=columns,
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", MissingPeriodsTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    financials = dict(YFinanceSource().fetch(_request()).observations[0].financials)

    assert "revenue_ttm" not in financials
    assert "revenue_cagr_3y" not in financials


def test_yfinance_source_uses_populated_statement_alias_after_empty_preferred_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class EmptyPreferredAliasTicker(_Ticker):
        def get_income_stmt(self, *, freq: str) -> pd.DataFrame:
            if freq == "quarterly":
                return _statement(
                    {
                        "EBITDA": [float("nan")] * 4,
                        "Normalized EBITDA": [40.0, 30.0, 20.0, 10.0],
                    },
                    quarterly=True,
                )
            return super().get_income_stmt(freq=freq)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", EmptyPreferredAliasTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    financials = dict(YFinanceSource().fetch(_request()).observations[0].financials)

    assert financials["ebitda_ttm"] == "100"


def test_yfinance_source_rejects_non_contiguous_fiscal_periods(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class MissingFiscalPeriodTicker(_Ticker):
        def get_income_stmt(self, *, freq: str) -> pd.DataFrame:
            periods = (
                ["2025-12-31", "2025-06-30", "2025-03-31", "2024-12-31"]
                if freq == "quarterly"
                else ["2025-12-31", "2024-12-31", "2022-12-31", "2021-12-31"]
            )
            return pd.DataFrame(
                [[160.0, 140.0, 120.0, 100.0]],
                index=["TotalRevenue"],
                columns=pd.to_datetime(periods),
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", MissingFiscalPeriodTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    financials = dict(YFinanceSource().fetch(_request()).observations[0].financials)

    assert "revenue_ttm" not in financials
    assert "revenue_cagr_3y" not in financials


def test_yfinance_source_rejects_non_finite_volume_instead_of_zero_filling() -> None:
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Volume": [float("nan")],
        },
        index=pd.to_datetime(["2026-08-03"]),
    )

    bars = YFinanceSource._bars(
        frame,
        instrument=_instrument(),
        adjustment=Adjustment.ADJUSTED,
        retrieved_at=datetime(2026, 8, 3, tzinfo=UTC),
        version="1.5.2",
    )

    assert bars == ()


def test_yfinance_source_split_adjusts_volume_with_adjusted_prices() -> None:
    frame = pd.DataFrame(
        {
            "Open": [50.0, 50.0, 51.0],
            "High": [51.0, 51.0, 52.0],
            "Low": [49.0, 49.0, 50.0],
            "Close": [50.0, 50.0, 51.0],
            "Volume": [100, 200, 210],
            "Stock Splits": [0.0, 2.0, 0.0],
        },
        index=pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-05"]),
    )

    bars = YFinanceSource._bars(
        frame,
        instrument=_instrument(),
        adjustment=Adjustment.ADJUSTED,
        retrieved_at=datetime(2026, 8, 7, tzinfo=UTC),
        version="1.5.2",
    )

    assert [bar.volume for bar in bars] == [200, 200, 210]
    assert bars[0].close * bars[0].volume == bars[1].close * bars[1].volume


def test_yfinance_source_ignores_cross_market_alignment_gaps() -> None:
    frame = _history(("MSFT",))["MSFT"]
    frame.loc[pd.Timestamp("2026-08-06")] = [float("nan")] * len(frame.columns)
    frame.loc[pd.Timestamp("2026-08-06"), "Volume"] = 0

    bars = YFinanceSource._bars(
        frame,
        instrument=_instrument(),
        adjustment=Adjustment.ADJUSTED,
        retrieved_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        version="1.5.2",
    )

    assert len(bars) == 3
    assert bars[-1].trading_date == date(2026, 8, 5)


def test_yfinance_source_preserves_split_on_a_price_less_event_row() -> None:
    frame = pd.DataFrame(
        {
            "Open": [50.0, float("nan"), 51.0],
            "High": [51.0, float("nan"), 52.0],
            "Low": [49.0, float("nan"), 50.0],
            "Close": [50.0, float("nan"), 51.0],
            "Volume": [100, 0, 210],
            "Stock Splits": [0.0, 2.0, 0.0],
        },
        index=pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-05"]),
    )

    bars = YFinanceSource._bars(
        frame,
        instrument=_instrument(),
        adjustment=Adjustment.ADJUSTED,
        retrieved_at=datetime(2026, 8, 7, tzinfo=UTC),
        version="1.5.2",
    )

    assert [bar.volume for bar in bars] == [200, 210]


def test_yfinance_source_does_not_treat_zero_filled_volume_as_observed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frame = _history(("MSFT",))
    frame.loc[pd.Timestamp("2026-08-05"), ("MSFT", "Volume")] = 0
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert imported.observations[0].bars[-1].volume == 0
    assert any(
        failure.stage == "volume"
        and failure.field == "volume_20d"
        and failure.reason == "field_absent"
        for failure in imported.failures
    )


def test_yfinance_source_rejects_history_behind_latest_market_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    instruments = (
        EquityBatchInstrument(_instrument("AAA"), "AAA", ("sp500",)),
        EquityBatchInstrument(_instrument("ZZZ"), "ZZZ", ("sp500",)),
    )
    frame = _history(("AAA", "ZZZ"))
    for trading_day in ("2026-08-04", "2026-08-05"):
        frame.loc[pd.Timestamp(trading_day), "AAA"] = float("nan")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request(*instruments))
    observations = {
        observation.requested.provider_symbol: observation for observation in imported.observations
    }

    assert observations["AAA"].bars == ()
    assert observations["ZZZ"].bars[-1].trading_date == date(2026, 8, 5)
    assert any(
        failure.instrument.symbol == "AAA"
        and failure.stage == "price"
        and failure.reason == "stale_history"
        for failure in imported.failures
    )


def test_yfinance_source_accepts_one_day_provider_publication_lag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    instruments = (
        EquityBatchInstrument(_instrument("AAA"), "AAA", ("sp500",)),
        EquityBatchInstrument(_instrument("ZZZ"), "ZZZ", ("sp500",)),
    )
    frame = _history(("AAA", "ZZZ"))
    frame.loc[pd.Timestamp("2026-08-05"), "AAA"] = float("nan")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request(*instruments))
    observations = {
        observation.requested.provider_symbol: observation for observation in imported.observations
    }

    assert observations["AAA"].bars[-1].trading_date == date(2026, 8, 4)
    assert observations["ZZZ"].bars[-1].trading_date == date(2026, 8, 5)
    assert not any(failure.reason == "stale_history" for failure in imported.failures)


def test_yfinance_source_rejects_a_market_reference_far_before_request_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frame = _history(("MSFT",))
    frame.index = pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert imported.observations[0].bars == ()
    assert any(
        failure.stage == "price" and failure.reason == "stale_history"
        for failure in imported.failures
    )


@pytest.mark.parametrize(
    ("instrument", "retrieved_at", "expected_dates"),
    (
        (
            Instrument.create(
                symbol="7203",
                mic="XTKS",
                currency="JPY",
                exchange_timezone="Asia/Tokyo",
            ),
            datetime(2026, 8, 7, 5, 0, tzinfo=UTC),
            (date(2026, 8, 6),),
        ),
        (
            _instrument(),
            datetime(2026, 8, 7, 19, 59, tzinfo=UTC),
            (date(2026, 8, 6),),
        ),
        (
            _instrument(),
            datetime(2026, 8, 7, 20, 1, tzinfo=UTC),
            (date(2026, 8, 6), date(2026, 8, 7)),
        ),
    ),
)
def test_yfinance_source_excludes_only_in_progress_daily_sessions(
    instrument: Instrument,
    retrieved_at: datetime,
    expected_dates: tuple[date, ...],
) -> None:
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1000, 1100],
        },
        index=pd.to_datetime(["2026-08-06", "2026-08-07"]),
    )

    bars = YFinanceSource._bars(
        frame,
        instrument=instrument,
        adjustment=Adjustment.ADJUSTED,
        retrieved_at=retrieved_at,
        version="1.5.2",
    )

    assert tuple(bar.trading_date for bar in bars) == expected_dates


def test_yfinance_source_rejects_historical_non_session_rows() -> None:
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1000, 1100],
        },
        index=pd.to_datetime(["2026-08-01", "2026-08-03"]),
    )

    bars = YFinanceSource._bars(
        frame,
        instrument=_instrument(),
        adjustment=Adjustment.ADJUSTED,
        retrieved_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        version="1.5.2",
    )

    assert tuple(bar.trading_date for bar in bars) == (date(2026, 8, 3),)


@pytest.mark.parametrize(
    ("retrieved_at", "expected"),
    (
        (datetime(2025, 7, 3, 16, 59, tzinfo=UTC), ()),
        (datetime(2025, 7, 3, 17, 1, tzinfo=UTC), (date(2025, 7, 3),)),
    ),
)
def test_yfinance_source_uses_the_actual_early_close_for_each_date(
    retrieved_at: datetime,
    expected: tuple[date, ...],
) -> None:
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Volume": [1000],
        },
        index=pd.to_datetime(["2025-07-03"]),
    )

    bars = YFinanceSource._bars(
        frame,
        instrument=_instrument(),
        adjustment=Adjustment.ADJUSTED,
        retrieved_at=retrieved_at,
        version="1.5.2",
    )

    assert tuple(bar.trading_date for bar in bars) == expected


def test_yfinance_source_clamps_transport_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def request(session: Any, *args: Any, **kwargs: Any) -> object:
        del session, args
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(Session, "request", request)
    session = source_module._BoundedSession(17)
    try:
        assert session.impersonate == "chrome"
        session.request("GET", "https://example.invalid", timeout=99)
    finally:
        session.close()

    assert captured["timeout"] == 17


def test_yfinance_source_records_completion_timestamps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    times = iter(
        (
            datetime(2026, 8, 7, 0, 0, tzinfo=UTC),
            datetime(2026, 8, 7, 0, 1, tzinfo=UTC),
            datetime(2026, 8, 7, 0, 2, tzinfo=UTC),
        )
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource(clock=lambda: next(times)).fetch(_request())

    observation = imported.observations[0]
    assert observation.bars[0].available_at == datetime(2026, 8, 7, 0, 1, tzinfo=UTC)
    assert observation.retrieved_at == datetime(2026, 8, 7, 0, 2, tzinfo=UTC)
    assert imported.retrieved_at == observation.retrieved_at


def test_yfinance_source_evaluates_session_completion_at_request_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    times = iter(
        (
            datetime(2026, 8, 7, 19, 59, tzinfo=UTC),
            datetime(2026, 8, 7, 20, 1, tzinfo=UTC),
            datetime(2026, 8, 7, 20, 2, tzinfo=UTC),
        )
    )
    frame = _history(("MSFT",))
    frame.loc[pd.Timestamp("2026-08-07")] = [104, 106, 103, 105, 1300]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource(clock=lambda: next(times)).fetch(_request())

    observation = imported.observations[0]
    assert tuple(bar.trading_date for bar in observation.bars) == (
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
    )
    assert {bar.available_at for bar in observation.bars} == {
        datetime(2026, 8, 7, 20, 1, tzinfo=UTC)
    }


def test_yfinance_source_uses_one_session_cutoff_across_price_batches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    instruments = (
        EquityBatchInstrument(_instrument("AAA"), "AAA", ("sp500",)),
        EquityBatchInstrument(_instrument("BBB"), "BBB", ("sp500",)),
    )
    request = replace(_request(*instruments), batch_size=1)
    times = iter(
        (
            datetime(2026, 8, 7, 19, 59, tzinfo=UTC),
            datetime(2026, 8, 7, 20, 0, 30, tzinfo=UTC),
            datetime(2026, 8, 7, 20, 1, tzinfo=UTC),
            datetime(2026, 8, 7, 20, 2, tzinfo=UTC),
        )
    )

    def history(symbols: tuple[str, ...], **kwargs: Any) -> pd.DataFrame:
        del kwargs
        frame = _history(symbols)
        frame.loc[pd.Timestamp("2026-08-07")] = [104, 106, 103, 105, 1300]
        return frame

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", history)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource(clock=lambda: next(times)).fetch(request)

    assert {
        observation.requested.provider_symbol: tuple(bar.trading_date for bar in observation.bars)
        for observation in imported.observations
    } == {
        "AAA": (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)),
        "BBB": (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)),
    }
    assert not any(failure.reason == "stale_history" for failure in imported.failures)


def test_yfinance_source_preserves_profile_when_one_statement_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class PartialTicker(_Ticker):
        def get_balance_sheet(self, *, freq: str) -> pd.DataFrame:
            del freq
            raise RuntimeError("provider statement unavailable")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", PartialTicker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())
    observation = imported.observations[0]

    assert dict(observation.profile)["name"] == "Microsoft"
    assert "total_assets" not in dict(observation.financials)
    assert any(
        failure.stage == "financials"
        and failure.field == "balance_sheet"
        and failure.reason == "provider_error"
        for failure in imported.failures
    )


@pytest.mark.parametrize(
    ("instrument", "provider_symbol"),
    (
        (_instrument("GSPC"), "^GSPC"),
        (
            _instrument("1308", mic="XTKS", currency="JPY", timezone="Asia/Tokyo"),
            "1308.T",
        ),
    ),
)
def test_yfinance_source_does_not_fetch_profiles_for_benchmarks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    instrument: Instrument,
    provider_symbol: str,
) -> None:
    benchmark = EquityBatchInstrument(instrument, provider_symbol, ("sp500",), True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        source_module.YFINANCE, "download", lambda symbols, **kwargs: _history(symbols)
    )
    monkeypatch.setattr(
        source_module.YFINANCE,
        "Ticker",
        lambda symbol, session=None: pytest.fail(f"benchmark profile fetched: {symbol}"),
    )
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request(benchmark))

    assert imported.observations[0].profile == ()
    assert imported.failures == ()


@pytest.mark.parametrize(
    ("close_after_split", "split"),
    ((10.0, 10.0), (25.0, 4.0), (50.05, 2.0), (66.7, 1.5)),
)
def test_yfinance_source_rejects_adjusted_history_with_unadjusted_split_jump(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    close_after_split: float,
    split: float,
) -> None:
    frame = _history(("MSFT",))
    frame[("MSFT", "Close")] = [100.0, close_after_split, close_after_split * 1.05]
    frame[("MSFT", "Stock Splits")] = [0.0, split, 0.0]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert imported.observations[0].bars == ()
    assert any(
        failure.stage == "price" and failure.reason == "corporate_action_mismatch"
        for failure in imported.failures
    )


def test_yfinance_source_keeps_large_split_day_market_return(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frame = _history(("MSFT",))
    frame[("MSFT", "Close")] = [100.0, 75.0, 76.0]
    frame[("MSFT", "Open")] = [100.0, 75.0, 76.0]
    frame[("MSFT", "High")] = [101.0, 76.0, 77.0]
    frame[("MSFT", "Low")] = [99.0, 74.0, 75.0]
    frame[("MSFT", "Stock Splits")] = [0.0, 1.5, 0.0]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert len(imported.observations[0].bars) == 3
    assert not any(failure.reason == "corporate_action_mismatch" for failure in imported.failures)


def test_yfinance_source_skips_malformed_close_without_rejecting_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frame = _history(("MSFT",))
    frame[("MSFT", "Close")] = [100.0, "bad", 102.0]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert len(imported.observations[0].bars) == 2
    assert not any(failure.reason == "corporate_action_mismatch" for failure in imported.failures)


def test_yfinance_source_skips_empty_batch_alignment_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frame = _history(("MSFT",))
    frame[("MSFT", "Stock Splits")] = [0.0, 0.0, 0.0]
    for field in ("Open", "High", "Low", "Close", "Volume", "Stock Splits"):
        frame.loc[frame.index[1], ("MSFT", field)] = float("nan")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert len(imported.observations[0].bars) == 2
    assert not any(failure.reason == "corporate_action_mismatch" for failure in imported.failures)


def test_yfinance_source_rejects_split_jump_across_action_only_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frame = _history(("MSFT",))
    frame[("MSFT", "Close")] = [100.0, float("nan"), 10.0]
    frame[("MSFT", "Open")] = [100.0, float("nan"), 10.0]
    frame[("MSFT", "High")] = [101.0, float("nan"), 10.1]
    frame[("MSFT", "Low")] = [99.0, float("nan"), 9.9]
    frame[("MSFT", "Volume")] = [100.0, float("nan"), 1000.0]
    frame[("MSFT", "Stock Splits")] = [0.0, 10.0, 0.0]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(source_module.YFINANCE, "download", lambda symbols, **kwargs: frame)
    monkeypatch.setattr(source_module.YFINANCE, "Ticker", _Ticker)
    monkeypatch.setattr(source_module.YFINANCE, "set_tz_cache_location", lambda value: None)

    imported = YFinanceSource().fetch(_request())

    assert imported.observations[0].bars == ()
    assert any(
        failure.stage == "price" and failure.reason == "corporate_action_mismatch"
        for failure in imported.failures
    )


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("MARKETSIEVE_LIVE_YFINANCE") != "1",
    reason="set MARKETSIEVE_LIVE_YFINANCE=1 to run the explicit provider smoke",
)
def test_yfinance_live_smoke_jp_us_and_five_benchmarks(tmp_path: Path) -> None:
    values = (
        EquityBatchInstrument(
            Instrument.create(
                symbol="7203",
                mic="XTKS",
                currency="JPY",
                exchange_timezone="Asia/Tokyo",
            ),
            "7203.T",
            ("nikkei225", "topix500"),
        ),
        EquityBatchInstrument(_instrument("MSFT"), "MSFT", ("nasdaq100", "sp500")),
        EquityBatchInstrument(_instrument("DJI"), "^DJI", ("dow30",), True),
        EquityBatchInstrument(_instrument("GSPC"), "^GSPC", ("sp500",), True),
        EquityBatchInstrument(_instrument("NDX"), "^NDX", ("nasdaq100",), True),
        EquityBatchInstrument(
            Instrument.create(
                symbol="N225", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
            ),
            "^N225",
            ("nikkei225",),
            True,
        ),
        EquityBatchInstrument(
            Instrument.create(
                symbol="1308", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
            ),
            "1308.T",
            ("topix500",),
            True,
        ),
    )
    request = EquityBatchRequest(
        "live-yfinance",
        tuple(sorted(values, key=lambda value: (value.instrument.mic, value.instrument.symbol))),
        date.today() - timedelta(days=365),
        date.today(),
        Adjustment.ADJUSTED,
        10,
        1,
        30,
        3,
        2.0,
        {"cache_dir": str(tmp_path / "cache")},
    )

    imported = YFinanceSource().fetch(request)

    assert len(imported.observations) == len(values)
    observations = {
        observation.requested.provider_symbol: observation for observation in imported.observations
    }
    bar_counts = {symbol: len(observation.bars) for symbol, observation in observations.items()}
    required = ("7203.T", "MSFT", "^DJI", "^GSPC", "^NDX", "^N225", "1308.T")
    missing_symbols = [symbol for symbol in required if not observations[symbol].bars]
    assert not missing_symbols, {
        "missing_symbols": missing_symbols,
        "bar_counts": bar_counts,
        "failures": [
            (failure.instrument.symbol, failure.stage, failure.field, failure.reason)
            for failure in imported.failures
        ],
    }
