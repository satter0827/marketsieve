"""Installed source metadata and explicit plugin loading."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata

from marketsieve_extension_api import DailyBarBundleImporter, DailyBarFetcher

ENTRY_POINT_GROUP = "marketsieve.sources"
FETCHER_ENTRY_POINT_GROUP = "marketsieve.sources.daily_bars.fetchers"


def source_entry_points() -> metadata.EntryPoints:
    """Return source entry points without loading their referenced objects."""

    return metadata.entry_points(group=ENTRY_POINT_GROUP)


def fetcher_entry_points() -> metadata.EntryPoints:
    """Return fetch-capability markers without loading plugin code."""

    return metadata.entry_points(group=FETCHER_ENTRY_POINT_GROUP)


@dataclass(frozen=True, slots=True)
class InstalledSource:
    """Package metadata available without importing plugin code."""

    name: str
    distribution: str
    version: str
    value: str


class SourcePluginRegistry:
    """Inspect metadata first and load only one explicitly selected plugin."""

    def installed(self) -> tuple[InstalledSource, ...]:
        entries = source_entry_points()
        return tuple(
            sorted(
                (
                    InstalledSource(
                        entry.name,
                        entry.dist.name if entry.dist is not None else "unknown",
                        entry.dist.version if entry.dist is not None else "unknown",
                        entry.value,
                    )
                    for entry in entries
                ),
                key=lambda item: (item.name, item.distribution),
            )
        )

    def load_daily_bars(self, name: str) -> DailyBarBundleImporter:
        matches = tuple(entry for entry in source_entry_points() if entry.name == name)
        if len(matches) != 1:
            raise ValueError(
                f"source plugin {name!r} must resolve to exactly one installed entry point"
            )
        candidate = matches[0].load()()
        if not isinstance(candidate, DailyBarBundleImporter):
            raise TypeError(f"source plugin {name!r} does not implement daily-bar import")
        return candidate

    def can_fetch(self, name: str) -> bool:
        """Report a plugin's declared fetch capability without loading it."""

        return any(entry.name == name for entry in fetcher_entry_points())

    def load_fetcher(self, name: str) -> DailyBarFetcher:
        """Load only the explicitly selected network source."""

        matches = tuple(entry for entry in source_entry_points() if entry.name == name)
        if len(matches) != 1:
            raise ValueError(
                f"source plugin {name!r} must resolve to exactly one installed entry point"
            )
        candidate = matches[0].load()()
        if not isinstance(candidate, DailyBarFetcher):
            raise TypeError(f"source plugin {name!r} does not implement daily-bar fetch")
        return candidate
