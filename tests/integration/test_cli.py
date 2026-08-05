import importlib
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

from marketsieve import (
    DecisionAction,
    DecisionConfidence,
    DecisionEvidence,
    EvidenceDirection,
    Holding,
    InstrumentDecision,
    MarketSession,
    PortfolioSnapshot,
    __version__,
)
from marketsieve.domain import Instrument
from marketsieve_cli.adapters.reports import ReportStore, create_report
from marketsieve_cli.application.agent import AgentService
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


def write_decision_report(root: Path) -> str:
    instrument = Instrument.create(
        symbol="7203",
        mic="XTKS",
        currency="JPY",
        exchange_timezone="Asia/Tokyo",
    )
    settings = (("rsi_overbought", "70"),)
    decision = InstrumentDecision(
        instrument,
        True,
        DecisionAction.KEEP,
        DecisionConfidence.MEDIUM,
        (
            DecisionEvidence(
                "trend_above_sma60",
                EvidenceDirection.SUPPORTING,
                "2500",
                "2400",
                ("bars-evidence",),
            ),
        ),
        None,
        Decimal("0.05"),
        Decimal("0.03"),
        Decimal("1000000"),
        (("per", "14.2"),),
        (("latest_filing", "fixture-2026"),),
        ("close_below_sma60",),
        "次の終値で傾向を確認する",
        "balanced_medium_term",
        "1.0.0",
        settings,
    )
    as_of = datetime(2026, 8, 3, 6, tzinfo=UTC)
    portfolio = PortfolioSnapshot(
        as_of,
        (Holding(instrument, Decimal("10"), Decimal("2300"), "taxable"),),
        (),
        "fixture",
    )
    report = create_report(
        MarketSession.JP_CLOSE,
        as_of,
        portfolio,
        (decision,),
        diagnostics=("FRED系列は未取得",),
    )
    ReportStore(root).put(report)
    return report.report_id


def validate(name: str, document: object, major: int = 1) -> None:
    schema = json.loads((SCHEMAS / name / f"v{major}" / "schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def test_landing_and_version_are_immediately_useful() -> None:
    runner = CliRunner()
    landing = runner.invoke(main, [])
    version = runner.invoke(main, ["--version"])

    assert landing.exit_code == 0
    assert "再現可能な日本株・米国株分析" in landing.stdout
    assert "marketsieve inspect MIC:SYMBOL" in landing.stdout
    assert version.output == f"marketsieve, version {__version__}\n"


def test_doctor_supports_text_and_schema_valid_json() -> None:
    runner = CliRunner()
    text_result = runner.invoke(main, ["--locale", "en", "doctor", "--output", "text"])
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
    result = CliRunner().invoke(main, ["--locale", "en", "doctor", "--output", "text"])

    assert result.exit_code == 1
    assert "ACTION Use Python 3.13." in result.stdout
    assert "Traceback" not in result.output


def test_capabilities_match_click_commands_and_validate_schema() -> None:
    result = CliRunner().invoke(main, ["capabilities", "--output", "json"])

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    validate("capabilities-result", document, major=2)
    assert [item["name"] for item in document["commands"]] == [
        "agent doctor",
        "analyze atr",
        "analyze ema",
        "analyze macd",
        "analyze maximum-drawdown",
        "analyze period-return",
        "analyze rsi",
        "analyze sma",
        "capabilities",
        "compare",
        "daily",
        "doctor",
        "equity-report",
        "experiment compare",
        "experiment explain",
        "experiment run",
        "experiment show",
        "inspect",
        "portfolio import",
        "portfolio show",
        "report explain",
        "report export",
        "report list",
        "report show",
        "snapshot list",
        "snapshot show",
        "snapshot verify",
        "source doctor",
        "source fetch",
        "source import",
        "source list",
        "weekly",
    ]
    report = next(item for item in document["commands"] if item["name"] == "report explain")
    assert {option["name"] for option in report["options"]} == {
        "provider",
        "allow_cloud",
        "allow_remote",
        "dry_run",
        "output_mode",
    }
    assert {option["name"] for option in document["global_options"]} == {
        "log_file",
        "log_level",
        "config_path",
        "locale",
    }
    assert report["effects"] == {
        "network": True,
        "optional_writes": ["explanation"],
        "secrets": True,
    }


def test_experiment_commands_project_service_documents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    left = "a" * 64
    right = "b" * 64
    run_document: dict[str, object] = {
        "schema": "experiment-run/v1",
        "run_id": left,
        "spec_id": "c" * 64,
        "profit_simulation": False,
        "spec": {},
        "decisions": [],
        "metrics": {},
    }
    comparison_document: dict[str, object] = {
        "schema": "experiment-comparison/v1",
        "left_run_id": left,
        "right_run_id": right,
        "metric_deltas": {},
    }
    explanation_document: dict[str, object] = {
        "schema": "experiment-explanation/v1",
        "explanation_id": "d" * 64,
        "status": "model",
        "provider": "lmstudio",
        "model": "local-model",
        "validation": {"status": "accepted", "reason": None},
    }

    class StubExperimentService:
        def run(self, spec: Path) -> dict[str, object]:
            assert spec == strategy
            return run_document

        def show(self, run_id: str) -> dict[str, object]:
            assert run_id == left
            return run_document

        def compare(self, left_run_id: str, right_run_id: str) -> dict[str, object]:
            assert (left_run_id, right_run_id) == (left, right)
            return comparison_document

    class StubExperimentAgentService:
        def explain(
            self, run_id: str, provider: str, locale: str, **options: bool
        ) -> dict[str, object]:
            assert (run_id, provider, locale) == (left, "lmstudio", "ja")
            assert options == {"allow_cloud": False, "allow_remote": False}
            return explanation_document

    strategy = tmp_path / "strategy.toml"
    strategy.write_text("[experiment]\n", encoding="utf-8")
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")
    monkeypatch.setattr(cli_module, "build_experiment_service", StubExperimentService)
    monkeypatch.setattr(
        cli_module,
        "build_experiment_agent_service",
        lambda config_path: StubExperimentAgentService(),
    )
    runner = CliRunner()

    results = (
        runner.invoke(main, ["experiment", "run", str(strategy), "--output", "json"]),
        runner.invoke(main, ["experiment", "show", left, "--output", "json"]),
        runner.invoke(main, ["experiment", "compare", left, right, "--output", "json"]),
        runner.invoke(
            main,
            ["experiment", "explain", left, "--provider", "lmstudio", "--output", "json"],
        ),
    )

    assert all(result.exit_code == 0 for result in results), [
        (result.output, result.exception) for result in results
    ]
    assert json.loads(results[0].stdout) == run_document
    assert json.loads(results[1].stdout) == run_document
    assert json.loads(results[2].stdout) == comparison_document
    assert json.loads(results[3].stdout) == explanation_document


def test_experiment_commands_report_service_failures_without_tracebacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FailedExperimentService:
        def run(self, spec: Path) -> dict[str, object]:
            raise ValueError(f"invalid strategy: {spec.name}")

        def show(self, run_id: str) -> dict[str, object]:
            raise LookupError(f"missing run: {run_id}")

        def compare(self, left_run_id: str, right_run_id: str) -> dict[str, object]:
            raise ValueError(f"incompatible runs: {left_run_id}, {right_run_id}")

    class FailedExperimentAgentService:
        def explain(self, *args: object, **kwargs: object) -> dict[str, object]:
            raise LookupError("missing experiment")

    strategy = tmp_path / "strategy.toml"
    strategy.write_text("[experiment]\n", encoding="utf-8")
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")
    monkeypatch.setattr(cli_module, "build_experiment_service", FailedExperimentService)
    monkeypatch.setattr(
        cli_module,
        "build_experiment_agent_service",
        lambda config_path: FailedExperimentAgentService(),
    )
    digest = "a" * 64
    results = (
        CliRunner().invoke(main, ["experiment", "run", str(strategy), "--output", "json"]),
        CliRunner().invoke(main, ["experiment", "show", digest, "--output", "json"]),
        CliRunner().invoke(main, ["experiment", "compare", digest, digest, "--output", "json"]),
        CliRunner().invoke(
            main,
            ["experiment", "explain", digest, "--provider", "lmstudio", "--output", "json"],
        ),
    )

    assert all(result.exit_code == 1 for result in results)
    assert [json.loads(result.stderr)["error"] for result in results] == [
        "experiment_run_failed",
        "experiment_show_failed",
        "experiment_compare_failed",
        "experiment_agent_failed",
    ]
    assert all("Traceback" not in result.output for result in results)


def test_canonical_portfolio_import_and_show_are_offline_and_deterministic() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        source = Path("portfolio.csv")
        source.write_text(
            "kind,mic,symbol,currency,timezone,quantity,average_acquisition_price,account_type\n"
            "watch,XNAS,MSFT,USD,America/New_York,,,\n"
            "holding,XTKS,7203,JPY,Asia/Tokyo,10,2500,NISA\n",
            encoding="utf-8",
        )
        imported = runner.invoke(
            main,
            [
                "portfolio",
                "import",
                str(source),
                "--broker",
                "canonical",
                "--as-of",
                "2026-08-06T20:00:00+09:00",
                "--output",
                "json",
            ],
        )
        shown = runner.invoke(main, ["portfolio", "show", "--output", "json"])

        assert imported.exit_code == shown.exit_code == 0
        imported_document = json.loads(imported.stdout)
        shown_document = json.loads(shown.stdout)
        assert imported_document == shown_document
        assert imported_document["holdings"][0]["instrument"]["symbol"] == "7203"
        assert imported_document["watch_items"][0]["instrument"]["symbol"] == "MSFT"
        assert not any(
            path.read_bytes() == source.read_bytes()
            for path in Path(".marketsieve/portfolio").rglob("*")
            if path.is_file()
        )
    validate("portfolio-result", imported_document)
    validate("portfolio-result", shown_document)


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


def test_entrypoint_renders_json_usage_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["marketsieve", "report", "--output", "json"],
    )

    with pytest.raises(SystemExit, match="2"):
        entrypoint()

    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    validate("cli-error", error)
    assert error["error"] == "invalid_cli_usage"


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
    csv_source = next(item for item in source_document["sources"] if item["name"] == "csv")
    assert csv_source["loaded"] is False
    jquants = next(item for item in source_document["sources"] if item["name"] == "jquants")
    assert jquants["data_kinds"] == [
        "daily_bars",
        "financials",
        "events",
        "instrument_universe",
    ]
    alphavantage = next(
        item for item in source_document["sources"] if item["name"] == "alphavantage"
    )
    assert alphavantage["data_kinds"] == ["daily_bars", "financials", "events"]
    fred = next(item for item in source_document["sources"] if item["name"] == "fred")
    assert fred["data_kinds"] == ["economic_series"]
    sec = next(item for item in source_document["sources"] if item["name"] == "sec")
    assert sec["data_kinds"] == ["financials", "instrument_universe"]
    edinet = next(item for item in source_document["sources"] if item["name"] == "edinet")
    assert edinet["data_kinds"] == ["financials"]
    validate("source-result", import_document)
    assert import_document["observations"] == 2
    for result in (listed, shown, verified):
        assert result.exit_code == 0
        validate("snapshot-result", json.loads(result.stdout))
    assert inspected.exit_code == 0
    inspection = json.loads(inspected.stdout)
    validate("inspect-result", inspection, major=2)
    assert inspection["sections"]["price"]["values"]["close"] == "112"
    assert inspection["sections"]["technical"]["status"] == "partial"
    assert inspection["sections"]["financial"]["missing_reasons"] == ["not_present_in_snapshot"]
    assert analyzed.exit_code == 0
    analysis = json.loads(analyzed.stdout)
    validate("indicator-result", analysis)
    assert analysis["indicator"]["values"] == {"sma": "108.5"}


def test_report_commands_and_explicit_agent_share_one_immutable_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()

    class LocalModel:
        provider = "lmstudio"
        model = "configured-local-model"

        def invoke(self, prompt: str) -> str:
            assert '"quantity"' not in prompt
            assert "2300" not in prompt
            return json.dumps(
                {
                    "section_order": ["XTKS:7203"],
                    "selected_facts": [
                        {
                            "fact_id": "decision.XTKS:7203.action",
                            "emphasis": "context",
                        }
                    ],
                    "connections": ["保存済みの判断根拠を整理します。"],
                },
                ensure_ascii=False,
            )

    class FailedModel:
        provider = "lmstudio"
        model = "configured-local-model"

        def invoke(self, prompt: str) -> str:
            del prompt
            raise RuntimeError("provider detail must not escape")

    with runner.isolated_filesystem():
        Path("marketsieve.toml").write_text(
            "[agent.providers.openai]\n"
            'model = "configured-cloud-model"\n'
            "[agent.providers.lmstudio]\n"
            'model = "configured-local-model"\n',
            encoding="utf-8",
        )
        report_id = write_decision_report(Path(".marketsieve/reports"))
        report_path = Path(f".marketsieve/reports/objects/{report_id}.json")
        original_report = report_path.read_bytes()
        listed = runner.invoke(main, ["report", "list", "--output", "json"])
        shown = runner.invoke(main, ["report", "show", "latest", "--output", "json"])
        exported = runner.invoke(main, ["report", "export", "latest"])
        preview = runner.invoke(
            main,
            [
                "report",
                "explain",
                report_id,
                "--provider",
                "openai",
                "--dry-run",
                "--output",
                "json",
            ],
        )
        local_doctor = runner.invoke(main, ["agent", "doctor", "lmstudio", "--output", "json"])
        refused_cloud = runner.invoke(
            main,
            [
                "report",
                "explain",
                report_id,
                "--provider",
                "openai",
                "--output",
                "json",
            ],
        )
        monkeypatch.setattr(AgentService, "_model", lambda *args, **kwargs: LocalModel())
        explained = runner.invoke(
            main,
            [
                "report",
                "explain",
                "latest",
                "--provider",
                "lmstudio",
                "--output",
                "json",
            ],
        )
        monkeypatch.setattr(AgentService, "_model", lambda *args, **kwargs: FailedModel())
        fallback = runner.invoke(
            main,
            [
                "report",
                "explain",
                report_id,
                "--provider",
                "lmstudio",
                "--output",
                "json",
            ],
        )

        assert report_path.read_bytes() == original_report
        assert len(tuple(Path(".marketsieve/explanations/objects").glob("*.json"))) == 2

    assert listed.exit_code == 0, listed.output
    list_document = json.loads(listed.stdout)
    validate("report-list", list_document)
    assert list_document["reports"][0]["report_id"] == report_id
    assert shown.exit_code == 0, shown.output
    shown_document = json.loads(shown.stdout)
    validate("decision-report", shown_document)
    assert shown_document["report_id"] == report_id
    assert exported.exit_code == 0
    assert exported.stdout.startswith("# Close Brief\n")
    assert preview.exit_code == 0, preview.output
    preview_document = json.loads(preview.stdout)
    validate("agent-result", preview_document)
    assert preview_document["operation"] == "dry_run"
    assert preview_document["report_id"] == report_id
    assert preview_document["model"] == "configured-cloud-model"
    assert "credential" not in preview_document["payload"].casefold()
    assert local_doctor.exit_code == 0
    validate("agent-result", json.loads(local_doctor.stdout))
    assert refused_cloud.exit_code == 1
    assert "cloud consent" in refused_cloud.stderr
    assert explained.exit_code == 0, explained.output
    explanation = json.loads(explained.stdout)
    validate("agent-result", explanation)
    assert explanation["provider"] == "lmstudio"
    assert explanation["report_id"] == report_id
    assert explanation["schema"] == "report-explanation/v1"
    assert fallback.exit_code == 0, fallback.output
    fallback_document = json.loads(fallback.stdout)
    validate("agent-result", fallback_document)
    assert fallback_document["status"] == "template"
    assert "provider detail" not in fallback_document["text"]
    assert "provider detail" not in fallback.stderr


def test_report_projects_the_same_offline_equity_view(tmp_path: Path) -> None:
    runner = CliRunner()
    bundle = write_csv_bundle(tmp_path / "report-bundle")
    with runner.isolated_filesystem():
        assert runner.invoke(main, ["source", "import", str(bundle)]).exit_code == 0
        report = runner.invoke(
            main,
            [
                "equity-report",
                "XTKS:7203",
                "--source-profile",
                "offline-jp",
                "--format",
                "json",
            ],
        )

    assert report.exit_code == 0, report.output
    document = json.loads(report.stdout)
    validate("report-result", document, major=2)
    assert document["sections"]["price"]["values"]["close"] == "112"
    assert len(document["summary"]) == 7
    assert "not investment advice" in document["disclaimer"]


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
    validate("inspect-result", inspection, major=2)
    assert inspection["instrument"]["profile"]["names"]["ja"] == "テスト株式会社"
    assert inspection["instrument"]["profile"]["availability_basis"] == "retrieval"
    assert inspection["instrument"]["profile"]["available_at"] == "2026-08-01T12:00:00+00:00"


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
    validate("inspect-result", inspection, major=2)
    assert inspection["sections"]["financial"]["values"]["facts"][0]["concept"] == "revenue"
    assert inspection["sections"]["financial"]["completeness"] == (
        "0.1111111111111111111111111111111111"
    )
    assert (
        "compatible_annual_financial_period_not_available"
        in inspection["sections"]["financial"]["missing_reasons"]
    )
    assert inspection["sections"]["financial"]["as_of"] == "2026-07-31T07:00:00+00:00"
    assert inspection["sections"]["events"]["values"]["events"][0]["type"] == "earnings"
    assert inspection["sections"]["events"]["completeness"] == "0.333333"
    corrupt_inspection = json.loads(inspected_with_corrupt_financials.stdout)
    validate("inspect-result", corrupt_inspection, major=2)
    assert inspected_with_corrupt_financials.exit_code == 0
    assert corrupt_inspection["sections"]["price"]["status"] == "available"
    assert corrupt_inspection["sections"]["financial"]["status"] == "invalid"
    assert corrupt_inspection["sections"]["financial"]["missing_reasons"] == [
        "snapshot_verification_failed"
    ]
    for mismatched in (mismatched_financial_result, mismatched_event_result):
        assert mismatched.exit_code == 1
        assert "preserve the exact request" in json.loads(mismatched.stderr)["message"]
