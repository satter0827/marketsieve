"""On-demand yfinance research driven by explicit invocation inputs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Protocol

from marketsieve._snapshot_fields import INDEX_BENCHMARKS
from marketsieve.model import Adjustment, Instrument
from marketsieve_cli.contracts import ResearchBuildInputs, RuntimeSettings
from marketsieve_extension_api import (
    EquityBatchFetcher,
    EquityBatchInstrument,
    EquityBatchRequest,
    ImportedEquityBatch,
    SecurityResearchFetcher,
    SecurityResearchRequest,
)


class SettingsReader(Protocol):
    def runtime(self) -> RuntimeSettings: ...

    def effective_document(self) -> dict[str, Any]: ...

    def effective_hash(self) -> str: ...


class ResearchSourceRegistry(Protocol):
    def load_equity_batch_fetcher(self, name: str) -> EquityBatchFetcher: ...

    def load_security_research_fetcher(self, name: str) -> SecurityResearchFetcher: ...


class MarketReader(Protocol):
    def show(self, snapshot_id: str) -> dict[str, Any]: ...

    def row(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]: ...

    def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]: ...


class ResearchRepository(Protocol):
    def put(
        self,
        imported: Any,
        context: dict[str, Any],
        *,
        minimum_price_observations: int,
        runtime_settings: dict[str, Any],
        runtime_settings_hash: str,
        benchmarks: ImportedEquityBatch | None,
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
        settings: SettingsReader,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._registry = registry
        self._market = market
        self._repository = repository
        self._settings = settings
        self._today = today

    def build(self, inputs: ResearchBuildInputs) -> dict[str, Any]:
        resolved_snapshot_id = self._market.show(inputs.snapshot_id)["snapshot_id"]
        resolved_inputs = ResearchBuildInputs(
            resolved_snapshot_id,
            inputs.instrument_ids,
            inputs.evidence,
            inputs.history_days,
        )
        results: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for instrument_id in resolved_inputs.instrument_ids:
            try:
                results.append(self._build_one(resolved_inputs, instrument_id))
            except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
                failures.append({"instrument_id": instrument_id, "error": str(error)})
        return {
            "schema": "security-research-batch/v1",
            "snapshot_id": resolved_snapshot_id,
            "requested": list(inputs.instrument_ids),
            "research": results,
            "failures": failures,
            "requirements_met": bool(results)
            and all(item["price_coverage_gate_passed"] for item in results),
        }

    def _build_one(self, inputs: ResearchBuildInputs, instrument_id: str) -> dict[str, Any]:
        row = self._market.row(inputs.snapshot_id, instrument_id)
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
        runtime = self._settings.runtime()
        end = self._today()
        start = end - timedelta(days=inputs.history_days or 0)
        request = SecurityResearchRequest(
            "market-yfinance",
            instrument,
            row["provider_symbol"],
            start,
            end,
            Adjustment.ADJUSTED,
            runtime.yfinance.timeout_seconds,
            runtime.yfinance.max_retries,
            runtime.yfinance.retry_base_seconds,
            {"cache_dir": ".marketsieve/cache/yfinance"},
            inputs.evidence,
        )
        imported = self._registry.load_security_research_fetcher("yfinance").fetch_research(request)
        if imported.request != request or imported.source_name != "yfinance":
            raise ValueError("source result must preserve the exact yfinance research request")
        benchmarks = self._benchmarks(row, inputs, start, end, runtime)
        return self._repository.put(
            imported,
            context,
            minimum_price_observations=runtime.research_quality.minimum_price_observations,
            runtime_settings=self._settings.effective_document(),
            runtime_settings_hash=self._settings.effective_hash(),
            benchmarks=benchmarks,
        )

    def _benchmarks(
        self,
        row: dict[str, Any],
        inputs: ResearchBuildInputs,
        start: date,
        end: date,
        runtime: RuntimeSettings,
    ) -> ImportedEquityBatch | None:
        if "benchmarks" not in inputs.evidence:
            return None
        definitions = {
            "dow30": ("DJI", "XNYS", "USD", "America/New_York"),
            "nasdaq100": ("NDX", "XNAS", "USD", "America/New_York"),
            "nikkei225": ("N225", "XTKS", "JPY", "Asia/Tokyo"),
            "sp500": ("GSPC", "XNYS", "USD", "America/New_York"),
            "topix500": ("1308", "XTKS", "JPY", "Asia/Tokyo"),
        }
        instruments = tuple(
            sorted(
                (
                    EquityBatchInstrument(
                        Instrument.create(
                            symbol=definitions[index][0],
                            mic=definitions[index][1],
                            currency=definitions[index][2],
                            exchange_timezone=definitions[index][3],
                        ),
                        INDEX_BENCHMARKS[index],
                        (index,),
                        True,
                    )
                    for index in row["memberships"]
                ),
                key=lambda item: (item.instrument.mic, item.instrument.symbol),
            )
        )
        request = EquityBatchRequest(
            "market-yfinance",
            instruments,
            start,
            end,
            Adjustment.ADJUSTED,
            runtime.yfinance.batch_size,
            1,
            runtime.yfinance.timeout_seconds,
            runtime.yfinance.max_retries,
            runtime.yfinance.retry_base_seconds,
            {"cache_dir": ".marketsieve/cache/yfinance"},
            ("price",),
        )
        return self._registry.load_equity_batch_fetcher("yfinance").fetch(request)

    def show(
        self,
        research_id: str,
        *,
        snapshot_id: str | None = None,
        instrument_id: str | None = None,
    ) -> dict[str, Any]:
        if research_id != "latest":
            if snapshot_id is not None or instrument_id is not None:
                raise ValueError("filters are only valid with research ID 'latest'")
            return self._repository.show(research_id)
        if snapshot_id is None or instrument_id is None:
            raise ValueError("research show latest requires --snapshot and --security")
        resolved = snapshot_id
        if snapshot_id == "latest":
            resolved = self._market.research_context(snapshot_id, instrument_id)["snapshot_id"]
        return self._repository.latest(resolved, instrument_id)

    def list(
        self, *, snapshot_id: str | None = None, instrument_id: str | None = None
    ) -> dict[str, Any]:
        return self._repository.list(snapshot_id=snapshot_id, instrument_id=instrument_id)
