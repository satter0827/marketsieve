from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import scripts.release_qualification as qualification
from jsonschema import Draft202012Validator
from scripts.release_qualification import (
    SCHEMA_PATH,
    guard_promotion,
    normalized_lock,
    normalized_pyproject,
    preview_object,
    qualify,
    validate_consecutive_sessions,
    validate_recovery,
    validate_snapshot,
)


def _snapshot(*, market: str = "jp", mode: str = "current") -> dict[str, Any]:
    indices = ["nikkei225", "topix500"] if market == "jp" else ["dow30", "nasdaq100", "sp500"]
    return {
        "schema": "market-snapshot/v9",
        "request": {
            "inputs": {
                "indices": indices,
                "evidence": ["benchmarks", "company", "financials", "price"],
                "mode": mode,
                "session": "close",
            },
            "producer": {"version": "1.0.0rc3"},
        },
        "price_coverage_gate_passed": True,
        "market": {"markets": {market: {"latest_price_date": "2026-08-07"}}},
    }


def test_qualification_requires_three_consecutive_exchange_sessions() -> None:
    sessions = ("2026-08-05", "2026-08-06", "2026-08-07")
    validate_consecutive_sessions("jp", sessions)
    validate_consecutive_sessions("us", sessions)

    with pytest.raises(ValueError, match="three unique ordered"):
        validate_consecutive_sessions("jp", (sessions[0], sessions[0], sessions[2]))
    with pytest.raises(ValueError, match="not three consecutive"):
        validate_consecutive_sessions("us", ("2026-08-04", "2026-08-06", "2026-08-07"))


def test_qualification_rejects_reconstruction_version_and_quality_drift() -> None:
    assert validate_snapshot(_snapshot(), market="jp", version="1.0.0rc3") == "2026-08-07"

    reconstructed = _snapshot(mode="historical_price_reconstruction")
    with pytest.raises(ValueError, match="actual current close"):
        validate_snapshot(reconstructed, market="jp", version="1.0.0rc3")

    wrong_version = _snapshot()
    wrong_version["request"]["producer"]["version"] = "1.0.0rc2"
    with pytest.raises(ValueError, match="producer"):
        validate_snapshot(wrong_version, market="jp", version="1.0.0rc3")

    failed_quality = _snapshot()
    failed_quality["price_coverage_gate_passed"] = False
    with pytest.raises(ValueError, match="coverage gate"):
        validate_snapshot(failed_quality, market="jp", version="1.0.0rc3")


def test_qualification_requires_exact_resume_and_retained_publication() -> None:
    cancelled = {
        "command": "market capture",
        "status": "cancelled",
        "exit_code": 130,
        "resume_run_id": "0123456789abcdef",
        "input_fingerprint": "same",
    }
    resumed = {
        "command": "market build",
        "status": "completed",
        "exit_code": 0,
        "input_fingerprint": "same",
        "published_object_ids": ["a" * 64],
    }
    validate_recovery(cancelled, resumed)

    resumed["input_fingerprint"] = "changed"
    with pytest.raises(ValueError, match="input fingerprint"):
        validate_recovery(cancelled, resumed)


def test_qualification_schema_and_promotion_normalization_are_stable() -> None:
    report = {
        "schema": "release-qualification/v1",
        "status": "ready",
        "version": "1.0.0rc3",
        "commit": "a" * 40,
        "tag": "v1.0.0rc3",
        "release_manifest_sha256": "b" * 64,
        "snapshots": {"jp": ["a" * 64, "b" * 64, "c" * 64], "us": ["d" * 64, "e" * 64, "f" * 64]},
        "research": ["1" * 64, "2" * 64],
        "operations": {
            "cancelled_market": "00000000-0000-0000-0000-000000000001",
            "resumed_market": "00000000-0000-0000-0000-000000000002",
            "cancelled_research": "00000000-0000-0000-0000-000000000003",
        },
    }
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).validate(report)

    rc = (
        'version = "1.0.0rc3"\n'
        'dependencies = ["marketsieve==1.0.0rc3"]\n'
        '"Development Status :: 4 - Beta"\n'
    )
    stable = (
        'version = "1.0.0"\n'
        'dependencies = ["marketsieve==1.0.0"]\n'
        '"Development Status :: 5 - Production/Stable"\n'
    )
    assert normalized_pyproject(rc) == normalized_pyproject(stable)


def test_promotion_lock_normalization_changes_only_suite_versions() -> None:
    rc = """version = 1
[[package]]
name = "marketsieve"
version = "1.0.0rc3"
[[package]]
name = "example"
version = "2.0.0"
"""
    stable = rc.replace('version = "1.0.0rc3"', 'version = "1.0.0"')
    changed_dependency = stable.replace('version = "2.0.0"', 'version = "2.0.1"')

    assert normalized_lock(rc) == normalized_lock(stable)
    assert normalized_lock(rc) != normalized_lock(changed_dependency)


def test_preview_reads_every_registered_file_over_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_path = tmp_path / "object"
    object_path.mkdir()
    (object_path / "manifest.json").write_text(
        json.dumps(
            {"artifacts": {"explorer.html": {}, "explorer-data.json": {}}},
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (object_path / "explorer.html").write_text("<html>ready</html>", encoding="utf-8")
    (object_path / "explorer-data.json").write_text("{}", encoding="utf-8")

    class Server:
        def __init__(self, path: Path) -> None:
            assert path == object_path

        def start(self) -> str:
            return "http://127.0.0.1:1234/explorer.html"

        def close(self) -> None:
            pass

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        def read(self) -> bytes:
            return b"content"

    requested: list[str] = []
    monkeypatch.setattr(qualification, "ObjectPreviewServer", Server)

    def open_registered(url: str, timeout: int) -> Response:
        assert timeout == 5
        requested.append(url)
        return Response()

    monkeypatch.setattr(
        qualification,
        "urlopen",
        open_registered,
    )

    preview_object(object_path)

    assert requested == [
        "http://127.0.0.1:1234/manifest.json",
        "http://127.0.0.1:1234/explorer-data.json",
        "http://127.0.0.1:1234/explorer.html",
    ]


def test_qualification_writes_canonical_report_from_explicit_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = "a" * 40
    snapshot_ids = tuple(character * 64 for character in "abcdef")
    research_ids = ("1" * 64, "2" * 64)
    run_ids = (
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    )
    snapshots = {
        object_id: {
            **_snapshot(market="jp" if index < 3 else "us"),
            "market": {
                "markets": {
                    "jp" if index < 3 else "us": {
                        "latest_price_date": ("2026-08-05", "2026-08-06", "2026-08-07")[index % 3]
                    }
                }
            },
        }
        for index, object_id in enumerate(snapshot_ids)
    }
    research = {
        research_ids[0]: {
            "snapshot_id": snapshot_ids[2],
            "price_coverage_gate_passed": True,
        },
        research_ids[1]: {
            "snapshot_id": snapshot_ids[5],
            "price_coverage_gate_passed": True,
        },
        "3" * 64: {"snapshot_id": snapshot_ids[5], "price_coverage_gate_passed": True},
    }
    operations = {
        run_ids[0]: {
            "command": "market capture",
            "status": "cancelled",
            "exit_code": 130,
            "resume_run_id": "0123456789abcdef",
            "input_fingerprint": "same",
        },
        run_ids[1]: {
            "command": "market build",
            "status": "completed",
            "exit_code": 0,
            "input_fingerprint": "same",
            "published_object_ids": [snapshot_ids[5]],
        },
        run_ids[2]: {
            "command": "research build",
            "status": "cancelled",
            "exit_code": 130,
            "published_object_ids": ["3" * 64],
        },
    }

    class SnapshotStore:
        def __init__(self, _root: Path) -> None:
            pass

        def show(self, object_id: str) -> dict[str, Any]:
            return snapshots[object_id]

        @staticmethod
        def _verify_object(_path: Path, _object_id: str) -> None:
            pass

    class FakeResearchStore:
        def __init__(self, _root: Path) -> None:
            pass

        def show(self, object_id: str) -> dict[str, Any]:
            return research[object_id]

        @staticmethod
        def _verify(_path: Path, _object_id: str) -> None:
            pass

    class FakeOperationStore:
        def __init__(self, _root: Path) -> None:
            pass

        def show(self, run_id: str) -> dict[str, Any]:
            return operations[run_id]

    class Inventory:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def doctor(self) -> dict[str, Any]:
            return {"counts": {"corrupt": 0, "orphan": 0}}

    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "release.json").write_text(
        json.dumps({"version": "1.0.0rc3", "commit": commit}), encoding="utf-8"
    )
    monkeypatch.setattr(qualification, "MarketSnapshotStore", SnapshotStore)
    monkeypatch.setattr(qualification, "ResearchStore", FakeResearchStore)
    monkeypatch.setattr(qualification, "OperationRunStore", FakeOperationStore)
    monkeypatch.setattr(qualification, "ArtifactInventory", Inventory)
    monkeypatch.setattr(qualification, "preview_object", lambda _path: None)
    monkeypatch.setattr(qualification, "verify_release", lambda *_args: None)
    monkeypatch.setattr(qualification, "capture", lambda *_args: commit)
    output = tmp_path / "qualification"
    args = argparse.Namespace(
        version="1.0.0rc3",
        commit=commit,
        tag="v1.0.0rc3",
        release_dir=release_dir,
        state_root=tmp_path / "state",
        jp_snapshot=snapshot_ids[:3],
        us_snapshot=snapshot_ids[3:],
        jp_research=research_ids[0],
        us_research=research_ids[1],
        cancelled_market_run=run_ids[0],
        resumed_market_run=run_ids[1],
        cancelled_research_run=run_ids[2],
        output_dir=output,
    )

    report = qualify(args)

    assert report["status"] == "ready"
    assert json.loads((output / "qualification.json").read_text()) == report
    assert "MarketSieve Release Qualification" in (output / "summary.md").read_text()


def test_promotion_guard_rejects_files_outside_release_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        qualification,
        "load_package_catalog",
        lambda: (SimpleNamespace(distribution="marketsieve", project_version="1.0.0"),),
    )

    def allowed(*command: str) -> str:
        return "CHANGELOG.md" if command[1:3] == ("diff", "--name-only") else ""

    monkeypatch.setattr(qualification, "capture", allowed)
    assert guard_promotion("v1.0.0rc3", "HEAD")["files"] == ["CHANGELOG.md"]

    monkeypatch.setattr(
        qualification,
        "capture",
        lambda *command: (
            "packages/cli/src/change.py" if command[1:3] == ("diff", "--name-only") else ""
        ),
    )
    with pytest.raises(ValueError, match="frozen files"):
        guard_promotion("v1.0.0rc3", "HEAD")
