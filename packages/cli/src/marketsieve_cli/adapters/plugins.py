"""Discovery for the two implemented provider contracts."""

from __future__ import annotations

from importlib import metadata

from marketsieve_extension_api import EquityBatchFetcher, SecurityResearchFetcher

EQUITY_BATCH_GROUP = "marketsieve.sources.equity_batches.fetchers"
SECURITY_RESEARCH_GROUP = "marketsieve.sources.security_research.fetchers"


class SourcePluginRegistry:
    """Load provider implementations only for an explicit capability."""

    @staticmethod
    def _load(group: str, name: str) -> object:
        matches = [value for value in metadata.entry_points(group=group) if value.name == name]
        if len(matches) != 1:
            raise LookupError(f"provider {name!r} is not installed for {group}")
        factory = matches[0].load()
        return factory()

    def load_equity_batch_fetcher(self, name: str) -> EquityBatchFetcher:
        candidate = self._load(EQUITY_BATCH_GROUP, name)
        if not isinstance(candidate, EquityBatchFetcher):
            raise TypeError("provider does not implement EquityBatchFetcher")
        return candidate

    def load_security_research_fetcher(self, name: str) -> SecurityResearchFetcher:
        candidate = self._load(SECURITY_RESEARCH_GROUP, name)
        if not isinstance(candidate, SecurityResearchFetcher):
            raise TypeError("provider does not implement SecurityResearchFetcher")
        return candidate
