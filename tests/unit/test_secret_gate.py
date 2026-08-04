from pathlib import Path

from scripts.secret_gate import scan_paths


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
