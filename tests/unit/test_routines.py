from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from marketsieve import DecisionAction, Holding, PortfolioSnapshot, WatchItem
from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument
from marketsieve.synthetic.daily import JP_INSTRUMENT, US_INSTRUMENT, fixture_bars
from marketsieve_cli.adapters.reports import ReportStore, create_report
from marketsieve_cli.application.routines import DailyBriefService


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

    def fetch(
        self,
        profile_name: str,
        instrument_key: str,
        start: date,
        end: date,
        adjustment: str,
        kind: str = "daily_bars",
    ) -> dict[str, object]:
        del start, end, adjustment, kind
        self.fetches.append(f"{profile_name}:{instrument_key}")
        if instrument_key in self.failures:
            raise RuntimeError("provider secret must not enter diagnostics")
        return {}

    def bars(self, profile: str, instrument: str) -> tuple[DailyBar, ...]:
        del profile
        return self.values[instrument]


class Configuration:
    def daily_profile(self, market: str) -> tuple[str, int]:
        return f"{market}-profile", 400


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

    assert data.fetches == ["jp-profile:XTKS:7203"]
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
