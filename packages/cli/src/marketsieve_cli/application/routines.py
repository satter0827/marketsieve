"""One-command daily Close Brief orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Protocol

from marketsieve import (
    AnalysisContext,
    BalancedMediumTermPolicy,
    DecisionPolicy,
    DecisionReport,
    InstrumentDecision,
    MarketSession,
    PersonalInvestmentContext,
    PortfolioSnapshot,
    ScreeningReport,
    candidate_order_key,
)
from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument
from marketsieve.financial import FinancialTrendReport


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

    def financial_trend(
        self, profile: str, instrument: str, as_of: datetime
    ) -> FinancialTrendReport: ...

    def next_earnings_date(self, profile: str, instrument: str, as_of: datetime) -> date | None: ...

    def valuation_history(
        self, profile: str, instrument: str, as_of: datetime
    ) -> tuple[tuple[str, str], ...]: ...

    def fundamental_changes(
        self, profile: str, instrument: str, as_of: datetime
    ) -> tuple[tuple[str, str], ...]: ...


class DecisionReportRepository(Protocol):
    def put(self, report: DecisionReport) -> DecisionReport: ...

    def latest(self, session: MarketSession) -> DecisionReport: ...


class RoutineConfiguration(Protocol):
    def daily_profile(self, market: str) -> tuple[str, int, int]: ...

    def weekly_max_age_days(self) -> int: ...


class ScreeningReportReader(Protocol):
    def latest_report(self, market: str) -> ScreeningReport: ...


MARKET_CURRENCY = {"jp": "JPY", "us": "USD"}
MARKET_SESSION = {"jp": MarketSession.JP_CLOSE, "us": MarketSession.US_CLOSE}


@dataclass(frozen=True, slots=True)
class _OptionalContext:
    next_earnings_date: date | None = None
    revenue_growth: Decimal | None = None
    eps_growth: Decimal | None = None
    free_cash_flow: Decimal | None = None
    valuation: tuple[tuple[str, str], ...] = ()
    fundamentals: tuple[tuple[str, str], ...] = ()
    evidence_ids: tuple[str, ...] = ()


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

        profile, lookback_days, financial_lookback_days = self._configuration.daily_profile(market)
        bars_by_instrument: dict[tuple[str, str], tuple[DailyBar, ...]] = {}
        optional_by_instrument: dict[tuple[str, str], _OptionalContext] = {}
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
            optional_by_instrument[(instrument.mic, instrument.symbol)] = self._optional_context(
                profile,
                instrument,
                as_of,
                financial_lookback_days,
                diagnostics,
            )

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
                    optional_by_instrument[(instrument.mic, instrument.symbol)].next_earnings_date,
                    optional_by_instrument[(instrument.mic, instrument.symbol)].revenue_growth,
                    optional_by_instrument[(instrument.mic, instrument.symbol)].eps_growth,
                    optional_by_instrument[(instrument.mic, instrument.symbol)].free_cash_flow,
                    optional_by_instrument[(instrument.mic, instrument.symbol)].valuation,
                    optional_by_instrument[(instrument.mic, instrument.symbol)].fundamentals,
                    input_evidence_ids=optional_by_instrument[
                        (instrument.mic, instrument.symbol)
                    ].evidence_ids,
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

    def _optional_context(
        self,
        profile: str,
        instrument: Instrument,
        as_of: datetime,
        financial_lookback_days: int,
        diagnostics: list[str],
    ) -> _OptionalContext:
        key = self._key(instrument)
        local_end = as_of.astimezone(instrument.exchange_timezone).date()
        trend: FinancialTrendReport | None = None
        fundamentals: tuple[tuple[str, str], ...] = ()
        try:
            self._data.fetch(
                profile,
                key,
                local_end - timedelta(days=financial_lookback_days),
                local_end,
                "raw",
                "financials",
            )
            trend = self._data.financial_trend(profile, key, as_of)
            fundamentals = self._data.fundamental_changes(profile, key, as_of)
        except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
            diagnostics.append(f"{key}: financial acquisition failed ({type(error).__name__})")
        earnings: date | None = None
        try:
            self._data.fetch(
                profile,
                key,
                local_end - timedelta(days=30),
                local_end + timedelta(days=30),
                "raw",
                "events",
            )
            earnings = self._data.next_earnings_date(profile, key, as_of)
        except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
            diagnostics.append(f"{key}: event acquisition failed ({type(error).__name__})")
        valuation: tuple[tuple[str, str], ...] = ()
        try:
            valuation = self._data.valuation_history(profile, key, as_of)
        except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
            diagnostics.append(f"{key}: valuation history failed ({type(error).__name__})")
        if trend is None:
            return _OptionalContext(
                next_earnings_date=earnings,
                valuation=valuation,
                fundamentals=fundamentals,
            )
        return _OptionalContext(
            earnings,
            self._metric(trend, "revenue_growth"),
            self._metric(trend, "eps_growth"),
            self._metric(trend, "free_cash_flow"),
            valuation,
            fundamentals,
            (trend.evidence_id,),
        )

    @staticmethod
    def _metric(trend: FinancialTrendReport, name: str) -> Decimal | None:
        metric = trend.metric(name)
        return metric.value if metric is not None else None

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


class WeeklyBriefService:
    """Combine eligible daily reports without acquisition or recalculation."""

    def __init__(
        self,
        reports: DecisionReportRepository,
        configuration: RoutineConfiguration,
        report_factory: Callable[..., DecisionReport],
        screening: ScreeningReportReader | None = None,
    ) -> None:
        self._reports = reports
        self._configuration = configuration
        self._report_factory = report_factory
        self._screening = screening

    def run(self, *, as_of: datetime) -> DecisionReport:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("weekly as_of must include a UTC offset")
        maximum_age = timedelta(days=self._configuration.weekly_max_age_days())
        daily_reports = tuple(
            self._eligible(session, market, as_of, maximum_age)
            for session, market in (
                (MarketSession.JP_CLOSE, "jp"),
                (MarketSession.US_CLOSE, "us"),
            )
        )
        identities = {
            (item.policy_name, item.policy_version, item.policy_settings) for item in daily_reports
        }
        if len(identities) != 1:
            raise ValueError("daily reports use incompatible decision policies")
        portfolio = PortfolioSnapshot(
            max(item.portfolio.as_of for item in daily_reports),
            tuple(
                sorted(
                    (holding for item in daily_reports for holding in item.portfolio.holdings),
                    key=lambda item: (item.instrument.mic, item.instrument.symbol),
                )
            ),
            tuple(
                sorted(
                    (watch for item in daily_reports for watch in item.portfolio.watch_items),
                    key=lambda item: (item.instrument.mic, item.instrument.symbol),
                )
            ),
            "weekly_reports",
        )
        decisions = tuple(
            sorted(
                (decision for item in daily_reports for decision in item.decisions),
                key=lambda item: (item.instrument.mic, item.instrument.symbol),
            )
        )
        candidate_decisions, screening_report_ids, screening_diagnostics = self._screening_inputs(
            as_of, maximum_age, portfolio
        )
        try:
            previous_report_id = self._reports.latest(MarketSession.WEEKLY).report_id
        except LookupError:
            previous_report_id = None
        report = self._report_factory(
            MarketSession.WEEKLY,
            as_of,
            portfolio,
            decisions,
            diagnostics=tuple(
                sorted(
                    {diagnostic for item in daily_reports for diagnostic in item.diagnostics}
                    | set(screening_diagnostics)
                )
            ),
            previous_report_id=previous_report_id,
            input_report_ids=tuple(sorted(item.report_id for item in daily_reports)),
            candidate_decisions=candidate_decisions,
            screening_report_ids=screening_report_ids,
        )
        return self._reports.put(report)

    def _screening_inputs(
        self,
        as_of: datetime,
        maximum_age: timedelta,
        portfolio: PortfolioSnapshot,
    ) -> tuple[
        tuple[InstrumentDecision, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        if self._screening is None:
            return (), (), ()
        reports: list[ScreeningReport] = []
        diagnostics: list[str] = []
        for market in ("jp", "us"):
            try:
                report = self._screening.latest_report(market)
            except (LookupError, OSError, TypeError, ValueError) as error:
                diagnostics.append(f"{market}:screening_report_unavailable:{type(error).__name__}")
                continue
            age = as_of.astimezone(UTC) - report.as_of.astimezone(UTC)
            if age < timedelta(0):
                diagnostics.append(f"{market}:screening_report_newer_than_weekly")
                continue
            if age > maximum_age:
                diagnostics.append(f"{market}:screening_report_stale")
                continue
            reports.append(report)
            diagnostics.extend(
                f"{market}:screening:{diagnostic}" for diagnostic in report.diagnostics
            )
        held = {(item.instrument.mic, item.instrument.symbol) for item in portfolio.holdings}
        values = [
            candidate.decision
            for report in reports
            for candidate in report.candidates
            if (candidate.decision.instrument.mic, candidate.decision.instrument.symbol) not in held
        ]
        identities = tuple(
            (decision.instrument.mic, decision.instrument.symbol) for decision in values
        )
        if len(identities) != len(set(identities)):
            raise ValueError("screening reports contain duplicate candidate instruments")
        candidates = tuple(sorted(values, key=candidate_order_key))
        return candidates, tuple(sorted(item.report_id for item in reports)), tuple(diagnostics)

    def _eligible(
        self,
        session: MarketSession,
        market: str,
        as_of: datetime,
        maximum_age: timedelta,
    ) -> DecisionReport:
        try:
            report = self._reports.latest(session)
        except LookupError:
            raise LookupError(
                f"eligible {market} close report does not exist; run 'marketsieve daily {market}'"
            ) from None
        age = as_of.astimezone(UTC) - report.as_of.astimezone(UTC)
        if age < timedelta(0):
            raise ValueError(f"{market} close report is newer than weekly as_of")
        if age > maximum_age:
            raise LookupError(f"{market} close report is stale; run 'marketsieve daily {market}'")
        return report
