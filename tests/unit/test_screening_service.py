from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
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


class MixedMicImporter(Importer):
    def import_universe(self, path: Path, request: UniverseRequest) -> ImportedInstrumentUniverse:
        imported = super().import_universe(path, request)
        return ImportedInstrumentUniverse(
            request,
            imported.source_name,
            imported.source_version,
            imported.dataset,
            datetime.now().astimezone(),
            (_instrument("BBB"), _instrument("CCC")),
            imported.source_hash,
            2,
            False,
            ("ineligible_mics_excluded:1",),
        )


class MixedMicRegistry(Registry):
    def load_universe_importer(self, name: str) -> MixedMicImporter:
        assert name == "csv"
        return MixedMicImporter()


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

    def latest_snapshot(self) -> PortfolioSnapshot:
        if self.snapshot is None:
            raise LookupError("no portfolio")
        return self.snapshot


class Data:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, str, date, date]] = []
        self.completed_at: datetime | None = None

    def fetch(
        self,
        profile_name: str,
        instrument_key: str,
        start: date,
        end: date,
        adjustment: str,
        kind: str = "daily_bars",
    ) -> dict[str, object]:
        assert adjustment == "raw" and kind == "daily_bars"
        self.calls.append((profile_name, instrument_key, start, end))
        self.completed_at = datetime.now().astimezone()
        if self.failure is not None:
            raise self.failure
        return {"status": "fetched"}


def _configuration(tmp_path: Path) -> Configuration:
    path = tmp_path / "marketsieve.toml"
    path.write_text(
        "[source_profiles.offline-us]\n"
        'currency = "USD"\n'
        'timezone = "America/New_York"\n'
        "[source_profiles.offline-us.daily_bars]\n"
        'plugin = "csv"\n'
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


def test_refresh_fetches_only_the_configured_limit_and_records_rate_limit(
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    assert configuration.path is not None
    configuration.path.write_text(
        configuration.path.read_text(encoding="utf-8") + "fetch_limit = 1\nlookback_days = 90\n",
        encoding="utf-8",
    )
    data = Data(RuntimeError("provider rate limit"))
    service = ScreeningService(
        Registry(),
        Snapshots(),
        Portfolios(),
        ScreeningStore(tmp_path / "refresh-state"),
        Configuration(configuration.path),
        data,
    )

    report = service.refresh("us")

    assert len(data.calls) == 1
    assert data.calls[0][0:2] == ("offline-us", "XNAS:AAA")
    assert (data.calls[0][3] - data.calls[0][2]).days == 90
    assert "refresh_fetch_limit_reached:1" in report.diagnostics
    assert "XNAS:AAA:refresh_rate_limit" in report.diagnostics


def test_refresh_sets_default_time_after_acquisition_and_excludes_incompatible_mics(
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    assert configuration.path is not None
    configuration.path.write_text(
        configuration.path.read_text(encoding="utf-8") + "fetch_limit = 1\nprocessing_limit = 1\n",
        encoding="utf-8",
    )
    data = Data()
    service = ScreeningService(
        MixedMicRegistry(),
        Snapshots(),
        Portfolios(),
        ScreeningStore(tmp_path / "mixed-state"),
        Configuration(configuration.path),
        data,
    )

    report = service.refresh("us")

    assert [call[1] for call in data.calls] == ["XNAS:BBB"]
    assert data.completed_at is not None and report.as_of >= data.completed_at
    assert report.processed_count == 1
    assert "processing_limit_reached:1" in report.diagnostics
    assert "ineligible_mics_excluded:1" in report.diagnostics
