"""On-demand yfinance research driven by explicit invocation inputs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Protocol

from marketsieve.model import Adjustment, Instrument
from marketsieve_cli.contracts import ResearchBuildInputs, RuntimeSettings
from marketsieve_cli.market_catalog import INDEX_RUNTIME_CATALOG
from marketsieve_extension_api import (
    AcquisitionProgress,
    AcquisitionProgressState,
    EquityBatchFetcher,
    EquityBatchInstrument,
    EquityBatchRequest,
    ImportedEquityBatch,
    ProgressSink,
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

    def build(
        self,
        inputs: ResearchBuildInputs,
        *,
        progress: ProgressSink | None = None,
        published: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        resolved_snapshot_id = self._market.show(inputs.snapshot_id)["snapshot_id"]
        resolved_inputs = ResearchBuildInputs(
            resolved_snapshot_id,
            inputs.instrument_ids,
            inputs.evidence,
            inputs.history_days,
        )
        results: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        phase_failures: dict[str, int] = {}
        total_instruments = len(resolved_inputs.instrument_ids)

        def aggregate(index: int) -> ProgressSink | None:
            if progress is None:
                return None

            def emit(value: AcquisitionProgress) -> None:
                finished = value.state is AcquisitionProgressState.COMPLETED
                if finished and value.failure_count:
                    phase_failures[value.phase] = phase_failures.get(value.phase, 0) + 1
                completed = index + int(finished)
                if value.state is AcquisitionProgressState.RETRYING:
                    state = AcquisitionProgressState.RETRYING
                elif finished and completed == total_instruments:
                    state = AcquisitionProgressState.COMPLETED
                elif index == 0 and value.state is AcquisitionProgressState.STARTED:
                    state = AcquisitionProgressState.STARTED
                else:
                    state = AcquisitionProgressState.RUNNING
                progress(
                    AcquisitionProgress(
                        value.phase,
                        state,
                        completed,
                        total_instruments,
                        phase_failures.get(value.phase, 0),
                        value.attempt,
                        value.max_attempts,
                        value.retry_after_seconds,
                    )
                )

            return emit

        for index, instrument_id in enumerate(resolved_inputs.instrument_ids):
            try:
                result = self._build_one(resolved_inputs, instrument_id, progress=aggregate(index))
                results.append(result)
                if published is not None:
                    published(result["research_id"])
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

    def _build_one(
        self,
        inputs: ResearchBuildInputs,
        instrument_id: str,
        *,
        progress: ProgressSink | None,
    ) -> dict[str, Any]:
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
        fetcher = self._registry.load_security_research_fetcher("yfinance")
        imported = (
            fetcher.fetch_research(request)
            if progress is None
            else fetcher.fetch_research(request, progress=progress)
        )
        if imported.request != request or imported.source_name != "yfinance":
            raise ValueError("source result must preserve the exact yfinance research request")
        benchmarks = self._benchmarks(row, inputs, start, end, runtime, progress=progress)
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
        *,
        progress: ProgressSink | None,
    ) -> ImportedEquityBatch | None:
        if "benchmarks" not in inputs.evidence:
            return None
        instruments = tuple(
            sorted(
                (
                    EquityBatchInstrument(
                        INDEX_RUNTIME_CATALOG[index].instrument(),
                        INDEX_RUNTIME_CATALOG[index].provider_symbol,
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
        fetcher = self._registry.load_equity_batch_fetcher("yfinance")
        if progress is None:
            return fetcher.fetch(request)

        def benchmark_progress(value: AcquisitionProgress) -> None:
            progress(
                AcquisitionProgress(
                    "research_benchmarks",
                    value.state,
                    value.completed,
                    value.total,
                    value.failure_count,
                    value.attempt,
                    value.max_attempts,
                    value.retry_after_seconds,
                )
            )

        return fetcher.fetch(request, progress=benchmark_progress)

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
