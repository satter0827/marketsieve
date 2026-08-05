"""Deterministic historical decision replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from itertools import pairwise

from marketsieve.analysis.indicators import CONTEXT, canonical_decimal
from marketsieve.data.daily import DailyBar
from marketsieve.decision import (
    AnalysisContext,
    DecisionAction,
    DecisionConfidence,
    DecisionPolicy,
)
from marketsieve.domain import Instrument


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ReplayWindow:
    start: date
    end: date

    def __post_init__(self) -> None:
        if type(self.start) is not date or type(self.end) is not date:
            raise TypeError("replay window boundaries must be dates")
        if self.start > self.end:
            raise ValueError("replay window must be ascending")


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    policy_name: str
    policy_version: str
    policy_settings: tuple[tuple[str, str], ...]
    window: ReplayWindow
    datasets: tuple[tuple[str, str], ...]
    execution_costs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.policy_name or not self.policy_version:
            raise ValueError("experiment policy identity must not be empty")
        _pairs(self.policy_settings, "policy settings")
        _pairs(self.datasets, "datasets")
        _pairs(self.execution_costs, "execution costs")
        if not self.datasets:
            raise ValueError("experiment requires at least one dataset")
        if self.execution_costs and {key for key, _ in self.execution_costs} != {
            "commission_rate",
            "fx_cost_rate",
            "tax_rate",
        }:
            raise ValueError("execution costs must declare commission, tax, and FX rates together")
        for _, raw in self.execution_costs:
            value = Decimal(raw)
            if not value.is_finite() or not Decimal(0) <= value <= Decimal(1):
                raise ValueError("execution cost rates must be between zero and one")

    @property
    def spec_id(self) -> str:
        return _digest(_spec_document(self))

    @property
    def is_profit_simulation(self) -> bool:
        return bool(self.execution_costs)


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    instrument: Instrument
    as_of: datetime
    action: DecisionAction
    confidence: DecisionConfidence


@dataclass(frozen=True, slots=True)
class ExperimentMetric:
    name: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not self.name or not self.unit or not self.value.is_finite():
            raise ValueError("experiment metric must be finite and identified")


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    run_id: str
    spec: ExperimentSpec
    decisions: tuple[ReplayDecision, ...]
    metrics: tuple[ExperimentMetric, ...]

    def __post_init__(self) -> None:
        if len(self.run_id) != 64 or any(value not in "0123456789abcdef" for value in self.run_id):
            raise ValueError("experiment run ID must be a SHA-256 digest")
        keys = tuple(metric.name for metric in self.metrics)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("experiment metrics must have unique sorted names")


@dataclass(frozen=True, slots=True)
class ExperimentComparison:
    left_run_id: str
    right_run_id: str
    metric_deltas: tuple[ExperimentMetric, ...]


def run_experiment(
    spec: ExperimentSpec,
    policy: DecisionPolicy,
    datasets: tuple[tuple[str, Instrument, tuple[DailyBar, ...]], ...],
) -> ExperimentRun:
    """Replay a decision policy with only facts known at each observation instant."""

    if (policy.name, policy.version, policy.settings) != (
        spec.policy_name,
        spec.policy_version,
        spec.policy_settings,
    ):
        raise ValueError("experiment policy does not match its fixed specification")
    expected = dict(spec.datasets)
    supplied = {
        f"{instrument.mic}:{instrument.symbol}": data_id for data_id, instrument, _ in datasets
    }
    if supplied != expected or len(supplied) != len(datasets):
        raise ValueError("experiment datasets do not match the fixed specification")
    decisions: list[ReplayDecision] = []
    returns: list[Decimal] = []
    drawdowns: list[Decimal] = []
    for _, instrument, bars in sorted(datasets, key=lambda item: (item[1].mic, item[1].symbol)):
        _validate_bars(bars)
        peak: Decimal | None = None
        for index, bar in enumerate(bars):
            if not spec.window.start <= bar.trading_date <= spec.window.end:
                continue
            peak = bar.close if peak is None else max(peak, bar.close)
            with localcontext(CONTEXT):
                drawdowns.append(+(bar.close / peak - Decimal(1)))
            known = tuple(
                item for item in bars[: index + 1] if item.available_at <= bar.available_at
            )
            decision = policy.evaluate(AnalysisContext(instrument, bar.available_at, known))
            decisions.append(
                ReplayDecision(instrument, bar.available_at, decision.action, decision.confidence)
            )
            if index + 1 < len(bars):
                with localcontext(CONTEXT):
                    returns.append(+(bars[index + 1].close / bar.close - Decimal(1)))
    if not decisions:
        raise ValueError("experiment window contains no observations")
    metrics = _metrics(tuple(decisions), returns, drawdowns)
    payload = {
        "spec": _spec_document(spec),
        "decisions": [
            {
                "instrument": f"{item.instrument.mic}:{item.instrument.symbol}",
                "as_of": item.as_of.isoformat(),
                "action": item.action.value,
                "confidence": item.confidence.value,
            }
            for item in decisions
        ],
        "metrics": {item.name: canonical_decimal(item.value) for item in metrics},
    }
    return ExperimentRun(_digest(payload), spec, tuple(decisions), metrics)


def compare_experiments(left: ExperimentRun, right: ExperimentRun) -> ExperimentComparison:
    left_metrics = {item.name: item for item in left.metrics}
    right_metrics = {item.name: item for item in right.metrics}
    if left_metrics.keys() != right_metrics.keys():
        raise ValueError("experiment runs have incompatible metrics")
    deltas = tuple(
        ExperimentMetric(name, right_metrics[name].value - left_metrics[name].value, item.unit)
        for name, item in sorted(left_metrics.items())
    )
    return ExperimentComparison(left.run_id, right.run_id, deltas)


def _metrics(
    decisions: tuple[ReplayDecision, ...], returns: list[Decimal], drawdowns: list[Decimal]
) -> tuple[ExperimentMetric, ...]:
    determinate = [item for item in decisions if item.action is not DecisionAction.INDETERMINATE]
    changes = sum(
        current.action != prior.action
        for prior, current in pairwise(decisions)
        if prior.instrument == current.instrument
    )
    runs: list[int] = []
    length = 0
    prior_instrument: Instrument | None = None
    for item in decisions:
        if prior_instrument is not None and item.instrument != prior_instrument and length:
            runs.append(length)
            length = 0
        if item.action in {DecisionAction.BUY_CANDIDATE, DecisionAction.KEEP}:
            length += 1
        elif length:
            runs.append(length)
            length = 0
        prior_instrument = item.instrument
    if length:
        runs.append(length)
    with localcontext(CONTEXT):
        coverage = +(Decimal(len(determinate)) / Decimal(len(decisions)))
        average_holding = +(Decimal(sum(runs)) / Decimal(len(runs))) if runs else Decimal(0)
        forward = +(sum(returns, Decimal(0)) / Decimal(len(returns))) if returns else Decimal(0)
    return tuple(
        sorted(
            (
                ExperimentMetric("average_holding_period", average_holding, "observations"),
                ExperimentMetric("data_coverage", coverage, "ratio"),
                ExperimentMetric("decision_change_count", Decimal(changes), "count"),
                ExperimentMetric("decision_count", Decimal(len(decisions)), "count"),
                ExperimentMetric("forward_return", forward, "ratio"),
                ExperimentMetric("maximum_drawdown", min(drawdowns, default=Decimal(0)), "ratio"),
            ),
            key=lambda item: item.name,
        )
    )


def _validate_bars(bars: tuple[DailyBar, ...]) -> None:
    dates = tuple(item.trading_date for item in bars)
    if not bars or dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
        raise ValueError("experiment bars must have unique ascending dates")


def _spec_document(spec: ExperimentSpec) -> dict[str, object]:
    return {
        "policy": {
            "name": spec.policy_name,
            "version": spec.policy_version,
            "settings": dict(spec.policy_settings),
        },
        "window": {"start": spec.window.start.isoformat(), "end": spec.window.end.isoformat()},
        "datasets": dict(spec.datasets),
        "execution_costs": dict(spec.execution_costs),
    }


def _pairs(values: tuple[tuple[str, str], ...], name: str) -> None:
    keys = tuple(key for key, _ in values)
    if (
        keys != tuple(sorted(keys))
        or len(keys) != len(set(keys))
        or any(not key or not value for key, value in values)
    ):
        raise ValueError(f"experiment {name} must be unique sorted non-empty pairs")
