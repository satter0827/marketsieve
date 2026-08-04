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


def write_csv_bundle(path: Path) -> Path:
    path.mkdir()
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "marketsieve-csv-daily-bars/v1",
                "source_profile": "offline-jp",
                "source": "csv",
                "source_version": "fixture-1",
                "retrieved_at": "2026-08-01T12:00:00+00:00",
                "instrument": {
                    "symbol": "7203",
                    "mic": "XTKS",
                    "currency": "JPY",
                    "timezone": "Asia/Tokyo",
                },
                "dataset": {
                    "name": "example-bars",
                    "file": "daily-bars.csv",
                    "adjustment": "raw",
                    "availability_basis": "published",
                },
            }
        ),
        encoding="utf-8",
    )
    (path / "daily-bars.csv").write_text(
        "trading_date,open,high,low,close,volume,published_at\n"
        "2026-07-30,100,110,90,105,1000,2026-07-30T06:00:00+00:00\n"
        "2026-07-31,105,115,101,112,1200,2026-07-31T06:00:00+00:00\n",
        encoding="utf-8",
    )
    return path


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
    assert [item["name"] for item in document["commands"]] == [
        "capabilities",
        "doctor",
        "inspect",
        "report",
        "snapshot list",
        "snapshot show",
        "snapshot verify",
        "source import",
        "source list",
    ]
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


def test_csv_import_snapshot_and_price_inspect_are_one_offline_path(tmp_path: Path) -> None:
    runner = CliRunner()
    bundle = write_csv_bundle(tmp_path / "bundle")
    with runner.isolated_filesystem():
        sources = runner.invoke(main, ["source", "list", "--output", "json"])
        imported = runner.invoke(main, ["source", "import", str(bundle), "--output", "json"])
        import_document = json.loads(imported.stdout)
        object_id = import_document["object_id"]
        listed = runner.invoke(main, ["snapshot", "list", "--output", "json"])
        shown = runner.invoke(main, ["snapshot", "show", object_id, "--output", "json"])
        verified = runner.invoke(main, ["snapshot", "verify", object_id, "--output", "json"])
        inspected = runner.invoke(
            main,
            [
                "inspect",
                "XTKS:7203",
                "--source-profile",
                "offline-jp",
                "--output",
                "json",
            ],
        )

    assert sources.exit_code == imported.exit_code == 0
    source_document = json.loads(sources.stdout)
    validate("source-result", source_document)
    assert source_document["sources"][0]["name"] == "csv"
    assert source_document["sources"][0]["loaded"] is False
    validate("source-result", import_document)
    assert import_document["observations"] == 2
    for result in (listed, shown, verified):
        assert result.exit_code == 0
        validate("snapshot-result", json.loads(result.stdout))
    assert inspected.exit_code == 0
    inspection = json.loads(inspected.stdout)
    validate("inspect-result", inspection)
    assert inspection["sections"]["price"]["values"]["close"] == "112"
    assert inspection["sections"]["financial"]["missing_reasons"] == ["not_present_in_snapshot"]


def test_inspect_never_fetches_and_explains_missing_snapshot() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            main,
            [
                "inspect",
                "XTKS:7203",
                "--source-profile",
                "offline-jp",
                "--output",
                "json",
            ],
        )

    assert result.exit_code == 1
    error = json.loads(result.stderr)
    assert error["error"] == "inspect_failed"
    assert "marketsieve source import PATH" in error["message"]
