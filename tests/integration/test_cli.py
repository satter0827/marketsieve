import json

import pytest
from click.testing import CliRunner

from marketsieve import __version__
from marketsieve_app.application.diagnostics import DiagnosticCheck, DiagnosticsService
from marketsieve_app.interfaces.cli import main


def test_version_reports_sdk_version() -> None:
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"marketsieve, version {__version__}\n"


def test_doctor_reports_ready() -> None:
    result = CliRunner().invoke(main, ["doctor"])

    assert result.exit_code == 0
    assert "[ok] MarketSieve SDK" in result.output
    assert result.output.endswith("Status: ready\n")


def test_doctor_can_emit_structured_logs_to_stderr() -> None:
    result = CliRunner().invoke(main, ["--log-level", "INFO", "doctor"])

    assert result.exit_code == 0
    payload = json.loads(result.stderr)
    assert payload["event_name"] == "diagnostics.completed"
    assert payload["attributes"] == {"check_count": 3, "succeeded": True}


def test_doctor_returns_failure_for_unsuccessful_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed_collect(_: DiagnosticsService) -> tuple[DiagnosticCheck, ...]:
        return (DiagnosticCheck(name="Python", detail="unsupported", passed=False),)

    monkeypatch.setattr(DiagnosticsService, "collect", failed_collect)
    result = CliRunner().invoke(main, ["doctor"])

    assert result.exit_code == 1
    assert result.output.endswith("Status: not ready\n")
