"""Offline experiment orchestration."""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from marketsieve import (
    BalancedMediumTermPolicy,
    ExperimentRun,
    ExperimentSpec,
    ReplayWindow,
    run_experiment,
)
from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument


class SnapshotRepository(Protocol):
    def verify(self, object_id: str) -> Any: ...

    def daily_bars(self, object_id: str) -> tuple[DailyBar, ...]: ...


class ExperimentRepository(Protocol):
    def put(self, run: ExperimentRun) -> dict[str, Any]: ...

    def show(self, run_id: str) -> dict[str, Any]: ...

    def compare(self, left: str, right: str) -> dict[str, Any]: ...


class ExperimentService:
    def __init__(self, snapshots: SnapshotRepository, runs: ExperimentRepository) -> None:
        self._snapshots = snapshots
        self._runs = runs

    def run(self, path: Path) -> dict[str, Any]:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        value = raw.get("experiment")
        if not isinstance(value, dict):
            raise ValueError("strategy TOML requires [experiment]")
        datasets = value.get("datasets")
        if not isinstance(datasets, dict) or not datasets:
            raise ValueError("strategy TOML requires [experiment.datasets]")
        policy = BalancedMediumTermPolicy()
        costs = value.get("execution_costs", {})
        if not isinstance(costs, dict):
            raise ValueError("experiment execution_costs must be a table")
        spec = ExperimentSpec(
            policy.name,
            policy.version,
            policy.settings,
            ReplayWindow(date.fromisoformat(value["start"]), date.fromisoformat(value["end"])),
            tuple(sorted((str(key), str(data_id)) for key, data_id in datasets.items())),
            tuple(sorted((str(key), str(amount)) for key, amount in costs.items())),
        )
        resolved = []
        for instrument_key, object_id in spec.datasets:
            stored = self._snapshots.verify(object_id)
            manifest = stored.manifest
            identity = manifest["instrument"]
            actual_key = f"{identity['mic']}:{identity['symbol']}"
            if manifest.get("kind") != "daily_bars" or actual_key != instrument_key:
                raise ValueError("experiment snapshot does not match its instrument")
            instrument = Instrument.create(
                symbol=identity["symbol"],
                mic=identity["mic"],
                currency=identity["currency"],
                exchange_timezone=identity["timezone"],
            )
            resolved.append((object_id, instrument, self._snapshots.daily_bars(object_id)))
        return self._runs.put(run_experiment(spec, policy, tuple(resolved)))

    def show(self, run_id: str) -> dict[str, Any]:
        return self._runs.show(run_id)

    def compare(self, left: str, right: str) -> dict[str, Any]:
        return self._runs.compare(left, right)
