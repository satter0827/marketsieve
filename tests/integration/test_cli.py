import json
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator, FormatChecker

from marketsieve import __version__
from marketsieve.data.daily import DailyBarRequest, DailyBarSeries
from marketsieve.synthetic.daily import JP_BARS, SyntheticDailySource
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


def test_demo_json_is_schema_valid_reproducible_and_ordered() -> None:
    runner = CliRunner()
    first = runner.invoke(main, ["demo", "--format", "json"])
    second = runner.invoke(main, ["demo", "--format", "json"])

    assert first.exit_code == 0
    assert first.stdout == second.stdout
    document = json.loads(first.stdout)
    schema = json.loads(Path("schemas/demo-result/v1/schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    assert [item["market"] for item in document["results"]] == ["jp", "us"]
    assert [item["analysis"]["transition"] for item in document["results"]] == [
        "below_to_above",
        "above_to_below",
    ]
    assert all(len(item["evidence_id"]) == 64 for item in document["results"])


def test_demo_text_and_market_selection() -> None:
    all_markets = CliRunner().invoke(main, ["demo"])
    us_only = CliRunner().invoke(main, ["demo", "--market", "us"])

    assert all_markets.exit_code == 0
    assert all_markets.stdout.splitlines()[0].startswith("JP XTKS:7203")
    assert all_markets.stdout.splitlines()[1].startswith("US XNAS:MSFT")
    assert us_only.exit_code == 0
    assert us_only.stdout.startswith("US XNAS:MSFT")
    assert "JP " not in us_only.stdout


def test_demo_separates_results_and_logs() -> None:
    result = CliRunner().invoke(main, ["--log-level", "INFO", "demo", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["schema_version"] == "1.0.0"
    logs = [json.loads(line) for line in result.stderr.splitlines()]
    assert [item["event_name"] for item in logs] == ["demo.completed", "demo.completed"]


def test_demo_error_and_invalid_arguments_have_distinct_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(*_: object, **__: object) -> object:
        raise ValueError("invalid fixture")

    monkeypatch.setattr(SyntheticDailySource, "load", fail_load)
    failed = CliRunner().invoke(main, ["--log-level", "ERROR", "demo"])
    invalid = CliRunner().invoke(main, ["demo", "--market", "invalid"])

    assert failed.exit_code == 1
    assert failed.stdout == ""
    assert json.loads(failed.stderr)["event_name"] == "demo.failed"
    assert invalid.exit_code == 2


def test_demo_treats_insufficient_history_as_a_successful_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def short_load(
        _: SyntheticDailySource, request: DailyBarRequest, *, as_of: datetime
    ) -> DailyBarSeries:
        return DailyBarSeries(request, JP_BARS[:19], as_of, 2)

    monkeypatch.setattr(SyntheticDailySource, "load", short_load)
    result = CliRunner().invoke(main, ["demo", "--market", "jp", "--format", "json"])

    assert result.exit_code == 0
    analysis = json.loads(result.stdout)["results"][0]["analysis"]
    assert analysis["status"] == "insufficient_history"
    assert analysis["transition"] is None
