from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import NoReturn

from marketsieve import Holding, PortfolioSnapshot
from marketsieve.domain import Instrument
from marketsieve.synthetic.daily import fixture_bars
from marketsieve_cli.adapters.config import Configuration
from marketsieve_cli.adapters.screening import ScreeningStore
from marketsieve_cli.application.screening import ScreeningService
from marketsieve_extension_api import ImportedInstrumentUniverse, UniverseRequest


def _instrument(symbol: str) -> Instrument:
    return Instrument.create(
        symbol=symbol,
        mic="XNAS",
        currency="USD",
        exchange_timezone="America/New_York",
    )


class Importer:
    def import_universe(self, path: Path, request: UniverseRequest) -> ImportedInstrumentUniverse:
        assert path == Path("universe.csv")
        return ImportedInstrumentUniverse(
            request,
            "csv",
            "1.0.0",
            "instrument-universe",
            datetime(2026, 8, 1, tzinfo=UTC),
            (_instrument("AAA"), _instrument("BBB")),
            "a" * 64,
            2,
            False,
        )


class Registry:
    def load_universe_importer(self, name: str) -> Importer:
        assert name == "csv"
        return Importer()

    def load_universe_fetcher(self, name: str) -> NoReturn:
        raise AssertionError(f"offline import unexpectedly fetched {name}")


@dataclass(frozen=True)
class Stored:
    object_id: str


class Snapshots:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.missing = missing or set()

    def resolve(self, profile: str, instrument: str, kind: str = "daily_bars") -> Stored:
        assert profile == "offline-us"
        assert kind == "daily_bars"
        if instrument in self.missing:
            raise LookupError("missing")
        return Stored("b" * 64 + instrument)

    def daily_bars(self, object_id: str):  # type: ignore[no-untyped-def]
        symbol = object_id.removeprefix("b" * 64).partition(":")[2]
        return fixture_bars(
            _instrument(symbol),
            tuple(str(100 + index) for index in range(252)),
            dataset=f"screen-{symbol}",
        )


class Portfolios:
    def __init__(self, snapshot: PortfolioSnapshot | None = None) -> None:
        self.snapshot = snapshot

    def latest(self) -> tuple[str, PortfolioSnapshot, str]:
        if self.snapshot is None:
            raise LookupError("no portfolio")
        return "portfolio", self.snapshot, "source"


def _configuration(tmp_path: Path) -> Configuration:
    path = tmp_path / "marketsieve.toml"
    path.write_text(
        "[source_profiles.offline-us]\n"
        'currency = "USD"\n'
        'timezone = "America/New_York"\n'
        "[source_profiles.offline-us.instrument_universe]\n"
        'plugin = "csv"\n'
        'operation = "import"\n'
        "[source_profiles.offline-us.instrument_universe.settings]\n"
        'path = "universe.csv"\n'
        "[screening.us]\n"
        'source_profile = "offline-us"\n',
        encoding="utf-8",
    )
    return Configuration(path)


def test_update_then_run_is_offline_and_preserves_partial_data_diagnostics(
    tmp_path: Path,
) -> None:
    service = ScreeningService(
        Registry(),
        Snapshots({"XNAS:BBB"}),
        Portfolios(),
        ScreeningStore(tmp_path / "state"),
        _configuration(tmp_path),
    )

    universe = service.update("us")
    report = service.run("us", as_of=datetime(2026, 8, 2, tzinfo=UTC))

    assert universe.market == "us"
    assert report.processed_count == 2
    assert any("XNAS:BBB:daily_bars_unavailable" in item for item in report.diagnostics)
    assert service.show("latest", market="us") == report


def test_held_instruments_never_enter_candidate_results(tmp_path: Path) -> None:
    held = _instrument("AAA")
    portfolio = PortfolioSnapshot(
        datetime(2026, 8, 1, tzinfo=UTC),
        (Holding(held, Decimal("1"), Decimal("100"), "taxable"),),
        (),
        "test",
    )
    service = ScreeningService(
        Registry(),
        Snapshots(),
        Portfolios(portfolio),
        ScreeningStore(tmp_path / "state"),
        _configuration(tmp_path),
    )

    service.update("us")
    report = service.run("us", as_of=datetime(2026, 8, 2, tzinfo=UTC))

    assert all(item.decision.instrument.symbol != "AAA" for item in report.candidates)
