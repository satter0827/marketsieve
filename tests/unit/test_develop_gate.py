import json
from pathlib import Path

import pytest
from scripts import develop_gate


def test_secret_check_uses_configured_base(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setenv("BASE_SHA", "base-commit")
    monkeypatch.setattr(develop_gate, "run", commands.append)

    develop_gate.check_secrets(tmp_path)

    assert commands == [
        (
            "uv",
            "run",
            "python",
            "scripts/secret_gate.py",
            "--base",
            "base-commit",
            "--path",
            str(tmp_path),
        )
    ]


def test_secret_check_does_not_guess_a_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.delenv("BASE_SHA", raising=False)
    monkeypatch.setattr(develop_gate, "run", commands.append)

    develop_gate.check_secrets(tmp_path)

    assert commands == [
        (
            "uv",
            "run",
            "python",
            "scripts/secret_gate.py",
            "--path",
            str(tmp_path),
        )
    ]


def test_complete_gate_scans_before_and_after_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    monkeypatch.setattr(develop_gate, "evidence_dir", lambda: tmp_path)
    monkeypatch.setattr(develop_gate, "reset_evidence", lambda _path: events.append("reset"))
    monkeypatch.setattr(develop_gate, "check_secrets", lambda _path: events.append("secrets"))
    monkeypatch.setattr(develop_gate, "check_quality", lambda: events.append("quality"))
    monkeypatch.setattr(develop_gate, "check_tests", lambda _path: events.append("tests"))
    monkeypatch.setattr(develop_gate, "validate_schemas", lambda: events.append("schemas"))
    monkeypatch.setattr(
        develop_gate, "check_smoke", lambda _path, jobs: events.append(f"smoke:{jobs}")
    )
    monkeypatch.setattr(
        develop_gate, "check_package", lambda _path, jobs: events.append(f"package:{jobs}")
    )
    monkeypatch.setattr(develop_gate, "_write_timings", lambda *_: events.append("timings"))

    develop_gate.check_all(1)

    assert events == [
        "reset",
        "secrets",
        "quality",
        "schemas",
        "tests",
        "package:1",
        "smoke:1",
        "timings",
        "secrets",
    ]


def test_parallel_gate_keeps_nested_subprocess_groups_serial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nested_jobs: list[int] = []
    monkeypatch.setattr(develop_gate, "evidence_dir", lambda: tmp_path)
    monkeypatch.setattr(develop_gate, "reset_evidence", lambda _: None)
    monkeypatch.setattr(develop_gate, "check_secrets", lambda _: None)
    monkeypatch.setattr(develop_gate, "check_quality_and_schemas", lambda: None)
    monkeypatch.setattr(develop_gate, "check_tests", lambda _: None)
    monkeypatch.setattr(develop_gate, "check_package", lambda _path, jobs: nested_jobs.append(jobs))
    monkeypatch.setattr(develop_gate, "check_smoke", lambda _path, jobs: nested_jobs.append(jobs))
    monkeypatch.setattr(develop_gate, "_write_timings", lambda *_: None)

    develop_gate.check_all(4)

    assert nested_jobs == [1, 1]


def test_test_gate_runs_once_and_enforces_coverage_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[tuple[str, ...]] = []
    state_root = tmp_path / "state"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    monkeypatch.setattr(develop_gate, "STATE_ROOT", state_root)

    def run(command: tuple[str, ...]) -> None:
        commands.append(command)
        if command[2:4] == ("coverage", "json"):
            (evidence / "coverage.json").write_text(
                json.dumps(
                    {
                        "totals": {
                            "covered_lines": 90,
                            "num_statements": 100,
                            "covered_branches": 80,
                            "num_branches": 100,
                        },
                        "files": {},
                    }
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr(develop_gate, "run", run)
    monkeypatch.setattr(develop_gate, "head_sha", lambda: "a" * 40)

    develop_gate.check_tests(evidence)

    assert commands == [
        ("uv", "run", "coverage", "erase"),
        (
            "uv",
            "run",
            "coverage",
            "run",
            "-m",
            "pytest",
            f"--junitxml={evidence / 'junit.xml'}",
        ),
        (
            "uv",
            "run",
            "coverage",
            "report",
            "--fail-under=0",
        ),
        (
            "uv",
            "run",
            "coverage",
            "json",
            "-o",
            str(evidence / "coverage.json"),
        ),
    ]


def test_coverage_thresholds_are_independent() -> None:
    metrics = {
        "statement_percent": 90.0,
        "branch_percent": 70.0,
        "critical": {"application/market.py": 79.0},
    }

    with pytest.raises(RuntimeError, match=r"branch coverage.*critical module"):
        develop_gate.validate_coverage(metrics)
