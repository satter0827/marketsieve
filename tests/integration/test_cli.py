import json
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator, FormatChecker

from marketsieve import __version__
from marketsieve.data.daily import DailyBarRequest, DailyBarSeries
from marketsieve.synthetic.daily import JP_BARS, SyntheticDailySource
from marketsieve_cli.application.diagnostics import DiagnosticCheck, DiagnosticsService
from marketsieve_cli.interfaces.cli import entrypoint, main
from marketsieve_extension_api import (
    AvailabilityBasis,
    Consolidation,
    CorporateEvent,
    CorporateEventType,
    DailyBarFetchRequest,
    FactFetchRequest,
    FinancialFact,
    FinancialPeriod,
    ImportedDailyBars,
    ImportedEvents,
    ImportedFinancials,
    InstrumentProfile,
    Revision,
)
from marketsieve_source_csv import CsvDailyBarImporter
from marketsieve_source_jquants import JQuantsSource

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
    validate("capabilities-result", document, major=2)
    assert [item["name"] for item in document["commands"]] == [
        "analyze atr",
        "analyze ema",
        "analyze macd",
        "analyze maximum-drawdown",
        "analyze period-return",
        "analyze rsi",
        "analyze sma",
        "capabilities",
        "doctor",
        "inspect",
        "report",
        "snapshot list",
        "snapshot show",
        "snapshot verify",
        "source doctor",
        "source fetch",
        "source import",
        "source list",
    ]
    report = next(item for item in document["commands"] if item["name"] == "report")
    assert {option["name"] for option in report["options"]} == {"market", "output_mode"}
    assert {option["name"] for option in document["global_options"]} == {
        "log_file",
        "log_level",
        "config_path",
    }
    assert report["effects"] == {
        "network": False,
        "optional_writes": ["log_file"],
        "secrets": False,
    }


def test_configuration_errors_do_not_block_commands_that_do_not_read_configuration() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("marketsieve.toml").write_text("[broken", encoding="utf-8")

        sources = runner.invoke(main, ["source", "list", "--output", "json"])
        snapshots = runner.invoke(main, ["snapshot", "list", "--output", "json"])
        missing_sources = runner.invoke(
            main,
            ["--config", "missing.toml", "source", "list", "--output", "json"],
        )

    assert sources.exit_code == 0
    validate("source-result", json.loads(sources.stdout))
    assert snapshots.exit_code == 0
    validate("snapshot-result", json.loads(snapshots.stdout))
    assert missing_sources.exit_code == 0
    validate("source-result", json.loads(missing_sources.stdout))


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
        analyzed = runner.invoke(
            main,
            [
                "analyze",
                "sma",
                "XTKS:7203",
                "--period",
                "2",
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
    jquants = next(item for item in source_document["sources"] if item["name"] == "jquants")
    assert jquants["data_kinds"] == ["daily_bars", "financials", "events"]
    validate("source-result", import_document)
    assert import_document["observations"] == 2
    for result in (listed, shown, verified):
        assert result.exit_code == 0
        validate("snapshot-result", json.loads(result.stdout))
    assert inspected.exit_code == 0
    inspection = json.loads(inspected.stdout)
    validate("inspect-result", inspection)
    assert inspection["sections"]["price"]["values"]["close"] == "112"
    assert inspection["sections"]["technical"]["status"] == "partial"
    assert inspection["sections"]["financial"]["missing_reasons"] == ["not_present_in_snapshot"]
    assert analyzed.exit_code == 0
    analysis = json.loads(analyzed.stdout)
    validate("indicator-result", analysis)
    assert analysis["indicator"]["values"] == {"sma": "108.5"}


def test_jquants_doctor_and_fetch_use_only_explicit_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = write_csv_bundle(tmp_path / "provider-fixture")
    imported = CsvDailyBarImporter().import_bundle(bundle)

    def fake_fetch(_: JQuantsSource, request: DailyBarFetchRequest) -> ImportedDailyBars:
        assert request.source_profile == "japan"
        return replace(
            imported,
            source_profile="japan",
            source_name="jquants",
            source_version="jquants-api-v2",
            dataset="equities/master+equities/bars/daily",
            fetch_request=request,
            instrument_profile=InstrumentProfile(
                imported.bars[-1].trading_date,
                None,
                (("ja", "テスト株式会社"),),
                (("market_code", "0111"),),
            ),
        )

    monkeypatch.setattr(JQuantsSource, "fetch", fake_fetch)
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("marketsieve.toml").write_text(
            "[source_profiles.japan]\n"
            'currency = "JPY"\n'
            'timezone = "Asia/Tokyo"\n'
            "[source_profiles.japan.daily_bars]\n"
            'plugin = "jquants"\n',
            encoding="utf-8",
        )
        missing = runner.invoke(
            main,
            ["source", "doctor", "japan", "--output", "json"],
            env={"JQUANTS_API_KEY": ""},
        )
        missing_snapshot = runner.invoke(
            main,
            ["inspect", "XTKS:7203", "--source-profile", "japan", "--output", "json"],
        )
        fetched = runner.invoke(
            main,
            [
                "source",
                "fetch",
                "japan",
                "XTKS:7203",
                "--start",
                "2026-07-30",
                "--end",
                "2026-07-31",
                "--output",
                "json",
            ],
            env={"JQUANTS_API_KEY": "example"},
        )
        inspected = runner.invoke(
            main,
            ["inspect", "XTKS:7203", "--source-profile", "japan", "--output", "json"],
        )
        assert inspected.exit_code == 0, (inspected.output, inspected.exception)

    assert missing.exit_code == 1
    validate("source-result", json.loads(missing.stdout))
    assert missing_snapshot.exit_code == 1
    assert (
        "marketsieve source fetch japan XTKS:7203" in json.loads(missing_snapshot.stderr)["message"]
    )
    assert fetched.exit_code == 0
    fetch_document = json.loads(fetched.stdout)
    validate("source-result", fetch_document)
    assert fetch_document["status"] == "fetched"
    inspection = json.loads(inspected.stdout)
    validate("inspect-result", inspection)
    assert inspection["instrument"]["profile"]["names"]["ja"] == "テスト株式会社"


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


def test_configured_import_only_source_explains_import_recovery() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("marketsieve.toml").write_text(
            "[source_profiles.offline-jp]\n"
            'currency = "JPY"\n'
            'timezone = "Asia/Tokyo"\n'
            "[source_profiles.offline-jp.daily_bars]\n"
            'plugin = "csv"\n',
            encoding="utf-8",
        )
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
    assert "marketsieve source import PATH" in json.loads(result.stderr)["message"]


def test_jquants_financials_and_events_join_price_inspection_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = write_csv_bundle(tmp_path / "fundamental-fixture")
    daily = CsvDailyBarImporter().import_bundle(bundle)

    def fake_daily(_: JQuantsSource, request: DailyBarFetchRequest) -> ImportedDailyBars:
        return replace(
            daily,
            source_profile=request.source_profile,
            source_name="jquants",
            source_version="jquants-api-v2",
            fetch_request=request,
        )

    def fake_financials(_: JQuantsSource, request: FactFetchRequest) -> ImportedFinancials:
        return ImportedFinancials(
            request,
            "jquants",
            "jquants-api-v2",
            "fins/summary",
            datetime(2026, 8, 1, tzinfo=UTC),
            (
                FinancialFact(
                    "revenue",
                    "Sales",
                    None,
                    FinancialPeriod.ANNUAL,
                    "FY",
                    date(2025, 4, 1),
                    date(2026, 3, 31),
                    datetime(2026, 7, 31, 15, tzinfo=ZoneInfo("Asia/Tokyo")),
                    datetime(2026, 7, 31, 15, tzinfo=ZoneInfo("Asia/Tokyo")),
                    AvailabilityBasis.PUBLISHED,
                    Consolidation.CONSOLIDATED,
                    Revision.REPORTED,
                    "JPY",
                    1,
                    Decimal("48000000000000"),
                ),
                FinancialFact(
                    "operating_income",
                    "OP",
                    None,
                    FinancialPeriod.ANNUAL,
                    "FY",
                    date(2025, 4, 1),
                    date(2026, 3, 31),
                    datetime(2026, 7, 31, 7, tzinfo=UTC),
                    datetime(2026, 7, 31, 7, tzinfo=UTC),
                    AvailabilityBasis.PUBLISHED,
                    Consolidation.CONSOLIDATED,
                    Revision.REPORTED,
                    "JPY",
                    1,
                    Decimal("5000000000000"),
                ),
            ),
            "c" * 64,
            ("interest_bearing_debt_not_present_in_summary",),
        )

    def fake_events(_: JQuantsSource, request: FactFetchRequest) -> ImportedEvents:
        return ImportedEvents(
            request,
            "jquants",
            "jquants-api-v2",
            "equities/earnings-calendar",
            datetime(2026, 7, 20, tzinfo=UTC),
            (
                CorporateEvent(
                    CorporateEventType.EARNINGS,
                    date(2026, 7, 30),
                    date(2026, 7, 30),
                    None,
                    datetime(2026, 7, 20, tzinfo=UTC),
                    AvailabilityBasis.RETRIEVAL,
                    (("quarter", "1Q"),),
                ),
            ),
            "d" * 64,
            (
                "dividend_endpoint_not_selected",
                "split_events_not_provided_by_selected_jquants_endpoints",
            ),
        )

    monkeypatch.setattr(JQuantsSource, "fetch", fake_daily)
    monkeypatch.setattr(JQuantsSource, "fetch_financials", fake_financials)
    monkeypatch.setattr(JQuantsSource, "fetch_events", fake_events)
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("marketsieve.toml").write_text(
            "[source_profiles.japan]\n"
            'currency = "JPY"\n'
            'timezone = "Asia/Tokyo"\n'
            '[source_profiles.japan.daily_bars]\nplugin = "jquants"\n'
            '[source_profiles.japan.financials]\nplugin = "jquants"\n'
            '[source_profiles.japan.events]\nplugin = "jquants"\n',
            encoding="utf-8",
        )
        results = [
            runner.invoke(
                main,
                [
                    "source",
                    "fetch",
                    "japan",
                    "XTKS:7203",
                    "--start",
                    "2026-07-01",
                    "--end",
                    "2026-07-31",
                    "--kind",
                    kind,
                    "--output",
                    "json",
                ],
                env={"JQUANTS_API_KEY": "example"},
            )
            for kind in ("daily_bars", "financials", "events")
        ]
        inspected = runner.invoke(
            main,
            ["inspect", "XTKS:7203", "--source-profile", "japan", "--output", "json"],
        )
        assert inspected.exit_code == 0, (inspected.output, inspected.exception)
        financial_id = json.loads(results[1].stdout)["object_id"]
        normalized = (
            Path(".marketsieve/data/objects") / financial_id / "normalized" / "financials.json"
        )
        normalized.write_bytes(normalized.read_bytes().replace(b'"revenue"', b'"tampered"'))
        inspected_with_corrupt_financials = runner.invoke(
            main,
            ["inspect", "XTKS:7203", "--source-profile", "japan", "--output", "json"],
        )

        def mismatched_financials(
            source: JQuantsSource, request: FactFetchRequest
        ) -> ImportedFinancials:
            imported = fake_financials(source, request)
            return replace(imported, request=replace(request, end=request.start))

        def mismatched_events(source: JQuantsSource, request: FactFetchRequest) -> ImportedEvents:
            imported = fake_events(source, request)
            return replace(imported, request=replace(request, end=request.start))

        monkeypatch.setattr(JQuantsSource, "fetch_financials", mismatched_financials)
        mismatched_financial_result = runner.invoke(
            main,
            [
                "source",
                "fetch",
                "japan",
                "XTKS:7203",
                "--start",
                "2026-07-01",
                "--end",
                "2026-07-31",
                "--kind",
                "financials",
                "--output",
                "json",
            ],
        )
        monkeypatch.setattr(JQuantsSource, "fetch_events", mismatched_events)
        mismatched_event_result = runner.invoke(
            main,
            [
                "source",
                "fetch",
                "japan",
                "XTKS:7203",
                "--start",
                "2026-07-01",
                "--end",
                "2026-07-31",
                "--kind",
                "events",
                "--output",
                "json",
            ],
        )

    for result in results:
        assert result.exit_code == 0, result.output
        validate("source-result", json.loads(result.stdout))
    inspection = json.loads(inspected.stdout)
    validate("inspect-result", inspection)
    assert inspection["sections"]["financial"]["values"]["facts"][0]["concept"] == "revenue"
    assert inspection["sections"]["financial"]["completeness"] == "0.25"
    assert inspection["sections"]["financial"]["as_of"] == "2026-07-31T07:00:00+00:00"
    assert inspection["sections"]["events"]["values"]["events"][0]["type"] == "earnings"
    assert inspection["sections"]["events"]["completeness"] == "0.333333"
    corrupt_inspection = json.loads(inspected_with_corrupt_financials.stdout)
    validate("inspect-result", corrupt_inspection)
    assert inspected_with_corrupt_financials.exit_code == 0
    assert corrupt_inspection["sections"]["price"]["status"] == "available"
    assert corrupt_inspection["sections"]["financial"]["status"] == "invalid"
    assert corrupt_inspection["sections"]["financial"]["missing_reasons"] == [
        "snapshot_verification_failed"
    ]
    for mismatched in (mismatched_financial_result, mismatched_event_result):
        assert mismatched.exit_code == 1
        assert "preserve the exact request" in json.loads(mismatched.stderr)["message"]
