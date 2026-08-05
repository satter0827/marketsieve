from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from marketsieve import (
    DecisionAction,
    FinancialObservation,
    FinancialTrendReport,
    Holding,
    MarketSession,
    PortfolioSnapshot,
    WatchItem,
    analyze_financial_history,
)
from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument
from marketsieve.synthetic.daily import JP_INSTRUMENT, US_INSTRUMENT, fixture_bars
from marketsieve_cli.adapters.reports import ReportStore, create_report
from marketsieve_cli.application.routines import DailyBriefService, WeeklyBriefService


def _bars(instrument: Instrument = JP_INSTRUMENT, *, count: int = 252) -> tuple[DailyBar, ...]:
    closes = tuple(str(100 + index) for index in range(count))
    return fixture_bars(instrument, closes, dataset=f"routine-{instrument.symbol}-{count}")


@dataclass
class PortfolioReader:
    snapshot: PortfolioSnapshot

    def latest(self) -> tuple[str, PortfolioSnapshot, str]:
        return "portfolio-id", self.snapshot, "source-hash"


@dataclass
class DataService:
    values: dict[str, tuple[DailyBar, ...]]
    failures: set[str] = field(default_factory=set)
    fetches: list[str] = field(default_factory=list)
    trends: dict[str, FinancialTrendReport] = field(default_factory=dict)
    earnings: dict[str, date] = field(default_factory=dict)
    valuations: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    fundamentals: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)

    def fetch(
        self,
        profile_name: str,
        instrument_key: str,
        start: date,
        end: date,
        adjustment: str,
        kind: str = "daily_bars",
    ) -> dict[str, object]:
        del start, end, adjustment
        self.fetches.append(f"{profile_name}:{instrument_key}:{kind}")
        if kind == "daily_bars" and instrument_key in self.failures:
            raise RuntimeError("provider secret must not enter diagnostics")
        return {}

    def bars(self, profile: str, instrument: str) -> tuple[DailyBar, ...]:
        del profile
        return self.values[instrument]

    def financial_trend(
        self, profile: str, instrument: str, as_of: datetime
    ) -> FinancialTrendReport:
        del profile
        value = self.trends.get(instrument)
        return value if value is not None else analyze_financial_history((), as_of)

    def next_earnings_date(self, profile: str, instrument: str, as_of: datetime) -> date | None:
        del profile, as_of
        return self.earnings.get(instrument)

    def valuation_history(
        self, profile: str, instrument: str, as_of: datetime
    ) -> tuple[tuple[str, str], ...]:
        del profile, as_of
        return self.valuations.get(instrument, ())

    def fundamental_changes(
        self, profile: str, instrument: str, as_of: datetime
    ) -> tuple[tuple[str, str], ...]:
        del profile, as_of
        return self.fundamentals.get(instrument, ())


class Configuration:
    def daily_profile(self, market: str) -> tuple[str, int, int]:
        return f"{market}-profile", 400, 1500

    def weekly_max_age_days(self) -> int:
        return 7


def _portfolio(as_of: datetime) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        as_of,
        (Holding(JP_INSTRUMENT, Decimal("10"), Decimal("100"), "taxable"),),
        (WatchItem(US_INSTRUMENT),),
        "fixture",
    )


def test_daily_acquires_only_selected_market_and_stores_report(tmp_path: Path) -> None:
    bars = _bars()
    data = DataService({"XTKS:7203": bars})
    reports = ReportStore(tmp_path / "reports")
    service = DailyBriefService(
        PortfolioReader(_portfolio(bars[-1].available_at)),
        data,
        reports,
        Configuration(),
        create_report,
    )

    report = service.run("jp", as_of=bars[-1].available_at)

    assert data.fetches == [
        "jp-profile:XTKS:7203:daily_bars",
        "jp-profile:XTKS:7203:financials",
        "jp-profile:XTKS:7203:events",
    ]
    assert report.session.value == "jp_close"
    assert report.decisions[0].action is not DecisionAction.INDETERMINATE
    assert reports.latest(report.session) == report


def test_daily_partial_failure_is_indeterminate_without_losing_success(tmp_path: Path) -> None:
    jp_second = JP_INSTRUMENT.__class__.create(
        symbol="6758", mic="XTKS", currency="JPY", exchange_timezone="Asia/Tokyo"
    )
    bars = _bars()
    portfolio = PortfolioSnapshot(
        bars[-1].available_at,
        (Holding(JP_INSTRUMENT, Decimal("10"), Decimal("100"), "taxable"),),
        (WatchItem(jp_second),),
        "fixture",
    )
    data = DataService({"XTKS:7203": bars}, failures={"XTKS:6758"})
    reports = ReportStore(tmp_path / "reports")
    service = DailyBriefService(
        PortfolioReader(portfolio), data, reports, Configuration(), create_report
    )

    report = service.run("jp", as_of=bars[-1].available_at)

    assert [item.action for item in report.decisions] == [
        DecisionAction.INDETERMINATE,
        DecisionAction.REDUCE_REVIEW,
    ]
    assert report.diagnostics == ("XTKS:6758: price acquisition failed (RuntimeError)",)


def test_daily_passes_known_financial_trends_and_earnings_to_policy(tmp_path: Path) -> None:
    bars = _bars()
    available = bars[-1].available_at
    observations = []
    for year, revenue, eps in ((2024, "100", "10"), (2025, "120", "12")):
        for concept, value in (
            ("revenue", revenue),
            ("eps", eps),
            ("operating_cash_flow", "30"),
            ("capital_expenditure", "10"),
        ):
            observations.append(
                FinancialObservation(
                    concept,
                    Decimal(value),
                    1,
                    "annual",
                    date(year, 1, 1),
                    date(year, 12, 31),
                    "ifrs",
                    "consolidated",
                    "reported",
                    "JPY",
                    available.replace(year=year + 1, month=2, day=1),
                    f"{year}:{concept}",
                )
            )
    trend = analyze_financial_history(observations, available)
    earnings = available.astimezone(JP_INSTRUMENT.exchange_timezone).date() + timedelta(days=5)
    data = DataService(
        {"XTKS:7203": bars},
        trends={"XTKS:7203": trend},
        earnings={"XTKS:7203": earnings},
        valuations={
            "XTKS:7203": (
                ("trailing_per.current", "14"),
                ("trailing_per.history_count", "3"),
            )
        },
        fundamentals={"XTKS:7203": (("latest_filing_id", "filing-2025"),)},
    )
    service = DailyBriefService(
        PortfolioReader(_portfolio(available)),
        data,
        ReportStore(tmp_path / "reports"),
        Configuration(),
        create_report,
    )

    report = service.run("jp", as_of=available)
    decision = report.decisions[0]

    assert decision.revenue_growth == Decimal("0.2")
    assert decision.eps_growth == Decimal("0.2")
    assert decision.free_cash_flow == Decimal("20")
    assert decision.next_earnings_date == earnings
    assert dict(decision.valuation)["trailing_per.current"] == "14"
    assert dict(decision.fundamentals)["latest_filing_id"] == "filing-2025"
    assert any(trend.evidence_id in item.evidence_ids for item in decision.evidence)


def test_all_indeterminate_report_is_retained_without_latest_reference(tmp_path: Path) -> None:
    bars = _bars(count=1)
    data = DataService({"XTKS:7203": bars})
    reports = ReportStore(tmp_path / "reports")
    service = DailyBriefService(
        PortfolioReader(_portfolio(bars[-1].available_at)),
        data,
        reports,
        Configuration(),
        create_report,
    )

    with pytest.raises(RuntimeError, match="latest report was not updated"):
        service.run("jp", as_of=bars[-1].available_at)

    assert len(reports.list()) == 1
    with pytest.raises(LookupError):
        reports.latest(reports.list()[0].session)


def test_daily_rejects_an_as_of_before_the_portfolio(tmp_path: Path) -> None:
    bars = _bars()
    service = DailyBriefService(
        PortfolioReader(_portfolio(bars[-1].available_at)),
        DataService({"XTKS:7203": bars}),
        ReportStore(tmp_path / "reports"),
        Configuration(),
        create_report,
    )

    with pytest.raises(ValueError, match="must not predate"):
        service.run("jp", as_of=bars[-2].available_at)

    with pytest.raises(ValueError, match="market must be"):
        service.run("eu", as_of=bars[-1].available_at)
    with pytest.raises(ValueError, match="UTC offset"):
        service.run("jp", as_of=bars[-1].available_at.replace(tzinfo=None))
    with pytest.raises(ValueError, match="no us instruments"):
        DailyBriefService(
            PortfolioReader(
                PortfolioSnapshot(
                    bars[-1].available_at,
                    (Holding(JP_INSTRUMENT, Decimal("1"), Decimal("1"), "taxable"),),
                    (),
                    "fixture",
                )
            ),
            DataService({"XTKS:7203": bars}),
            ReportStore(tmp_path / "empty-market"),
            Configuration(),
            create_report,
        ).run("us", as_of=bars[-1].available_at)


def _daily_inputs(tmp_path: Path) -> tuple[ReportStore, datetime]:
    jp_bars = _bars(JP_INSTRUMENT)
    us_bars = _bars(US_INSTRUMENT)
    as_of = max(jp_bars[-1].available_at, us_bars[-1].available_at)
    reports = ReportStore(tmp_path / "reports")
    data = DataService({"XTKS:7203": jp_bars, "XNAS:MSFT": us_bars})
    daily = DailyBriefService(
        PortfolioReader(_portfolio(min(jp_bars[-1].available_at, us_bars[-1].available_at))),
        data,
        reports,
        Configuration(),
        create_report,
    )
    daily.run("jp", as_of=as_of)
    daily.run("us", as_of=as_of)
    return reports, as_of


def test_weekly_combines_exact_daily_inputs_without_acquisition(tmp_path: Path) -> None:
    reports, as_of = _daily_inputs(tmp_path)
    jp = reports.latest(MarketSession.JP_CLOSE)
    us = reports.latest(MarketSession.US_CLOSE)

    weekly = WeeklyBriefService(reports, Configuration(), create_report).run(
        as_of=as_of + timedelta(days=1)
    )

    assert weekly.session is MarketSession.WEEKLY
    assert weekly.input_report_ids == tuple(sorted((jp.report_id, us.report_id)))
    assert [item.instrument.currency for item in weekly.decisions] == ["USD", "JPY"]
    assert reports.latest(MarketSession.WEEKLY) == weekly


def test_weekly_rejects_stale_or_missing_inputs_with_recovery_command(tmp_path: Path) -> None:
    reports, as_of = _daily_inputs(tmp_path)
    service = WeeklyBriefService(reports, Configuration(), create_report)

    with pytest.raises(LookupError, match="marketsieve daily jp"):
        service.run(as_of=as_of + timedelta(days=8))

    empty = WeeklyBriefService(ReportStore(tmp_path / "empty"), Configuration(), create_report)
    with pytest.raises(LookupError, match="marketsieve daily jp"):
        empty.run(as_of=as_of)

    with pytest.raises(ValueError, match="newer than weekly"):
        service.run(as_of=as_of - timedelta(seconds=1))
    with pytest.raises(ValueError, match="UTC offset"):
        service.run(as_of=as_of.replace(tzinfo=None))
