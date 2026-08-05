"""Installed source metadata and explicit plugin loading."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata

from marketsieve_extension_api import (
    DailyBarBundleImporter,
    DailyBarFetcher,
    EconomicSeriesFetcher,
    EventFetcher,
    FinancialFetcher,
)

ENTRY_POINT_GROUP = "marketsieve.sources"
IMPORTER_ENTRY_POINT_GROUP = "marketsieve.sources.daily_bars.importers"
FETCHER_ENTRY_POINT_GROUP = "marketsieve.sources.daily_bars.fetchers"
FINANCIAL_ENTRY_POINT_GROUP = "marketsieve.sources.financials.fetchers"
EVENT_ENTRY_POINT_GROUP = "marketsieve.sources.events.fetchers"
ECONOMIC_SERIES_ENTRY_POINT_GROUP = "marketsieve.sources.economic_series.fetchers"


def source_entry_points() -> metadata.EntryPoints:
    """Return source entry points without loading their referenced objects."""

    return metadata.entry_points(group=ENTRY_POINT_GROUP)


def fetcher_entry_points() -> metadata.EntryPoints:
    """Return fetch-capability markers without loading plugin code."""

    return metadata.entry_points(group=FETCHER_ENTRY_POINT_GROUP)


def importer_entry_points() -> metadata.EntryPoints:
    return metadata.entry_points(group=IMPORTER_ENTRY_POINT_GROUP)


def financial_entry_points() -> metadata.EntryPoints:
    return metadata.entry_points(group=FINANCIAL_ENTRY_POINT_GROUP)


def event_entry_points() -> metadata.EntryPoints:
    return metadata.entry_points(group=EVENT_ENTRY_POINT_GROUP)


def economic_series_entry_points() -> metadata.EntryPoints:
    return metadata.entry_points(group=ECONOMIC_SERIES_ENTRY_POINT_GROUP)


@dataclass(frozen=True, slots=True)
class InstalledSource:
    """Package metadata available without importing plugin code."""

    name: str
    distribution: str
    version: str
    value: str
    data_kinds: tuple[str, ...]


class SourcePluginRegistry:
    """Inspect metadata first and load only one explicitly selected plugin."""

    def installed(self) -> tuple[InstalledSource, ...]:
        entries = source_entry_points()
        importers = {entry.name for entry in importer_entry_points()}
        fetchers = {entry.name for entry in fetcher_entry_points()}
        financials = {entry.name for entry in financial_entry_points()}
        events = {entry.name for entry in event_entry_points()}
        economic_series = {entry.name for entry in economic_series_entry_points()}
        return tuple(
            sorted(
                (
                    InstalledSource(
                        entry.name,
                        entry.dist.name if entry.dist is not None else "unknown",
                        entry.dist.version if entry.dist is not None else "unknown",
                        entry.value,
                        tuple(
                            kind
                            for kind, names in (
                                ("daily_bars", importers | fetchers),
                                ("financials", financials),
                                ("events", events),
                                ("economic_series", economic_series),
                            )
                            if entry.name in names
                        ),
                    )
                    for entry in entries
                ),
                key=lambda item: (item.name, item.distribution),
            )
        )

    def load_daily_bars(self, name: str) -> DailyBarBundleImporter:
        candidate = self._load(name)
        if not isinstance(candidate, DailyBarBundleImporter):
            raise TypeError(f"source plugin {name!r} does not implement daily-bar import")
        return candidate

    def can_fetch(self, name: str) -> bool:
        """Report a plugin's declared fetch capability without loading it."""

        return any(entry.name == name for entry in fetcher_entry_points())

    def load_fetcher(self, name: str) -> DailyBarFetcher:
        """Load only the explicitly selected network source."""

        candidate = self._load(name)
        if not isinstance(candidate, DailyBarFetcher):
            raise TypeError(f"source plugin {name!r} does not implement daily-bar fetch")
        return candidate

    def load_financial_fetcher(self, name: str) -> FinancialFetcher:
        candidate = self._load(name)
        if not isinstance(candidate, FinancialFetcher):
            raise TypeError(f"source plugin {name!r} does not implement financial fetch")
        return candidate

    def load_event_fetcher(self, name: str) -> EventFetcher:
        candidate = self._load(name)
        if not isinstance(candidate, EventFetcher):
            raise TypeError(f"source plugin {name!r} does not implement event fetch")
        return candidate

    def load_economic_series_fetcher(self, name: str) -> EconomicSeriesFetcher:
        candidate = self._load(name)
        if not isinstance(candidate, EconomicSeriesFetcher):
            raise TypeError(f"source plugin {name!r} does not implement economic-series fetch")
        return candidate

    def _load(self, name: str) -> object:
        matches = tuple(entry for entry in source_entry_points() if entry.name == name)
        if len(matches) != 1:
            raise ValueError(
                f"source plugin {name!r} must resolve to exactly one installed entry point"
            )
        return matches[0].load()()
