from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from marketsieve.data.daily import Adjustment, DailyBar
from marketsieve.synthetic.daily import JP_INSTRUMENT, fixture_bars
from marketsieve_cli.adapters.experiments import ExperimentStore
from marketsieve_cli.adapters.snapshots import SnapshotStore
from marketsieve_cli.application.experiments import ExperimentService
from marketsieve_extension_api import AvailabilityBasis, ImportedDailyBars


def bars() -> tuple[DailyBar, ...]:
    return fixture_bars(
        JP_INSTRUMENT,
        tuple(str(100 + index // 5) for index in range(300)),
        dataset="experiment-cli-v1",
    )


def test_experiment_service_runs_stores_shows_and_compares_offline(tmp_path: Path) -> None:
    snapshots = SnapshotStore(tmp_path / "data")
    imported = ImportedDailyBars(
        "offline-jp",
        "fixture",
        "v1",
        "experiment-cli-v1",
        JP_INSTRUMENT,
        Adjustment.RAW,
        datetime(2026, 8, 1, tzinfo=UTC),
        AvailabilityBasis.RETRIEVAL,
        bars(),
        "a" * 64,
    )
    stored = snapshots.put_daily_bars(imported)
    history = bars()
    strategy = tmp_path / "strategy.toml"
    strategy.write_text(
        "[experiment]\n"
        f'start = "{history[199].trading_date.isoformat()}"\n'
        f'end = "{history[-1].trading_date.isoformat()}"\n'
        "[experiment.datasets]\n"
        f'"XTKS:7203" = "{stored.object_id}"\n',
        encoding="utf-8",
    )
    service = ExperimentService(snapshots, ExperimentStore(tmp_path / "experiments"))

    first = service.run(strategy)
    second = service.run(strategy)

    assert first == second
    assert service.show(first["run_id"]) == first
    comparison = service.compare(first["run_id"], second["run_id"])
    assert all(item["value"] == "0" for item in comparison["metric_deltas"].values())
    stored_document = json.loads(
        (tmp_path / "experiments" / "objects" / f"{first['run_id']}.json").read_text()
    )
    assert stored_document == first
    for name, value in (("experiment-run", first), ("experiment-comparison", comparison)):
        schema = json.loads(Path(f"schemas/{name}/v1/schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)

    object_path = tmp_path / "experiments" / "objects" / f"{first['run_id']}.json"
    object_path.write_bytes(object_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="conflicts"):
        service.run(strategy)


def test_experiment_store_rejects_modified_and_linked_artifacts(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "experiments")
    object_path = tmp_path / "experiments" / "objects" / ("a" * 64 + ".json")
    object_path.parent.mkdir(parents=True)
    object_path.write_text(
        json.dumps({"schema": "experiment-run/v1", "run_id": "a" * 64}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not canonical"):
        store.show("a" * 64)
    with pytest.raises(ValueError, match="run ID"):
        store.show("invalid")
    object_path.unlink()
    with pytest.raises(LookupError, match="not found"):
        store.show("a" * 64)

    linked_root = tmp_path / "linked-experiments"
    os.symlink(tmp_path / "experiments", linked_root)
    linked = ExperimentStore(linked_root)
    with pytest.raises(LookupError, match="directory does not exist"):
        linked.show("a" * 64)


def test_experiment_store_recomputes_all_derived_identity_fields(tmp_path: Path) -> None:
    snapshots = SnapshotStore(tmp_path / "data")
    imported = ImportedDailyBars(
        "offline-jp",
        "fixture",
        "v1",
        "experiment-cli-v1",
        JP_INSTRUMENT,
        Adjustment.RAW,
        datetime(2026, 8, 1, tzinfo=UTC),
        AvailabilityBasis.RETRIEVAL,
        bars(),
        "a" * 64,
    )
    stored = snapshots.put_daily_bars(imported)
    history = bars()
    strategy = tmp_path / "strategy.toml"
    strategy.write_text(
        "[experiment]\n"
        f'start = "{history[199].trading_date.isoformat()}"\n'
        f'end = "{history[-1].trading_date.isoformat()}"\n'
        "[experiment.datasets]\n"
        f'"XTKS:7203" = "{stored.object_id}"\n',
        encoding="utf-8",
    )
    store = ExperimentStore(tmp_path / "experiments")
    document = ExperimentService(snapshots, store).run(strategy)
    path = tmp_path / "experiments" / "objects" / f"{document['run_id']}.json"

    variants = []
    wrong_spec = {**document, "spec_id": "0" * 64}
    variants.append(wrong_spec)
    wrong_run = {**document, "run_id": "0" * 64}
    variants.append(wrong_run)
    wrong_profit = {**document, "profit_simulation": True}
    variants.append(wrong_profit)
    wrong_metrics = json.loads(json.dumps(document))
    wrong_metrics["metrics"]["data_coverage"]["unit"] = "count"
    variants.append(wrong_metrics)
    for variant in variants:
        path.write_text(
            json.dumps(variant, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="not canonical"):
            store.show(str(document["run_id"]))

    path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="not canonical"):
        store.show(str(document["run_id"]))


def test_experiment_store_requires_real_directories(tmp_path: Path) -> None:
    root_file = tmp_path / "experiments"
    root_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ValueError, match="root"):
        ExperimentStore(root_file)._ensure_directory()

    root_file.unlink()
    objects_file = root_file / "objects"
    root_file.mkdir()
    objects_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ValueError, match="object path"):
        ExperimentStore(root_file)._ensure_directory()
