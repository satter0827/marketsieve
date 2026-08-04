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
