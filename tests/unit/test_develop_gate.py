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
    monkeypatch.setattr(develop_gate, "check_smoke", lambda _path: events.append("smoke"))
    monkeypatch.setattr(develop_gate, "check_package", lambda _path: events.append("package"))

    develop_gate.check_all()

    assert events == [
        "reset",
        "secrets",
        "quality",
        "tests",
        "schemas",
        "smoke",
        "package",
        "secrets",
    ]


def test_test_gate_runs_once_and_enforces_coverage_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[tuple[str, ...]] = []
    state_root = tmp_path / "state"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    monkeypatch.setattr(develop_gate, "STATE_ROOT", state_root)
    monkeypatch.setattr(develop_gate, "run", commands.append)

    develop_gate.check_tests(evidence)

    assert commands == [
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
            f"--fail-under={develop_gate.MINIMUM_COVERAGE_PERCENT}",
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
