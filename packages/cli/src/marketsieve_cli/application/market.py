"""Broad yfinance Market Snapshot orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from importlib import resources
from typing import Any, Protocol

from marketsieve.analysis.indicators import CONTEXT, canonical_decimal
from marketsieve.data.daily import Adjustment
from marketsieve.domain import Instrument
from marketsieve.matrix import (
    INDEX_BENCHMARKS,
    MatrixField,
    MatrixRow,
    MatrixSecurity,
    build_matrix_row,
    field_definitions,
)
from marketsieve_cli.contracts import MarketBuildInputs, RuntimeSettings
from marketsieve_extension_api import (
    EquityAcquisitionFailure,
    EquityBatchFetcher,
    EquityBatchInstrument,
    EquityBatchRequest,
)


class SettingsReader(Protocol):
    def runtime(self) -> RuntimeSettings: ...

    def effective_document(self) -> dict[str, Any]: ...

    def effective_hash(self) -> str: ...


class BatchRegistry(Protocol):
    def load_equity_batch_fetcher(self, name: str) -> EquityBatchFetcher: ...


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
        fields: tuple[MatrixField, ...],
        rows: tuple[MatrixRow, ...],
        summary: dict[str, Any],
        failures: tuple[dict[str, str], ...],
    ) -> dict[str, Any]: ...

    def show(self, snapshot_id: str) -> dict[str, Any]: ...

    def list(self) -> dict[str, Any]: ...

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
        self, inputs: MarketBuildInputs | None, *, resume: str | None = None
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
            )
        assert inputs is not None
        universe, assets = _load_universe(inputs.indices)
        benchmark_seeds = (
            _benchmark_seeds(inputs.indices) if "benchmarks" in inputs.evidence else ()
        )
        requested = tuple(sorted((*universe, *benchmark_seeds), key=_seed_key))
        acquisition_date = self._today()
        if resume is None:
            end = acquisition_date
            start = end - timedelta(days=inputs.history_days or 0)
        else:
            try:
                assert stored_request is not None
                start = date.fromisoformat(str(stored_request["start"]))
                end = date.fromisoformat(str(stored_request["end"]))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("stored market snapshot run has an invalid date window") from error
            if end != acquisition_date:
                raise ValueError(
                    "market snapshot runs can be resumed only on their original acquisition date; "
                    "start a new build"
                )
        fingerprint_document = {
            "schema": "market-snapshot-request/v2",
            "inputs": {
                "indices": list(inputs.indices),
                "evidence": list(inputs.evidence),
                "history_days": inputs.history_days,
            },
            "assets": assets,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": Adjustment.ADJUSTED.value,
            "runtime_settings": self._settings.effective_document(),
            "runtime_settings_hash": self._settings.effective_hash(),
            "source": {"name": "yfinance"},
        }
        fingerprint = hashlib.sha256(_json_bytes(fingerprint_document)).hexdigest()
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
        fetcher = self._registry.load_equity_batch_fetcher("yfinance")
        diagnostic = fetcher.doctor()
        if not diagnostic.ready:
            raise RuntimeError(diagnostic.message)
        imported = fetcher.fetch(request)
        if imported.request != request:
            raise ValueError("source fetch result must preserve the exact market request")
        if self._today() != acquisition_date:
            raise ValueError(
                "market acquisition crossed the local date boundary; start a new build"
            )
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
        rows: list[MatrixRow] = []
        for seed in universe:
            observation = observations[(seed.instrument.mic, seed.instrument.symbol)]
            security = MatrixSecurity(
                instrument=seed.instrument,
                provider_symbol=seed.provider_symbol,
                memberships=seed.memberships,
                retrieved_at=observation.retrieved_at,
                bars=observation.bars,
                profile=observation.profile,
                financials=observation.financials,
                evidence_id=observation.source_hash,
            )
            calculated = build_matrix_row(security, benchmarks)
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
                MatrixRow(
                    MatrixSecurity(
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
            "price_requirements_met": summary["price_requirements_met"],
        }
        return self._store.put(
            run_id=run_id,
            manifest_body=manifest_body,
            fields=field_definitions(),
            rows=ordered_rows,
            summary=summary,
            failures=failures,
        )

    def diff(
        self, left_snapshot_id: str, right_snapshot_id: str, fields: tuple[str, ...]
    ) -> dict[str, Any]:
        return self._store.diff(left_snapshot_id, right_snapshot_id, fields)

    def show(self, snapshot_id: str) -> dict[str, Any]:
        return self._store.show(snapshot_id)

    def list(self) -> dict[str, Any]:
        return self._store.list()

    def row(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        return self._store.row(snapshot_id, instrument_id)

    def compare(
        self, snapshot_id: str, instrument_ids: tuple[str, ...], fields: tuple[str, ...]
    ) -> dict[str, Any]:
        if len(instrument_ids) < 2:
            raise ValueError("market snapshot compare requires at least two instruments")
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("market snapshot compare instruments must be unique")
        return self._store.compare(snapshot_id, instrument_ids, fields)

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
    ) -> dict[str, Any]:
        return self._store.query(
            snapshot_id,
            filters=filters,
            minimums=minimums,
            maximums=maximums,
            present=present,
            missing=missing,
            fields=fields,
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


def _decimal(values: Mapping[str, str], name: str) -> Decimal | None:
    try:
        return Decimal(values[name])
    except (KeyError, ArithmeticError):
        return None


def _median(values: list[Decimal]) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    with localcontext(CONTEXT):
        result = (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
        )
    return canonical_decimal(result)


def _percentile(values: list[Decimal], percentile: int) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    with localcontext(CONTEXT):
        position = Decimal(len(ordered) - 1) * Decimal(percentile) / Decimal(100)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - Decimal(lower)
        result = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return canonical_decimal(result)


def _ratio_text(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator == 0:
        return None
    with localcontext(CONTEXT):
        return canonical_decimal(numerator / denominator)


def _summary(
    rows: tuple[MatrixRow, ...],
    indices: tuple[str, ...],
    runtime: RuntimeSettings,
    retrieved_at: datetime,
    *,
    price_requested: bool,
) -> dict[str, Any]:
    with localcontext(CONTEXT):
        return _build_summary(rows, indices, runtime, retrieved_at, price_requested=price_requested)


def _build_summary(
    rows: tuple[MatrixRow, ...],
    indices: tuple[str, ...],
    runtime: RuntimeSettings,
    retrieved_at: datetime,
    *,
    price_requested: bool,
) -> dict[str, Any]:
    groups: dict[str, tuple[MatrixRow, ...]] = {
        "all": rows,
        **{
            f"index:{index}": tuple(row for row in rows if index in row.security.memberships)
            for index in indices
        },
    }
    groups["market:jp"] = tuple(row for row in rows if row.security.instrument.mic == "XTKS")
    groups["market:us"] = tuple(row for row in rows if row.security.instrument.mic != "XTKS")
    for classification_field, prefix in (("sector", "sector"), ("industry", "industry")):
        classification_values = sorted(
            {
                classification_value
                for row in rows
                if (classification_value := dict(row.values).get(classification_field)) is not None
            }
        )
        for classification_value in classification_values:
            groups[f"{prefix}:{classification_value}"] = tuple(
                row
                for row in rows
                if dict(row.values).get(classification_field) == classification_value
            )
    documents: dict[str, Any] = {}
    for name, selected in groups.items():
        present = [row for row in selected if "close" in dict(row.values)]
        returns = [
            value
            for row in present
            if (value := _decimal(dict(row.values), "return_1d")) is not None
        ]
        values_by_name = {
            field: [
                value
                for row in selected
                if (value := _decimal(dict(row.values), field)) is not None
            ]
            for field in (
                "return_20d",
                "return_60d",
                "return_252d",
                "volatility_60d",
                "volatility_252d",
                "maximum_drawdown_252d",
                "trailing_pe",
                "price_to_book",
                "return_on_equity",
                "operating_margin",
                "revenue_growth",
            )
        }
        market_caps_by_currency: dict[str, list[Decimal]] = {}
        traded_values_by_currency: dict[str, list[Decimal]] = {}
        for row in selected:
            row_values = dict(row.values)
            currency = row_values.get("currency")
            market_cap = _decimal(row_values, "market_cap")
            if currency is not None and market_cap is not None:
                market_caps_by_currency.setdefault(currency, []).append(market_cap)
            traded_value = _decimal(row_values, "median_traded_value_20d")
            if currency is not None and traded_value is not None:
                traded_values_by_currency.setdefault(currency, []).append(traded_value)
        currency_totals = {
            currency: sum(values, start=Decimal(0))
            for currency, values in market_caps_by_currency.items()
        }
        concentration_by_currency = {}
        for currency, market_caps in sorted(market_caps_by_currency.items()):
            total = currency_totals[currency]
            concentration_by_currency[currency] = {
                "market_cap_observation_count": len(market_caps),
                "top_10_market_cap_share": _ratio_text(
                    sum(sorted(market_caps, reverse=True)[:10], start=Decimal(0)), total
                )
                if total > 0
                else None,
            }
        only_currency = next(iter(market_caps_by_currency), None)
        if len(market_caps_by_currency) != 1:
            only_currency = None
        sector_counts: dict[str, int] = {}
        sector_market_caps: dict[str, dict[str, Decimal]] = {}
        missing_fields: dict[str, int] = {}
        missing_reasons: dict[str, int] = {}
        for row in selected:
            row_values = dict(row.values)
            sector = row_values.get("sector", "unclassified")
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            market_cap = _decimal(row_values, "market_cap")
            currency = row_values.get("currency")
            if market_cap is not None and currency is not None:
                currency_values = sector_market_caps.setdefault(sector, {})
                currency_values[currency] = currency_values.get(currency, Decimal(0)) + market_cap
            for field, reason in row.missing:
                missing_fields[field] = missing_fields.get(field, 0) + 1
                missing_reasons[reason] = missing_reasons.get(reason, 0) + 1
        documents[name] = {
            "security_count": len(selected),
            "price_count": len(present),
            "latest_price_date": max(
                (
                    latest_price_date
                    for row in present
                    if (latest_price_date := dict(row.values).get("price_as_of")) is not None
                ),
                default=None,
            ),
            "price_coverage": _ratio_text(Decimal(len(present)), Decimal(len(selected)))
            if selected
            else "0",
            "advancing_count": sum(value > 0 for value in returns),
            "declining_count": sum(value < 0 for value in returns),
            "unchanged_count": sum(value == 0 for value in returns),
            "above_sma_20_count": sum(
                (_decimal(dict(row.values), "distance_sma_20") or Decimal("-1")) > 0
                for row in present
            ),
            "above_sma_200_count": sum(
                (_decimal(dict(row.values), "distance_sma_200") or Decimal("-1")) > 0
                for row in present
            ),
            "distributions": {
                field: {
                    "count": len(values),
                    "p25": _percentile(values, 25),
                    "median": _median(values),
                    "p75": _percentile(values, 75),
                }
                for field, values in values_by_name.items()
                if values
            },
            "currency_distributions": {
                field: {
                    currency: {
                        "count": len(currency_values),
                        "p25": _percentile(currency_values, 25),
                        "median": _median(currency_values),
                        "p75": _percentile(currency_values, 75),
                    }
                    for currency, currency_values in sorted(values_by_currency.items())
                }
                for field, values_by_currency in (
                    ("market_cap", market_caps_by_currency),
                    ("median_traded_value_20d", traded_values_by_currency),
                )
            },
            "concentration": {
                "market_cap_observation_count": sum(
                    len(values) for values in market_caps_by_currency.values()
                ),
                "top_10_market_cap_share": (
                    concentration_by_currency[only_currency]["top_10_market_cap_share"]
                    if only_currency is not None
                    else None
                ),
                "by_currency": concentration_by_currency,
            },
            "sectors": {
                sector: {
                    "security_count": sector_counts[sector],
                    "market_cap_share": (
                        _ratio_text(
                            sector_market_caps.get(sector, {}).get(only_currency, Decimal(0)),
                            currency_totals[only_currency],
                        )
                        if only_currency is not None and currency_totals[only_currency] > 0
                        else None
                    ),
                    "market_cap_share_by_currency": {
                        currency: (
                            _ratio_text(value, currency_totals[currency])
                            if currency_totals[currency] > 0
                            else None
                        )
                        for currency, value in sorted(sector_market_caps.get(sector, {}).items())
                    },
                }
                for sector in sorted(sector_counts)
            },
            "missing": {
                "fields": dict(sorted(missing_fields.items())),
                "reasons": dict(sorted(missing_reasons.items())),
            },
        }
    overall = Decimal(documents["all"]["price_coverage"])
    index_coverages = {
        index: Decimal(documents[f"index:{index}"]["price_coverage"]) for index in indices
    }
    meets = (not price_requested) or (
        overall >= runtime.market_quality.minimum_overall_price_coverage
        and all(
            value >= runtime.market_quality.minimum_index_price_coverage
            for value in index_coverages.values()
        )
    )
    return {
        "schema": "market-snapshot-summary/v1",
        "generated_at": retrieved_at.isoformat(),
        "coverage": {
            "overall": canonical_decimal(overall),
            "indices": {
                key: canonical_decimal(value) for key, value in sorted(index_coverages.items())
            },
        },
        "price_requirements_met": meets,
        "groups": documents,
    }


def _failures(
    rows: tuple[MatrixRow, ...],
    provider_failures: tuple[Any, ...],
) -> tuple[dict[str, str], ...]:
    output = []
    for value in provider_failures:
        output.append(
            {
                "instrument_id": f"{value.instrument.mic}:{value.instrument.symbol}",
                "stage": value.stage,
                "field": value.field,
                "reason": value.reason,
            }
        )
    for row in rows:
        instrument_id = f"{row.security.instrument.mic}:{row.security.instrument.symbol}"
        output.extend(
            {
                "instrument_id": instrument_id,
                "stage": "calculation",
                "field": field,
                "reason": reason,
            }
            for field, reason in row.missing
            if reason not in {"not_applicable", "not_requested"}
        )
    return tuple(
        sorted(
            output,
            key=lambda value: (
                value["instrument_id"],
                value["stage"],
                value["field"],
                value["reason"],
            ),
        )
    )
