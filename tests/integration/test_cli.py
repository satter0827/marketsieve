import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator, FormatChecker

from marketsieve import __version__
from marketsieve.data.daily import DailyBarRequest, DailyBarSeries
from marketsieve.synthetic.daily import JP_BARS, SyntheticDailySource
from marketsieve_cli.application.diagnostics import DiagnosticCheck, DiagnosticsService
from marketsieve_cli.interfaces.cli import entrypoint, main

SCHEMAS = Path("schemas")


def validate(name: str, document: object, major: int = 1) -> None:
    schema = json.loads((SCHEMAS / name / f"v{major}" / "schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def test_landing_and_version_are_immediately_useful() -> None:
    runner = CliRunner()
    landing = runner.invoke(main, [])
    version = runner.invoke(main, ["--version"])

    assert landing.exit_code == 0
    assert "Reproducible Japanese and U.S. equity analysis" in landing.stdout
    assert "marketsieve report --market all" in landing.stdout
    assert version.output == f"marketsieve, version {__version__}\n"


def test_doctor_supports_text_and_schema_valid_json() -> None:
    runner = CliRunner()
    text_result = runner.invoke(main, ["doctor", "--output", "text"])
    json_result = runner.invoke(main, ["doctor", "--output", "json"])

    assert text_result.exit_code == 0
    assert "PASS MarketSieve SDK" in text_result.stdout
    assert text_result.stdout.endswith("STATUS Ready\n")
    document = json.loads(json_result.stdout)
    validate("doctor-result", document)
    assert document["status"] == "ready"


def test_doctor_reports_recovery_without_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed_collect(_: DiagnosticsService) -> tuple[DiagnosticCheck, ...]:
        return (DiagnosticCheck("Python", "unsupported", False, "Use Python 3.13."),)

    monkeypatch.setattr(DiagnosticsService, "collect", failed_collect)
    result = CliRunner().invoke(main, ["doctor", "--output", "text"])

    assert result.exit_code == 1
    assert "ACTION Use Python 3.13." in result.stdout
    assert "Traceback" not in result.output


def test_report_json_is_schema_valid_reproducible_and_ordered() -> None:
    runner = CliRunner()
    first = runner.invoke(main, ["report", "--output", "json"])
    second = runner.invoke(main, ["report", "--output", "json"])

    assert first.exit_code == 0
    assert first.stdout == second.stdout
    document = json.loads(first.stdout)
    validate("report-result", document)
    assert [item["market"] for item in document["reports"]] == ["jp", "us"]
    assert [item["transitions"][0]["current_state"] for item in document["reports"]] == [
        "above",
        "below",
    ]


def test_report_text_market_selection_and_notice() -> None:
    result = CliRunner().invoke(main, ["report", "--market", "us", "--output", "text"])

    assert result.exit_code == 0
    assert result.stdout.startswith("US XNAS:MSFT")
    assert "JP " not in result.stdout
    assert result.stdout.endswith(
        "NOTICE Observed market-data conditions; not investment advice.\n"
    )


def test_report_rich_is_readable_without_relying_on_color() -> None:
    result = CliRunner(env={"NO_COLOR": "1"}).invoke(
        main, ["report", "--market", "jp", "--output", "rich"], color=True
    )

    assert result.exit_code == 0
    assert "MarketSieve Report" in result.stdout
    assert "XTKS:7203" in result.stdout
    assert "below → above" in result.stdout
    assert "not investment advice" in result.stdout


def test_capabilities_match_click_commands_and_validate_schema() -> None:
    result = CliRunner().invoke(main, ["capabilities", "--output", "json"])

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    validate("capabilities-result", document)
    assert [item["name"] for item in document["commands"]] == sorted(main.commands)
    report = next(item for item in document["commands"] if item["name"] == "report")
    assert {option["name"] for option in report["options"]} == {"market", "output_mode"}
    assert {option["name"] for option in document["global_options"]} == {
        "log_file",
        "log_level",
    }
    assert report["effects"] == {
        "network": False,
        "optional_writes": ["log_file"],
        "secrets": False,
    }


def test_structured_logs_are_opt_in_and_separate() -> None:
    quiet = CliRunner().invoke(main, ["report", "--output", "json"])
    logged = CliRunner().invoke(
        main, ["--log-level", "INFO", "report", "--market", "jp", "--output", "json"]
    )

    assert quiet.stderr == ""
    assert json.loads(logged.stdout)["schema_version"] == "1.0.0"
    assert json.loads(logged.stderr)["event_name"] == "report.completed"


def test_report_errors_are_machine_readable_and_usage_is_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(*_: object, **__: object) -> object:
        raise ValueError("invalid fixture")

    monkeypatch.setattr(SyntheticDailySource, "load", fail_load)
    failed = CliRunner().invoke(main, ["report", "--output", "json"])
    invalid = CliRunner().invoke(main, ["report", "--market", "invalid"])

    assert failed.exit_code == 1
    assert failed.stdout == ""
    error = json.loads(failed.stderr)
    validate("cli-error", error)
    assert error["error"] == "report_failed"
    assert invalid.exit_code == 2


def test_entrypoint_renders_json_usage_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["marketsieve", "report", "--market", "invalid", "--output", "json"],
    )

    with pytest.raises(SystemExit, match="2"):
        entrypoint()

    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    validate("cli-error", error)
    assert error["error"] == "invalid_cli_usage"


def test_report_treats_insufficient_history_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def short_load(
        _: SyntheticDailySource, request: DailyBarRequest, *, as_of: datetime
    ) -> DailyBarSeries:
        bars = tuple(bar for bar in JP_BARS[:19] if bar.available_at <= as_of)
        return DailyBarSeries(request, bars, as_of, 21 - len(bars))

    monkeypatch.setattr(SyntheticDailySource, "load", short_load)
    result = CliRunner().invoke(main, ["report", "--market", "jp", "--output", "json"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)["reports"][0]
    assert report["latest"]["status"] == "insufficient_history"
    assert report["transitions"] == []
