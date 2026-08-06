"""Explicit loading for installed portfolio importer plugins."""

from __future__ import annotations

from importlib import metadata

from marketsieve_extension_api import PortfolioSnapshotImporter

ENTRY_POINT_GROUP = "marketsieve.portfolios.importers"


def portfolio_importer_entry_points() -> metadata.EntryPoints:
    """Return portfolio importer entry points without loading plugin code."""

    return metadata.entry_points(group=ENTRY_POINT_GROUP)


class PortfolioPluginRegistry:
    """Load exactly one explicitly selected portfolio importer."""

    def load(self, name: str) -> PortfolioSnapshotImporter:
        matches = tuple(entry for entry in portfolio_importer_entry_points() if entry.name == name)
        if len(matches) != 1:
            raise ValueError(
                f"portfolio importer {name!r} must resolve to exactly one installed entry point"
            )
        candidate = matches[0].load()()
        if not isinstance(candidate, PortfolioSnapshotImporter):
            raise TypeError(
                f"portfolio importer {name!r} does not implement PortfolioSnapshotImporter"
            )
        return candidate
