"""On-demand security research orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Protocol

from marketsieve.data.daily import Adjustment
from marketsieve.domain import Instrument
from marketsieve_cli.contracts import ResearchConfiguration
from marketsieve_extension_api import SecurityResearchFetcher, SecurityResearchRequest


class ResearchConfigurationReader(Protocol):
    def research_configuration(self) -> ResearchConfiguration: ...


class ResearchSourceRegistry(Protocol):
    def load_equity_batch_fetcher(self, name: str) -> object: ...


class MarketReader(Protocol):
    def row(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]: ...

    def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]: ...


class ResearchRepository(Protocol):
    def put(
        self,
        imported: Any,
        context: dict[str, Any],
        *,
        minimum_price_observations: int,
    ) -> dict[str, Any]: ...

    def show(self, research_id: str) -> dict[str, Any]: ...

    def latest(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]: ...

    def list(
        self, *, snapshot_id: str | None = None, instrument_id: str | None = None
    ) -> dict[str, Any]: ...


class ResearchService:
    def __init__(
        self,
        registry: ResearchSourceRegistry,
        market: MarketReader,
        repository: ResearchRepository,
        configuration: ResearchConfigurationReader,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._registry = registry
        self._market = market
        self._repository = repository
        self._configuration = configuration
        self._today = today

    def build(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        row = self._market.row(snapshot_id, instrument_id)
        resolved_snapshot_id = row["snapshot_id"]
        context = self._market.research_context(resolved_snapshot_id, instrument_id)
        if context["snapshot_id"] != resolved_snapshot_id:
            raise ValueError("research context must preserve the resolved Market Snapshot")
        instrument_document = row["instrument"]
        instrument = Instrument.create(
            symbol=instrument_document["symbol"],
            mic=instrument_document["mic"],
            currency=instrument_document["currency"],
            exchange_timezone=instrument_document["exchange_timezone"],
        )
        configuration = self._configuration.research_configuration()
        end = self._today()
        request = SecurityResearchRequest(
            "market-yfinance",
            instrument,
            row["provider_symbol"],
            end - timedelta(days=configuration.history_days),
            end,
            Adjustment.ADJUSTED,
            configuration.timeout_seconds,
            configuration.max_retries,
            configuration.retry_base_seconds,
            {"cache_dir": ".marketsieve/cache/yfinance"},
        )
        candidate = self._registry.load_equity_batch_fetcher("yfinance")
        if not isinstance(candidate, SecurityResearchFetcher):
            raise TypeError("yfinance source does not implement security research")
        imported = candidate.fetch_research(request)
        if imported.request != request:
            raise ValueError("source fetch result must preserve the exact research request")
        if imported.source_name != "yfinance":
            raise ValueError("security research source must be yfinance")
        document = self._repository.put(
            imported,
            context,
            minimum_price_observations=configuration.minimum_price_observations,
        )
        return document

    def show(
        self,
        research_id: str,
        *,
        snapshot_id: str = "latest",
        instrument_id: str | None = None,
    ) -> dict[str, Any]:
        if research_id != "latest":
            if instrument_id is not None:
                raise ValueError("--security is only valid with research ID 'latest'")
            return self._repository.show(research_id)
        if instrument_id is None:
            raise ValueError("research show latest requires --security MIC:SYMBOL")
        resolved_snapshot_id = snapshot_id
        if snapshot_id == "latest":
            resolved_snapshot_id = self._market.research_context(snapshot_id, instrument_id)[
                "snapshot_id"
            ]
        return self._repository.latest(resolved_snapshot_id, instrument_id)

    def list(
        self, *, snapshot_id: str | None = None, instrument_id: str | None = None
    ) -> dict[str, Any]:
        resolved = None
        if snapshot_id is not None:
            if snapshot_id == "latest":
                if instrument_id is None:
                    raise ValueError("research list --snapshot latest also requires --security")
                resolved = self._market.research_context(snapshot_id, instrument_id)["snapshot_id"]
            else:
                resolved = snapshot_id
        return self._repository.list(snapshot_id=resolved, instrument_id=instrument_id)
