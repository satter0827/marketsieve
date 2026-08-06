"""Explicit universe acquisition and deterministic offline screening."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from marketsieve import (
    AnalysisContext,
    BalancedCandidateScreen,
    BalancedMediumTermPolicy,
    InstrumentUniverse,
    PersonalInvestmentContext,
    PortfolioSnapshot,
    ScreeningReport,
)
from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument
from marketsieve.portfolio import Holding
from marketsieve_cli.contracts import ScreeningConfiguration
from marketsieve_extension_api import (
    ImportedInstrumentUniverse,
    InstrumentUniverseFetcher,
    InstrumentUniverseImporter,
    UniverseRequest,
)


class ConfigurationReader(Protocol):
    def screening_configuration(self, market: str) -> ScreeningConfiguration: ...

    def screening_refresh_configuration(self, market: str) -> ScreeningConfiguration: ...


class UniversePluginRegistry(Protocol):
    def load_universe_importer(self, name: str) -> InstrumentUniverseImporter: ...

    def load_universe_fetcher(self, name: str) -> InstrumentUniverseFetcher: ...


class SnapshotReader(Protocol):
    def resolve(self, profile: str, instrument: str, kind: str = "daily_bars") -> Any: ...

    def daily_bars(self, object_id: str) -> tuple[DailyBar, ...]: ...


class PortfolioReader(Protocol):
    def latest_snapshot(self) -> PortfolioSnapshot: ...


class DailyDataService(Protocol):
    def fetch(
        self,
        profile_name: str,
        instrument_key: str,
        start: Any,
        end: Any,
        adjustment: str,
        kind: str = "daily_bars",
    ) -> dict[str, object]: ...


class ScreeningRepository(Protocol):
    def put_universe(self, imported: ImportedInstrumentUniverse) -> InstrumentUniverse: ...

    def latest_universe(self, market: str) -> InstrumentUniverse: ...

    def put_report(self, report: ScreeningReport, *, market: str) -> ScreeningReport: ...

    def resolve_report(self, report_id: str, market: str | None = None) -> ScreeningReport: ...


class ScreeningService:
    """Keep network acquisition separate from reproducible local screening."""

    def __init__(
        self,
        registry: UniversePluginRegistry,
        snapshots: SnapshotReader,
        portfolios: PortfolioReader,
        store: ScreeningRepository,
        configuration: ConfigurationReader,
        data: DailyDataService | None = None,
    ) -> None:
        self._registry = registry
        self._snapshots = snapshots
        self._portfolios = portfolios
        self._store = store
        self._configuration = configuration
        self._data = data

    def update(self, market: str) -> InstrumentUniverse:
        screening = self._configuration.screening_configuration(market)
        settings = dict(screening.settings)
        path_value = settings.pop("path", None)
        request = UniverseRequest(
            screening.source_profile,
            market,
            screening.acquisition_limit,
            settings,
            screening.eligible_mics,
        )
        imported: ImportedInstrumentUniverse
        if screening.operation == "import":
            if path_value is None:
                raise ValueError("universe import requires settings.path")
            imported = self._registry.load_universe_importer(screening.plugin).import_universe(
                Path(path_value), request
            )
        elif screening.operation == "fetch":
            if path_value is not None:
                raise ValueError("universe fetch does not accept settings.path")
            imported = self._registry.load_universe_fetcher(screening.plugin).fetch_universe(
                request
            )
        else:
            raise ValueError("universe operation must be import or fetch")
        return self._store.put_universe(imported)

    def refresh(self, market: str) -> ScreeningReport:
        """Acquire a bounded universe and bounded price set, then screen it offline."""

        if self._data is None:
            raise RuntimeError("screen refresh requires a configured daily data service")
        screening = self._configuration.screening_refresh_configuration(market)
        universe = self.update(market)
        acquisition_as_of = datetime.now().astimezone()
        diagnostics: list[str] = []
        compatible = self._compatible_instruments(universe, screening, diagnostics)
        selected = compatible[: screening.fetch_limit]
        if len(compatible) > len(selected):
            diagnostics.append(f"refresh_fetch_limit_reached:{screening.fetch_limit}")
        for instrument in selected:
            key = f"{instrument.mic}:{instrument.symbol}"
            end = acquisition_as_of.astimezone(instrument.exchange_timezone).date()
            try:
                self._data.fetch(
                    screening.source_profile,
                    key,
                    end - timedelta(days=screening.lookback_days),
                    end,
                    "raw",
                )
            except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
                diagnostics.append(f"{key}:refresh_{self._failure_code(error)}")
        report_as_of = datetime.now().astimezone()
        return self.run(market, as_of=report_as_of, extra_diagnostics=tuple(diagnostics))

    def run(
        self, market: str, *, as_of: datetime, extra_diagnostics: tuple[str, ...] = ()
    ) -> ScreeningReport:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("screening as_of must include a UTC offset")
        screening = self._configuration.screening_configuration(market)
        universe = self._store.latest_universe(market)
        if universe.as_of.astimezone(UTC) > as_of.astimezone(UTC):
            raise ValueError("screening as_of must not predate the universe")
        holdings = self._holdings(as_of)
        diagnostics = [*universe.diagnostics, *extra_diagnostics]
        compatible = self._compatible_instruments(universe, screening, diagnostics)
        policy = BalancedMediumTermPolicy()
        decisions = []
        for instrument in compatible[: screening.processing_limit]:
            key = (instrument.mic, instrument.symbol)
            evidence_ids: tuple[str, ...]
            try:
                stored = self._snapshots.resolve(
                    universe.source_profile, f"{instrument.mic}:{instrument.symbol}"
                )
                object_id = stored.object_id
                bars = tuple(
                    bar
                    for bar in self._snapshots.daily_bars(object_id)
                    if bar.available_at.astimezone(UTC) <= as_of.astimezone(UTC)
                )
                evidence_ids = (object_id,)
            except (AttributeError, LookupError, OSError, TypeError, ValueError) as error:
                diagnostics.append(
                    f"{instrument.mic}:{instrument.symbol}:daily_bars_unavailable:{type(error).__name__}"
                )
                bars = ()
                evidence_ids = ()
            decisions.append(
                policy.evaluate(
                    AnalysisContext(
                        instrument=instrument,
                        as_of=as_of,
                        bars=bars,
                        personal=PersonalInvestmentContext(),
                        holding=holdings.get(key),
                        input_evidence_ids=evidence_ids,
                    )
                )
            )
        report = BalancedCandidateScreen().screen(
            universe,
            tuple(decisions),
            as_of=as_of,
            eligible_instruments=compatible,
            processing_limit=screening.processing_limit,
            display_limit=screening.display_limit,
            diagnostics=tuple(sorted(set(diagnostics))),
        )
        return self._store.put_report(report, market=market)

    @staticmethod
    def _compatible_instruments(
        universe: InstrumentUniverse,
        screening: ScreeningConfiguration,
        diagnostics: list[str],
    ) -> tuple[Instrument, ...]:
        compatible = tuple(
            instrument
            for instrument in universe.instruments
            if instrument.mic in screening.eligible_mics
        )
        excluded = sorted(
            {instrument.mic for instrument in universe.instruments} - set(screening.eligible_mics)
        )
        diagnostics.extend(f"incompatible_mic_excluded:{mic}" for mic in excluded)
        return compatible

    @staticmethod
    def _failure_code(error: Exception) -> str:
        text = str(error).lower()
        if "rate" in text or "limit" in text:
            return "rate_limit"
        if "credential" in text or "api key" in text or "authentication" in text:
            return "credential"
        if "range" in text or "history" in text:
            return "insufficient_data"
        return f"failed_{type(error).__name__}"

    def show(self, report_id: str, *, market: str | None = None) -> ScreeningReport:
        return self._store.resolve_report(report_id, market)

    def _holdings(self, as_of: datetime) -> dict[tuple[str, str], Holding]:
        try:
            portfolio = self._portfolios.latest_snapshot()
        except LookupError:
            return {}
        if portfolio.as_of.astimezone(UTC) > as_of.astimezone(UTC):
            raise ValueError("screening as_of must not predate the portfolio snapshot")
        return {
            (holding.instrument.mic, holding.instrument.symbol): holding
            for holding in portfolio.holdings
        }
