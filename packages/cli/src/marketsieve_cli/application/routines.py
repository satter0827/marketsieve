"""One-command daily Close Brief orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Protocol

from marketsieve import (
    AnalysisContext,
    BalancedMediumTermPolicy,
    DecisionPolicy,
    DecisionReport,
    MarketSession,
    PersonalInvestmentContext,
    PortfolioSnapshot,
)
from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument


class PortfolioReader(Protocol):
    def latest(self) -> tuple[str, PortfolioSnapshot, str]: ...


class DailyDataService(Protocol):
    def fetch(
        self,
        profile_name: str,
        instrument_key: str,
        start: date,
        end: date,
        adjustment: str,
        kind: str = "daily_bars",
    ) -> dict[str, object]: ...

    def bars(self, profile: str, instrument: str) -> tuple[DailyBar, ...]: ...


class DecisionReportRepository(Protocol):
    def put(self, report: DecisionReport) -> DecisionReport: ...

    def latest(self, session: MarketSession) -> DecisionReport: ...


class RoutineConfiguration(Protocol):
    def daily_profile(self, market: str) -> tuple[str, int]: ...


MARKET_CURRENCY = {"jp": "JPY", "us": "USD"}
MARKET_SESSION = {"jp": MarketSession.JP_CLOSE, "us": MarketSession.US_CLOSE}


class DailyBriefService:
    """Acquire configured market data and persist one deterministic report."""

    def __init__(
        self,
        portfolios: PortfolioReader,
        data: DailyDataService,
        reports: DecisionReportRepository,
        configuration: RoutineConfiguration,
        report_factory: Callable[..., DecisionReport],
        policy: DecisionPolicy | None = None,
    ) -> None:
        self._portfolios = portfolios
        self._data = data
        self._reports = reports
        self._configuration = configuration
        self._report_factory = report_factory
        self._policy = policy or BalancedMediumTermPolicy()

    def run(self, market: str, *, as_of: datetime) -> DecisionReport:
        if market not in MARKET_SESSION:
            raise ValueError("market must be jp or us")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("daily as_of must include a UTC offset")
        _, portfolio, _ = self._portfolios.latest()
        if portfolio.as_of.astimezone(UTC) > as_of.astimezone(UTC):
            raise ValueError("daily as_of must not predate the portfolio snapshot")
        selected = self._select_portfolio(portfolio, market)
        if not selected.holdings and not selected.watch_items:
            raise ValueError(f"portfolio contains no {market} instruments")

        profile, lookback_days = self._configuration.daily_profile(market)
        bars_by_instrument: dict[tuple[str, str], tuple[DailyBar, ...]] = {}
        diagnostics: list[str] = []
        for instrument in self._instruments(selected):
            key = self._key(instrument)
            local_end = as_of.astimezone(instrument.exchange_timezone).date()
            try:
                self._data.fetch(
                    profile,
                    key,
                    local_end - timedelta(days=lookback_days),
                    local_end,
                    "raw",
                )
                bars = self._data.bars(profile, key)
                bars_by_instrument[(instrument.mic, instrument.symbol)] = tuple(
                    bar for bar in bars if bar.available_at.astimezone(UTC) <= as_of.astimezone(UTC)
                )
            except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
                diagnostics.append(f"{key}: price acquisition failed ({type(error).__name__})")
                bars_by_instrument[(instrument.mic, instrument.symbol)] = ()

        weights = self._position_weights(selected, bars_by_instrument)
        holdings = {
            (item.instrument.mic, item.instrument.symbol): item for item in selected.holdings
        }
        decisions = tuple(
            self._policy.evaluate(
                AnalysisContext(
                    instrument,
                    as_of,
                    bars_by_instrument[(instrument.mic, instrument.symbol)],
                    PersonalInvestmentContext(),
                    holdings.get((instrument.mic, instrument.symbol)),
                    weights.get((instrument.mic, instrument.symbol)),
                )
            )
            for instrument in self._instruments(selected)
        )
        session = MARKET_SESSION[market]
        try:
            previous_report_id = self._reports.latest(session).report_id
        except LookupError:
            previous_report_id = None
        report = self._report_factory(
            session,
            as_of,
            selected,
            decisions,
            diagnostics=tuple(sorted(diagnostics)),
            previous_report_id=previous_report_id,
        )
        stored = self._reports.put(report)
        if all(item.action.value == "indeterminate" for item in stored.decisions):
            raise RuntimeError(
                f"all {market} instruments are indeterminate; latest report was not updated"
            )
        return stored

    @staticmethod
    def _select_portfolio(portfolio: PortfolioSnapshot, market: str) -> PortfolioSnapshot:
        currency = MARKET_CURRENCY[market]
        return PortfolioSnapshot(
            portfolio.as_of,
            tuple(item for item in portfolio.holdings if item.instrument.currency == currency),
            tuple(item for item in portfolio.watch_items if item.instrument.currency == currency),
            portfolio.source,
        )

    @staticmethod
    def _instruments(portfolio: PortfolioSnapshot) -> tuple[Instrument, ...]:
        values = [item.instrument for item in portfolio.holdings]
        values.extend(item.instrument for item in portfolio.watch_items)
        return tuple(sorted(values, key=lambda item: (item.mic, item.symbol)))

    @staticmethod
    def _key(instrument: Instrument) -> str:
        return f"{instrument.mic}:{instrument.symbol}"

    @staticmethod
    def _position_weights(
        portfolio: PortfolioSnapshot,
        bars: dict[tuple[str, str], tuple[DailyBar, ...]],
    ) -> dict[tuple[str, str], Decimal]:
        values: dict[tuple[str, str], Decimal] = {}
        for holding in portfolio.holdings:
            identity = (holding.instrument.mic, holding.instrument.symbol)
            history = bars[identity]
            if history:
                values[identity] = holding.quantity * history[-1].close
        total = sum(values.values(), start=Decimal(0))
        if total <= 0:
            return {}
        with localcontext() as context:
            context.prec = 28
            return {identity: value / total for identity, value in values.items()}
