from pathlib import Path

import pytest
from scripts.secret_gate import _scan_added_lines, scan_history, scan_paths


def write(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def test_secret_scan_accepts_empty_documented_environment(tmp_path: Path) -> None:
    path = write(tmp_path / ".env.example", "OPENAI_API_KEY=\n")

    assert scan_paths((path,)) == []


def test_secret_scan_reports_location_without_value(tmp_path: Path) -> None:
    value = "sk-" + "A" * 24
    path = write(tmp_path / "settings.txt", f"OPENAI_API_KEY={value}\n")

    findings = scan_paths((path,))

    assert {finding.kind for finding in findings} == {"credential_assignment", "openai_key"}
    assert all(value not in repr(finding) for finding in findings)


def test_secret_scan_rejects_sensitive_tracked_path(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", "SAFE=placeholder\n")

    assert [finding.kind for finding in scan_paths((path,))] == ["sensitive_path"]


def test_patch_scan_ignores_removed_credentials() -> None:
    value = "sk-" + "A" * 24
    patch = f"--- a/settings\n+++ b/settings\n-{value}\n+safe\n".encode()

    assert _scan_added_lines("change", patch) == []


def test_history_scan_checks_each_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    value = "sk-" + "A" * 24
    responses = iter(
        (
            b"first\nsecond\n",
            f"+OPENAI_API_KEY={value}\n".encode(),
            b"-OPENAI_API_KEY=removed\n",
        )
    )
    monkeypatch.setattr("scripts.secret_gate._capture", lambda _command: next(responses))

    findings = scan_history("base")

    assert [(finding.path, finding.kind) for finding in findings] == [
        ("git-commit:first", "credential_assignment"),
        ("git-commit:first", "openai_key"),
    ]
