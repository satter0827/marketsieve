from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import StringIO
from pathlib import Path

import pytest

from marketsieve.fields import FieldDefinition, field_definitions
from marketsieve.indicators import IndicatorResult, IndicatorSpec, calculate
from marketsieve.model import DailyBar, Instrument
from marketsieve_cli.adapters.artifacts import ArtifactInventory
from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.adapters.operations import OperationRunStore
from marketsieve_cli.application.acquisition_errors import MarketSnapshotRunInterrupted
from marketsieve_cli.schema_registry import validate_document
from marketsieve_extension_api import (
    AcquisitionProgress,
    AcquisitionProgressState,
    MarketIndicatorKind,
    MarketIndicatorSpec,
)


def _manifest(path: Path, schema: str, object_id: str) -> None:
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": schema,
                "snapshot_id": object_id,
                "created_at": "2026-08-09T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )


def _reject_object(_path: Path, _object_id: str) -> None:
    raise ValueError("projection_invalid")


def test_artifact_inventory_isolates_legacy_corrupt_and_orphan(tmp_path: Path) -> None:
    objects = tmp_path / "market-snapshots" / "objects"
    _manifest(objects / ("a" * 64), "market-snapshot-manifest/v9", "a" * 64)
    _manifest(objects / ("b" * 64), "market-snapshot-manifest/v7", "b" * 64)
    (objects / ("c" * 64)).mkdir()
    (objects / ".DS_Store").write_text("ignored", encoding="utf-8")
    latest = tmp_path / "market-snapshots" / "latest.json"
    latest.write_text(json.dumps({"snapshot_id": "d" * 64}), encoding="utf-8")

    document = ArtifactInventory(tmp_path).list(object_type="snapshot")

    assert document["counts"] == {
        "current": 1,
        "incompatible": 1,
        "corrupt": 1,
        "orphan": 1,
    }
    assert ArtifactInventory(tmp_path).doctor()["status"] == "degraded"


def test_artifact_inventory_validates_filters_and_invalid_metadata(tmp_path: Path) -> None:
    inventory = ArtifactInventory(tmp_path)
    assert inventory.doctor()["status"] == "healthy"
    with pytest.raises(ValueError, match="artifact type"):
        inventory.list(object_type="portfolio")
    with pytest.raises(ValueError, match="artifact status"):
        inventory.list(status="deleted")

    objects = tmp_path / "research" / "objects"
    _manifest(objects / ("a" * 64), "security-research-manifest/v9", "a" * 64)
    (objects / ("b" * 64)).mkdir()
    (objects / ("b" * 64) / "manifest.json").write_text("[]", encoding="utf-8")
    (objects / ("c" * 64)).mkdir()
    (objects / ("c" * 64) / "manifest.json").write_text(
        json.dumps({"schema": 7, "created_at": None}), encoding="utf-8"
    )
    latest = tmp_path / "research" / "latest.json"
    latest.write_text("not-json", encoding="utf-8")

    current = inventory.list(object_type="research", status="current")
    assert current["counts"]["current"] == 1
    assert len(current["artifacts"]) == 1
    assert inventory.list(status="corrupt")["counts"]["corrupt"] == 2
    assert inventory.list(status="orphan")["counts"]["orphan"] == 1


def test_artifact_inventory_uses_object_validator_without_failing_the_list(
    tmp_path: Path,
) -> None:
    objects = tmp_path / "market-snapshots" / "objects"
    object_id = "a" * 64
    _manifest(objects / object_id, "market-snapshot-manifest/v9", object_id)
    inventory = ArtifactInventory(
        tmp_path,
        validators={"snapshot": _reject_object},
    )

    document = inventory.list(object_type="snapshot")

    assert document["counts"]["corrupt"] == 1
    assert document["counts"]["current"] == 0
    assert document["artifacts"][0]["reason"] == "projection_invalid"


def test_non_tty_auto_output_is_untranslated_json() -> None:
    stdout, stderr = StringIO(), StringIO()
    console = ConsoleOutput(OutputMode.AUTO, stdout=stdout, stderr=stderr, locale="ja")

    console.emit_document({"status": "available", "price": 1}, title="test")

    assert console.mode is OutputMode.JSON
    assert json.loads(stdout.getvalue()) == {"status": "available", "price": 1}


def test_operation_runs_persist_success_failure_and_dry_run_prune(tmp_path: Path) -> None:
    store = OperationRunStore(tmp_path)
    with store.track("market build", {"scope": "all"}) as context:
        context.publish("a" * 64)
        context.set_metrics(acquired_count=10, coverage=None)
    completed = store.list()["runs"][0]
    assert completed["status"] == "completed"
    assert completed["published_object_ids"] == ["a" * 64]
    assert store.events(completed["run_id"])["events"][-1]["code"] == "completed"
    assert store.prune((completed["run_id"],))["dry_run"] is True
    assert store.show(completed["run_id"])["status"] == "completed"
    validate_document(completed)
    for event in store.events(completed["run_id"])["events"]:
        validate_document(event)

    with pytest.raises(RuntimeError), store.track("research build", {"security": "XNAS:FAIL"}):
        raise RuntimeError("failed")
    assert store.list(status="failed")["runs"][0]["status"] == "failed"


def test_operation_run_records_monotonic_progress_retry_and_heartbeat(tmp_path: Path) -> None:
    observed: list[str] = []
    store = OperationRunStore(tmp_path, heartbeat_interval_seconds=0.01)
    with store.track(
        "market build",
        {"scope": "all"},
        observer=lambda code, _progress, _elapsed: observed.append(code),
    ) as context:
        context(AcquisitionProgress("price", AcquisitionProgressState.STARTED, 0, 10, 0))
        context(AcquisitionProgress("price", AcquisitionProgressState.RUNNING, 2, 10, 1))
        context(
            AcquisitionProgress(
                "price",
                AcquisitionProgressState.RETRYING,
                2,
                10,
                1,
                attempt=2,
                max_attempts=3,
                retry_after_seconds=15,
            )
        )
        time.sleep(0.03)
        context(AcquisitionProgress("price", AcquisitionProgressState.COMPLETED, 10, 10, 1))

    run = store.list()["runs"][0]
    events = store.events(run["run_id"])["events"]
    assert run["current_progress"]["completed"] == 10
    assert {item["code"] for item in events} >= {"progress", "retry", "heartbeat"}
    assert "heartbeat" in observed


def test_operation_context_is_thread_safe_and_retains_publications_on_cancel(
    tmp_path: Path,
) -> None:
    store = OperationRunStore(tmp_path)
    with pytest.raises(KeyboardInterrupt), store.track("research build", {}) as context:
        with ThreadPoolExecutor(max_workers=4) as executor:
            tuple(executor.map(context.publish, (f"research-{index}" for index in range(20))))
        raise KeyboardInterrupt

    cancelled = store.list(status="cancelled")["runs"][0]
    assert cancelled["exit_code"] == 130
    assert len(cancelled["published_object_ids"]) == 20
    assert store.events(cancelled["run_id"])["events"][-1]["code"] == "cancelled"


def test_operation_v2_list_excludes_legacy_v1_runs(tmp_path: Path) -> None:
    store = OperationRunStore(tmp_path)
    legacy = store.root / "00000000-0000-0000-0000-000000000001"
    legacy.mkdir(parents=True)
    store._write(
        legacy / "run.json",
        {
            "schema": "operation-run/v1",
            "run_id": legacy.name,
            "started_at": "2026-08-09T00:00:00+00:00",
            "status": "completed",
        },
    )

    assert store.list()["schema"] == "operation-run-list/v2"
    assert store.list()["runs"] == []
    assert store.show(legacy.name)["schema"] == "operation-run/v1"


def test_operation_run_carries_a_snapshot_acquisition_resume_run_id(tmp_path: Path) -> None:
    store = OperationRunStore(tmp_path)
    error = MarketSnapshotRunInterrupted("0123456789abcdef", RuntimeError("provider unavailable"))

    with pytest.raises(MarketSnapshotRunInterrupted), store.track("market build", {"scope": "jp"}):
        raise error

    failed = store.list(status="failed")["runs"][0]
    assert failed["resumable"] is True
    assert failed["resume_run_id"] == "0123456789abcdef"


def test_operation_run_filters_events_validation_and_apply_prune(tmp_path: Path) -> None:
    store = OperationRunStore(tmp_path)
    with store.track("market build", {"scope": "jp"}):
        pass
    run = store.list(command="market build")["runs"][0]
    assert store.list(command="research build")["runs"] == []
    assert store.events(run["run_id"], level="ERROR")["events"] == []
    assert store.prune(before=date(2999, 1, 1))["run_ids"] == [run["run_id"]]
    assert store.prune((run["run_id"],), apply=True)["dry_run"] is False
    assert store.list()["runs"] == []
    with pytest.raises(LookupError):
        store.show("not-a-run")

    missing_events = store.root / "00000000-0000-0000-0000-000000000000"
    missing_events.mkdir(parents=True)
    assert store._read_jsonl(missing_events / "events.jsonl") == []


def test_public_sdk_and_market_indicator_units_are_explicit() -> None:
    instrument = Instrument.create(
        symbol="MSFT", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
    )
    indicator = IndicatorSpec.create("sma", period=20)
    assert instrument.symbol == "MSFT"
    assert indicator.parameter("period") == 20
    assert DailyBar.__module__ == "marketsieve.model"
    assert IndicatorResult.__module__ == "marketsieve.indicators"
    assert callable(calculate)
    definitions = field_definitions()
    assert definitions and isinstance(definitions[0], FieldDefinition)
    spec = MarketIndicatorSpec(
        "usd_jpy", "JPY=X", "USD/JPY", MarketIndicatorKind.FX_RATE, "JPY_per_USD"
    )
    assert spec.kind is MarketIndicatorKind.FX_RATE
    assert spec.unit == "JPY_per_USD"
