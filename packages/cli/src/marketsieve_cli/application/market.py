"""Broad yfinance Market Snapshot orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from decimal import Decimal
from importlib import resources
from typing import Any, Protocol

from marketsieve import __version__
from marketsieve._snapshot import (
    SnapshotRow,
    SnapshotSecurityEvidence,
    build_snapshot_row,
)
from marketsieve._snapshot_fields import INDEX_BENCHMARKS, field_definitions
from marketsieve.fields import FieldDefinition
from marketsieve.model import Adjustment, Instrument
from marketsieve_cli.application.acquisition_errors import (
    MarketSnapshotRunCancelled,
    MarketSnapshotRunInterrupted,
)
from marketsieve_cli.application.market_summary import _failures, _summary
from marketsieve_cli.contracts import (
    MarketBuildInputs,
    MarketCompareInputs,
    MarketDiffInputs,
    MarketQueryInputs,
    RuntimeSettings,
)
from marketsieve_extension_api import (
    EquityAcquisitionFailure,
    EquityBatchFetcher,
    EquityBatchInstrument,
    EquityBatchRequest,
    MarketIndicatorFetcher,
    MarketIndicatorKind,
    MarketIndicatorRequest,
    MarketIndicatorSpec,
    ProgressSink,
)


class SettingsReader(Protocol):
    def runtime(self) -> RuntimeSettings: ...

    def effective_document(self) -> dict[str, Any]: ...

    def effective_hash(self) -> str: ...


class BatchRegistry(Protocol):
    def load_equity_batch_fetcher(self, name: str) -> EquityBatchFetcher: ...

    def load_market_indicator_fetcher(self, name: str) -> MarketIndicatorFetcher: ...


class MarketSnapshotRepository(Protocol):
    """Persistence boundary required by the Market Snapshot service."""

    def run_request(self, run_id: str) -> dict[str, Any]: ...

    def begin_run(
        self,
        fingerprint: str,
        request_document: dict[str, Any],
        *,
        resume: str | None,
    ) -> str: ...

    def put(
        self,
        *,
        run_id: str,
        manifest_body: dict[str, Any],
        fields: tuple[FieldDefinition, ...],
        rows: tuple[SnapshotRow, ...],
        summary: dict[str, Any],
        failures: tuple[dict[str, str], ...],
        market_indicators: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]: ...

    def show(self, snapshot_id: str) -> dict[str, Any]: ...

    def list(self) -> dict[str, Any]: ...

    def find_by_request_fingerprint(self, fingerprint: str) -> dict[str, Any] | None: ...

    def row(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]: ...

    def compare(
        self, snapshot_id: str, instrument_ids: tuple[str, ...], fields: tuple[str, ...]
    ) -> dict[str, Any]: ...

    def query(
        self,
        snapshot_id: str,
        *,
        filters: dict[str, tuple[str, ...]],
        minimums: dict[str, Decimal],
        maximums: dict[str, Decimal],
        present: tuple[str, ...],
        missing: tuple[str, ...],
        fields: tuple[str, ...],
        order: tuple[str, ...] = (),
        limit: int | None = None,
        domains: tuple[str, ...] = (),
        profile: str | None = None,
        budget: Decimal | None = None,
        budget_currency: str | None = None,
        trading_unit: int | None = None,
        use_snapshot_fx: bool = False,
    ) -> dict[str, Any]: ...

    def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]: ...

    def diff(
        self, left_snapshot_id: str, right_snapshot_id: str, fields: tuple[str, ...]
    ) -> dict[str, Any]: ...


class MarketService:
    """Acquire one complete fixed universe and persist a Market Snapshot."""

    def __init__(
        self,
        registry: BatchRegistry,
        store: MarketSnapshotRepository,
        settings: SettingsReader,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._registry = registry
        self._store = store
        self._settings = settings
        self._today = today

    def build(
        self,
        inputs: MarketBuildInputs | None,
        *,
        resume: str | None = None,
        progress: ProgressSink | None = None,
    ) -> dict[str, Any]:
        runtime = self._settings.runtime()
        if resume is None and inputs is None:
            raise ValueError("market build inputs are required")
        if resume is not None and inputs is not None:
            raise ValueError("--resume cannot be combined with market build inputs")
        stored_request = self._store.run_request(resume) if resume is not None else None
        if stored_request is not None:
            inputs = MarketBuildInputs(
                tuple(stored_request["inputs"]["indices"]),
                tuple(stored_request["inputs"]["evidence"]),
                stored_request["inputs"]["history_days"],
                (
                    date.fromisoformat(stored_request["inputs"]["as_of"])
                    if stored_request["inputs"].get("as_of") is not None
                    else None
                ),
                stored_request["inputs"].get("mode", "current"),
                stored_request["inputs"].get("session"),
            )
        assert inputs is not None
        universe, assets = _load_universe(inputs.indices)
        benchmark_seeds = (
            _benchmark_seeds(inputs.indices) if "benchmarks" in inputs.evidence else ()
        )
        indicator_specs = _market_indicator_specs() if "price" in inputs.evidence else ()
        requested = _merge_batch_instruments((*universe, *benchmark_seeds))
        acquisition_date = self._today()
        end_date = inputs.as_of or acquisition_date
        if end_date > acquisition_date:
            raise ValueError("market acquisition date cannot be in the future")
        if inputs.mode == "historical_price_reconstruction":
            asset_dates = [date.fromisoformat(value["as_of"]) for value in assets.values()]
            if end_date < max(asset_dates):
                raise ValueError(
                    "historical reconstruction predates the built-in universe asset basis"
                )
        if resume is None:
            end = end_date
            start = end - timedelta(days=inputs.history_days or 0)
        else:
            try:
                assert stored_request is not None
                start = date.fromisoformat(str(stored_request["start"]))
                end = date.fromisoformat(str(stored_request["end"]))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("stored market snapshot run has an invalid date window") from error
            if inputs.mode == "current" and end != acquisition_date:
                raise ValueError(
                    "market snapshot runs can be resumed only on their original acquisition date; "
                    "start a new build"
                )
        fingerprint_document = {
            "schema": "market-snapshot-request/v3",
            "inputs": {
                "indices": list(inputs.indices),
                "evidence": list(inputs.evidence),
                "history_days": inputs.history_days,
                "as_of": inputs.as_of.isoformat() if inputs.as_of is not None else None,
                "mode": inputs.mode,
                "session": inputs.session,
            },
            "assets": assets,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": Adjustment.ADJUSTED.value,
            "runtime_settings": self._settings.effective_document(),
            "runtime_settings_hash": self._settings.effective_hash(),
            "source": {"name": "yfinance"},
            "producer": {
                "name": "marketsieve-cli",
                "version": __version__,
                "snapshot_schema": "market-snapshot/v9",
                "explorer_schema": "explorer-data/v5",
            },
        }
        fingerprint = hashlib.sha256(_json_bytes(fingerprint_document)).hexdigest()
        existing = self._store.find_by_request_fingerprint(fingerprint)
        if existing is not None and resume is None:
            return {
                **existing,
                "run": {
                    "schema": "capture-run/v1",
                    "run_id": fingerprint[:16],
                    "status": "duplicate",
                    "exit_code": 0,
                    "resumable": False,
                },
            }
        run_id = self._store.begin_run(
            fingerprint,
            fingerprint_document,
            resume=resume,
        )
        request = EquityBatchRequest(
            source_profile="market-yfinance",
            instruments=requested,
            start=start,
            end=end,
            adjustment=Adjustment.ADJUSTED,
            batch_size=runtime.yfinance.batch_size,
            profile_workers=runtime.yfinance.company_workers,
            timeout_seconds=runtime.yfinance.timeout_seconds,
            max_retries=runtime.yfinance.max_retries,
            retry_base_seconds=runtime.yfinance.retry_base_seconds,
            settings={"cache_dir": ".marketsieve/cache/yfinance"},
            evidence=inputs.evidence,
        )
        try:
            fetcher = self._registry.load_equity_batch_fetcher("yfinance")
            diagnostic = fetcher.doctor()
            if not diagnostic.ready:
                raise RuntimeError(diagnostic.message)
            imported = (
                fetcher.fetch(request)
                if progress is None
                else fetcher.fetch(request, progress=progress)
            )
            if imported.request != request:
                raise ValueError("source fetch result must preserve the exact market request")
        except KeyboardInterrupt as error:
            raise MarketSnapshotRunCancelled(run_id) from error
        except Exception as error:
            raise MarketSnapshotRunInterrupted(run_id, error) from error
        if inputs.mode == "current" and self._today() != acquisition_date:
            raise ValueError(
                "market acquisition crossed the local date boundary; start a new build"
            )
        indicator_import = None
        if indicator_specs:
            indicator_fetcher = self._registry.load_market_indicator_fetcher("yfinance")
            indicator_request = MarketIndicatorRequest(
                source_profile="market-indicators-yfinance",
                indicators=indicator_specs,
                start=start,
                end=end,
                timeout_seconds=runtime.yfinance.timeout_seconds,
                max_retries=runtime.yfinance.max_retries,
                retry_base_seconds=runtime.yfinance.retry_base_seconds,
                settings={"cache_dir": ".marketsieve/cache/yfinance"},
            )
            try:
                indicator_import = (
                    indicator_fetcher.fetch_market_indicators(indicator_request)
                    if progress is None
                    else indicator_fetcher.fetch_market_indicators(
                        indicator_request, progress=progress
                    )
                )
                if indicator_import.request != indicator_request:
                    raise ValueError("source must preserve the exact market indicator request")
            except KeyboardInterrupt as error:
                raise MarketSnapshotRunCancelled(run_id) from error
            except Exception as error:
                raise MarketSnapshotRunInterrupted(run_id, error) from error
        benchmark_ids = {
            seed.provider_symbol: (seed.instrument.mic, seed.instrument.symbol)
            for seed in benchmark_seeds
        }
        observations = {
            (value.requested.instrument.mic, value.requested.instrument.symbol): value
            for value in imported.observations
        }
        benchmarks: dict[str, tuple[Any, ...]] = {}
        benchmark_failure_reasons: dict[str, str] = {}
        for index, symbol in INDEX_BENCHMARKS.items():
            if index not in inputs.indices or "benchmarks" not in inputs.evidence:
                continue
            benchmark_identity = benchmark_ids[symbol]
            observation = observations.get(benchmark_identity)
            benchmarks[index] = observation.bars if observation is not None else ()
            reasons = [
                value.reason
                for value in imported.failures
                if (value.instrument.mic, value.instrument.symbol) == benchmark_identity
                and value.stage == "price"
            ]
            if reasons:
                benchmark_failure_reasons[index] = max(reasons, key=_failure_reason_priority)
        rows: list[SnapshotRow] = []
        for seed in universe:
            observation = observations[(seed.instrument.mic, seed.instrument.symbol)]
            security = SnapshotSecurityEvidence(
                instrument=seed.instrument,
                provider_symbol=seed.provider_symbol,
                memberships=seed.memberships,
                retrieved_at=observation.retrieved_at,
                bars=observation.bars,
                profile=observation.profile,
                financials=observation.financials,
                evidence_id=observation.source_hash,
            )
            calculated = build_snapshot_row(security, benchmarks)
            overrides = _missing_overrides(
                seed,
                imported.failures,
                benchmark_failure_reasons,
                successful_fields=frozenset(name for name, _ in calculated.values),
            )
            overrides = _merge_missing_overrides(
                overrides,
                _not_requested_fields(inputs.evidence),
            )
            values = dict(calculated.values)
            missing = dict(calculated.missing)
            for field, reason in overrides:
                values.pop(field, None)
                missing[field] = reason
            rows.append(
                SnapshotRow(
                    SnapshotSecurityEvidence(
                        instrument=security.instrument,
                        provider_symbol=security.provider_symbol,
                        memberships=security.memberships,
                        retrieved_at=security.retrieved_at,
                        bars=security.bars,
                        profile=security.profile,
                        financials=security.financials,
                        evidence_id=security.evidence_id,
                        missing=overrides,
                    ),
                    tuple(sorted(values.items())),
                    tuple(sorted(missing.items())),
                )
            )
        ordered_rows = tuple(sorted(rows, key=lambda value: _seed_key(value.security)))
        identities = tuple(_seed_key(row.security) for row in ordered_rows)
        if len(identities) != len(set(identities)):
            raise ValueError("provider exchange normalization created duplicate securities")
        summary = _summary(
            ordered_rows,
            inputs.indices,
            runtime,
            imported.retrieved_at,
            price_requested="price" in inputs.evidence,
        )
        failures = _failures(ordered_rows, imported.failures)
        indicator_failure_reasons: dict[str, str] = {}
        if indicator_import is not None:
            for failure in indicator_import.failures:
                current = indicator_failure_reasons.get(failure.indicator_id)
                if current is None or _failure_reason_priority(
                    failure.reason
                ) > _failure_reason_priority(current):
                    indicator_failure_reasons[failure.indicator_id] = failure.reason
            failures = (
                *failures,
                *(
                    {
                        "schema": "market-snapshot-failure/v2",
                        "instrument_id": f"market_indicator:{failure.indicator_id}",
                        "indicator_id": failure.indicator_id,
                        "stage": failure.stage,
                        "field": failure.field,
                        "reason": failure.reason,
                    }
                    for failure in indicator_import.failures
                ),
            )
        indicator_observations = {
            item.requested.indicator_id: item
            for item in (() if indicator_import is None else indicator_import.observations)
        }
        market_indicators = tuple(
            {
                "schema": "market-indicator/v2",
                "indicator_id": spec.indicator_id,
                "provider_symbol": spec.provider_symbol,
                "name": spec.name,
                "kind": spec.kind.value,
                "unit": spec.unit,
                "retrieved_at": indicator_observations[spec.indicator_id].retrieved_at.isoformat(),
                "observations": [
                    {"date": bar.trading_date.isoformat(), "value": str(bar.close)}
                    for bar in indicator_observations[spec.indicator_id].bars
                ],
                "missing_reason": (
                    None
                    if indicator_observations[spec.indicator_id].bars
                    else indicator_failure_reasons.get(spec.indicator_id, "history_empty")
                ),
                "not_applicable": [
                    "company_information",
                    "financials",
                    "market_cap",
                    "shares_outstanding",
                    "volume_metrics",
                ],
            }
            for spec in indicator_specs
        )
        manifest_body = {
            "created_at": imported.retrieved_at.isoformat(),
            "request": {"fingerprint": fingerprint, **fingerprint_document},
            "inputs": fingerprint_document["inputs"],
            "runtime_settings": fingerprint_document["runtime_settings"],
            "runtime_settings_hash": fingerprint_document["runtime_settings_hash"],
            "request_fingerprint": fingerprint,
            "source": {
                "name": imported.source_name,
                "version": imported.source_version,
                "dataset": imported.dataset,
                "response_hash": imported.response_hash,
            },
            "input_snapshot_id": imported.response_hash,
            "universe_assets": assets,
            "row_count": len(ordered_rows),
            "field_count": len(field_definitions()),
            "failure_count": len(failures),
            "coverage": summary["coverage"],
            "price_coverage_gate_passed": summary["price_requirements_met"],
        }
        document = self._store.put(
            run_id=run_id,
            manifest_body=manifest_body,
            fields=field_definitions(),
            rows=ordered_rows,
            summary=summary,
            failures=failures,
            market_indicators=market_indicators,
        )
        return {
            **document,
            "run": {
                "schema": "capture-run/v1",
                "run_id": run_id,
                "status": "completed",
                "exit_code": 0,
                "resumable": False,
            },
        }

    def diff(self, request: MarketDiffInputs) -> dict[str, Any]:
        return self._store.diff(request.left_snapshot_id, request.right_snapshot_id, request.fields)

    def show(self, snapshot_id: str) -> dict[str, Any]:
        return self._store.show(snapshot_id)

    def list(self) -> dict[str, Any]:
        return self._store.list()

    def row(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        return self._store.row(snapshot_id, instrument_id)

    def compare(self, request: MarketCompareInputs) -> dict[str, Any]:
        return self._store.compare(request.snapshot_id, request.instrument_ids, request.fields)

    def query(self, request: MarketQueryInputs) -> dict[str, Any]:
        return self._store.query(
            request.snapshot_id,
            filters=request.filters,
            minimums=request.minimums,
            maximums=request.maximums,
            present=request.present,
            missing=request.missing,
            fields=request.fields,
            order=request.order,
            limit=request.limit,
            domains=request.domains,
            profile=request.profile,
            budget=request.budget,
            budget_currency=request.budget_currency,
            trading_unit=request.trading_unit,
            use_snapshot_fx=request.use_snapshot_fx,
        )

    def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        return self._store.research_context(snapshot_id, instrument_id)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


_FAILURE_REASON_PRIORITY = {
    "field_absent": 0,
    "financials_unavailable": 1,
    "history_empty": 2,
    "stale_history": 3,
    "symbol_not_found": 3,
    "corporate_action_mismatch": 4,
    "provider_error": 4,
    "network_error": 5,
    "rate_limited": 6,
}

_PROFILE_FAILURE_FIELDS = {
    "name",
    "exchange",
    "country",
    "currency",
    "financial_currency",
    "sector",
    "industry",
    "quote_type",
    "market_cap",
    "enterprise_value",
    "shares_outstanding",
    "revenue_ttm",
    "ebitda_ttm",
    "operating_income_ttm",
    "net_income_ttm",
    "operating_cash_flow_ttm",
    "free_cash_flow_ttm",
    "total_cash",
    "total_debt",
    "revenue_growth",
    "earnings_growth",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "return_on_equity",
    "return_on_assets",
    "debt_to_equity",
    "current_ratio",
    "quick_ratio",
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "price_to_sales",
    "enterprise_to_revenue",
    "enterprise_to_ebitda",
    "dividend_yield",
    "payout_ratio",
    "volume_turnover_20d",
    "earnings_yield",
    "free_cash_flow_yield",
}
_FINANCIAL_FAILURE_GROUPS = {
    "financial",
    "fundamental",
    "profitability",
    "safety",
    "valuation",
}
_VOLUME_FAILURE_FIELDS = {
    "volume_20d": {
        "average_volume_20d",
        "average_volume_60d",
        "median_traded_value_20d",
        "volume_turnover_20d",
        "amihud_illiquidity_20d",
        "zero_volume_days_20d",
    },
    "volume_60d": {"average_volume_60d"},
}

MARKET_INDICATORS = {
    "gold": ("GC=F", MarketIndicatorKind.COMMODITY, "USD_per_troy_ounce", "Gold futures proxy"),
    "major_index_dow": (
        "^DJI",
        MarketIndicatorKind.EQUITY_INDEX,
        "index_points",
        "Dow Jones Industrial Average",
    ),
    "major_index_nasdaq100": (
        "^NDX",
        MarketIndicatorKind.EQUITY_INDEX,
        "index_points",
        "Nasdaq-100 index",
    ),
    "major_index_nikkei225": (
        "^N225",
        MarketIndicatorKind.EQUITY_INDEX,
        "index_points",
        "Nikkei 225 index",
    ),
    "major_index_sp500": (
        "^GSPC",
        MarketIndicatorKind.EQUITY_INDEX,
        "index_points",
        "S&P 500 index",
    ),
    "oil_wti": (
        "CL=F",
        MarketIndicatorKind.COMMODITY,
        "USD_per_barrel",
        "WTI crude-oil futures proxy",
    ),
    "usd_jpy": ("JPY=X", MarketIndicatorKind.FX_RATE, "JPY_per_USD", "U.S. dollar to Japanese yen"),
    "us_rate_10y": ("^TNX", MarketIndicatorKind.YIELD, "percent", "U.S. 10-year Treasury yield"),
    "us_rate_3m": ("^IRX", MarketIndicatorKind.YIELD, "percent", "U.S. 13-week Treasury yield"),
    "vix": ("^VIX", MarketIndicatorKind.VOLATILITY_INDEX, "index_points", "CBOE Volatility Index"),
}


def _failure_reason_priority(reason: str) -> tuple[int, str]:
    return _FAILURE_REASON_PRIORITY.get(reason, 3), reason


def _provider_failure_fields(failure: EquityAcquisitionFailure) -> set[str]:
    definitions = field_definitions()
    known = {field.name for field in definitions}
    selected = {failure.field} & known
    if failure.stage == "price":
        selected.update(
            field.name
            for field in definitions
            if field.group in {"price", "return", "trend", "momentum", "risk", "liquidity"}
        )
    elif failure.stage == "profile":
        selected.update(_PROFILE_FAILURE_FIELDS & known)
    elif failure.stage == "financials":
        if failure.field == "company_financials":
            selected.update(
                field.name for field in definitions if field.group in _FINANCIAL_FAILURE_GROUPS
            )
        financial_fields = {
            "annual_income": {
                "revenue_cagr_3y",
                "earnings_cagr_3y",
            },
            "quarterly_income": {
                "revenue_ttm",
                "ebitda_ttm",
                "operating_income_ttm",
                "net_income_ttm",
                "free_cash_flow_margin",
            },
            "balance_sheet": {
                "total_assets",
                "total_equity",
                "total_cash",
                "total_debt",
                "equity_ratio",
            },
            "quarterly_cash_flow": {
                "operating_cash_flow_ttm",
                "capital_expenditure_ttm",
                "free_cash_flow_ttm",
                "free_cash_flow_margin",
                "free_cash_flow_yield",
            },
        }
        selected.update(financial_fields.get(failure.field, ()))
    elif failure.stage == "volume":
        selected.update(_VOLUME_FAILURE_FIELDS.get(failure.field, ()))
    return selected


def _missing_overrides(
    seed: EquityBatchInstrument,
    failures: tuple[EquityAcquisitionFailure, ...],
    benchmark_failure_reasons: Mapping[str, str],
    *,
    successful_fields: frozenset[str] = frozenset(),
) -> tuple[tuple[str, str], ...]:
    """Map failures to affected cells while retaining independently acquired values."""

    identity = (seed.instrument.mic, seed.instrument.symbol)
    output: dict[str, str] = {}

    def assign(field: str, reason: str) -> None:
        current = output.get(field)
        if current is None or _failure_reason_priority(reason) > _failure_reason_priority(current):
            output[field] = reason

    for failure in failures:
        if (failure.instrument.mic, failure.instrument.symbol) != identity:
            continue
        for field in _provider_failure_fields(failure):
            if failure.stage in {"profile", "financials"} and field in successful_fields:
                continue
            assign(field, failure.reason)
        if failure.stage == "price":
            for index in seed.memberships:
                for period in (20, 60, 120, 252):
                    assign(f"relative_return_{index}_{period}d", failure.reason)
                assign(f"beta_{index}_252d", failure.reason)
    for index in seed.memberships:
        reason = benchmark_failure_reasons.get(index)
        if reason is None:
            continue
        for period in (20, 60, 120, 252):
            assign(f"relative_return_{index}_{period}d", reason)
        assign(f"beta_{index}_252d", reason)
    return tuple(sorted(output.items()))


def _not_requested_fields(evidence: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Mark omitted evidence domains as expected absences, not acquisition failures."""

    requested = set(evidence)
    fields = field_definitions()
    groups: set[str] = set()
    names: set[str] = set()
    if "price" not in requested:
        groups.update({"price", "return", "trend", "momentum", "risk", "liquidity", "relative"})
    if "benchmarks" not in requested:
        groups.add("relative")
    if "company" not in requested:
        groups.update({"identity", "size"})
        names.update({"volume_turnover_20d", "free_cash_flow_yield"})
    if "financials" not in requested:
        groups.update({"financial", "fundamental", "profitability", "safety", "valuation"})
    return tuple(
        sorted(
            (field.name, "not_requested")
            for field in fields
            if field.group in groups or field.name in names
            if not (field.name == "financial_currency" and "financials" in requested)
        )
    )


def _merge_missing_overrides(
    observed: tuple[tuple[str, str], ...],
    expected: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    output = dict(observed)
    output.update(expected)
    return tuple(sorted(output.items()))


def _seed_key(value: Any) -> tuple[str, str]:
    instrument = value.instrument
    return instrument.mic, instrument.symbol


def _merge_batch_instruments(
    values: tuple[EquityBatchInstrument, ...],
) -> tuple[EquityBatchInstrument, ...]:
    """Merge roles that resolve to the same exchange-qualified instrument."""

    grouped: dict[tuple[str, str], EquityBatchInstrument] = {}
    for value in values:
        identity = _seed_key(value)
        current = grouped.get(identity)
        if current is None:
            grouped[identity] = value
            continue
        if (
            current.instrument != value.instrument
            or current.provider_symbol != value.provider_symbol
        ):
            raise ValueError(
                f"conflicting market acquisition identity: {identity[0]}:{identity[1]}"
            )
        grouped[identity] = EquityBatchInstrument(
            current.instrument,
            current.provider_symbol,
            tuple(sorted(set(current.memberships) | set(value.memberships))),
            current.is_benchmark or value.is_benchmark,
        )
    return tuple(sorted(grouped.values(), key=_seed_key))


def _load_universe(
    selected_indices: tuple[str, ...],
) -> tuple[tuple[EquityBatchInstrument, ...], dict[str, Any]]:
    path = resources.files("marketsieve_cli.resources").joinpath("index_universe.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "index-universe/v1":
        raise ValueError("unsupported built-in index universe")
    if not isinstance(document.get("asset_version"), str) or not document["asset_version"]:
        raise ValueError("built-in index universe has no asset version")
    indices = document["indices"]
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    assets: dict[str, Any] = {}
    for index in selected_indices:
        value = indices[index]
        members = value["members"]
        if len(members) != value["constituent_count"]:
            raise ValueError(f"built-in index count is inconsistent: {index}")
        assets[index] = {
            key: value[key]
            for key in (
                "name",
                "benchmark_symbol",
                "benchmark_kind",
                "benchmark_name",
                "as_of",
                "source_url",
                "source_hash",
                "constituent_count",
            )
        }
        assets[index]["asset_version"] = document["asset_version"]
        assets[index]["asset_hash"] = hashlib.sha256(_json_bytes(value)).hexdigest()
        for member in members:
            identity = (str(member["mic"]), str(member["symbol"]))
            current = grouped.setdefault(
                identity,
                {**member, "memberships": set()},
            )
            current["memberships"].add(index)
    output: list[EquityBatchInstrument] = []
    for value in grouped.values():
        mic = str(value["mic"])
        output.append(
            EquityBatchInstrument(
                Instrument.create(
                    symbol=str(value["symbol"]),
                    mic=mic,
                    currency="JPY" if mic == "XTKS" else "USD",
                    exchange_timezone="Asia/Tokyo" if mic == "XTKS" else "America/New_York",
                ),
                str(value["provider_symbol"]),
                tuple(sorted(value["memberships"])),
            )
        )
    identities = [(value.instrument.mic, value.instrument.symbol) for value in output]
    if len(identities) != len(set(identities)):
        raise ValueError("built-in index universe contains duplicate identities")
    return tuple(sorted(output, key=_seed_key)), assets


def _benchmark_seeds(indices: tuple[str, ...]) -> tuple[EquityBatchInstrument, ...]:
    definitions = {
        "dow30": ("DJI", "XNYS", "USD", "America/New_York"),
        "nasdaq100": ("NDX", "XNAS", "USD", "America/New_York"),
        "nikkei225": ("N225", "XTKS", "JPY", "Asia/Tokyo"),
        "sp500": ("GSPC", "XNYS", "USD", "America/New_York"),
        "topix500": ("1308", "XTKS", "JPY", "Asia/Tokyo"),
    }
    return tuple(
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
        for index in indices
    )


def _market_indicator_specs() -> tuple[MarketIndicatorSpec, ...]:
    return tuple(
        MarketIndicatorSpec(
            indicator_id=indicator_id,
            provider_symbol=provider_symbol,
            name=name,
            kind=kind,
            unit=unit,
        )
        for indicator_id, (provider_symbol, kind, unit, name) in sorted(MARKET_INDICATORS.items())
    )
