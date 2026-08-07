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

ROOT = Path(__file__).parents[2]
RAKUTEN_EMPTY_FIXTURE = ROOT / "tests/fixtures/rakuten/assetbalance-empty.csv"
SCHEMAS = ROOT / "schemas"


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
    assert "marketsieve matrix refresh" in landing.stdout
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
    validate("capabilities-result", document, major=3)
    command_names = [item["name"] for item in document["commands"]]
    assert command_names == [
        "analysis build",
        "analysis show",
        "capabilities",
        "daily",
        "doctor",
        "experiment compare",
        "experiment run",
        "experiment show",
        "matrix compare",
        "matrix refresh",
        "matrix row",
        "matrix show",
        "portfolio import",
        "portfolio show",
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
        "watchlist add",
        "watchlist remove",
        "watchlist show",
        "weekly",
    ]
    assert {option["name"] for option in document["global_options"]} == {
        "log_file",
        "log_level",
        "config_path",
        "locale",
    }
    assert not {"agent doctor", "ai import", "report explain", "experiment explain"} & set(
        command_names
    )
    for removed in ("screen", "inspect", "analyze", "compare"):
        assert CliRunner().invoke(main, [removed]).exit_code == 2


def test_matrix_commands_project_versioned_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix_id = "a" * 64
    matrix_document: dict[str, object] = {
        "schema": "market-matrix/v1",
        "matrix_id": matrix_id,
        "input_snapshot_id": "d" * 64,
        "created_at": "2026-08-07T00:00:00+00:00",
        "request": {
            "fingerprint": "c" * 64,
            "schema": "market-matrix-request/v1",
            "indices": ["sp500"],
            "assets": {},
            "start": "2023-08-08",
            "end": "2026-08-07",
            "adjustment": "adjusted",
            "settings": {},
            "source": {"name": "yfinance", "profile": "matrix-yfinance"},
        },
        "source": {},
        "universe_assets": {},
        "configuration": {},
        "row_count": 2,
        "field_count": 2,
        "failure_count": 1,
        "coverage": {"overall": "1", "indices": {"sp500": "1"}},
        "quality_status": "ready",
        "summary": {
            "schema": "market-matrix-summary/v1",
            "generated_at": "2026-08-07T00:00:00+00:00",
            "coverage": {"overall": "1", "indices": {"sp500": "1"}},
            "quality_status": "ready",
            "groups": {
                name: {
                    "security_count": 2,
                    "price_count": 2,
                    "price_coverage": "1",
                    "advancing_count": 1,
                    "declining_count": 1,
                    "unchanged_count": 0,
                    "above_sma_20_count": 1,
                    "above_sma_200_count": 1,
                    "distributions": {},
                    "currency_distributions": {
                        "market_cap": {},
                        "median_traded_value_20d": {},
                    },
                    "concentration": {
                        "market_cap_observation_count": 0,
                        "top_10_market_cap_share": None,
                        "by_currency": {},
                    },
                    "sectors": {},
                    "missing": {"fields": {}, "reasons": {}},
                }
                for name in ("all", "sp500")
            },
        },
        "artifacts": {
            name: f"/fixture/{name}"
            for name in (
                "manifest.json",
                "fields.json",
                "securities.jsonl",
                "index-summary.json",
                "failures.jsonl",
                "matrix.csv",
                "overview.html",
                "analysis.md",
            )
        },
    }
    row_document: dict[str, object] = {
        "schema": "market-matrix-row/v1",
        "matrix_id": matrix_id,
        "instrument_id": "XNAS:MSFT",
        "instrument": {
            "mic": "XNAS",
            "symbol": "MSFT",
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            "instrument_type": "equity",
        },
        "provider_symbol": "MSFT",
        "memberships": ["sp500"],
        "retrieved_at": "2026-08-07T00:00:00+00:00",
        "evidence_id": "b" * 64,
        "values": {"close": "100"},
        "missing": {"trailing_pe": "field_absent"},
    }
    comparison_document: dict[str, object] = {
        "schema": "market-matrix-comparison/v1",
        "matrix_id": matrix_id,
        "fields": ["close"],
        "rows": [
            {"instrument_id": "XNAS:MSFT", "values": {"close": "100"}, "missing": {}},
            {"instrument_id": "XTKS:7203", "values": {"close": "200"}, "missing": {}},
        ],
    }
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")

    def refresh(config: Path | None, *, resume: str | None) -> dict[str, object]:
        assert config is None and resume == "fixture-run"
        return matrix_document

    monkeypatch.setattr(cli_module, "refresh_market_matrix", refresh)
    monkeypatch.setattr(
        cli_module,
        "show_market_matrix",
        lambda config, selected: (
            matrix_document if config is None and selected == matrix_id else {}
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "read_market_matrix_row",
        lambda config, selected, instrument: (
            row_document
            if config is None and (selected, instrument) == (matrix_id, "XNAS:MSFT")
            else {}
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "compare_market_matrix_rows",
        lambda config, selected, instruments, fields: (
            comparison_document
            if config is None
            and selected == matrix_id
            and instruments == ("XNAS:MSFT", "XTKS:7203")
            and fields == ("close",)
            else {}
        ),
    )
    runner = CliRunner()
    results = (
        runner.invoke(main, ["matrix", "refresh", "--resume", "fixture-run", "--output", "json"]),
        runner.invoke(main, ["matrix", "show", matrix_id, "--output", "json"]),
        runner.invoke(
            main,
            ["matrix", "row", "XNAS:MSFT", "--matrix", matrix_id, "--output", "json"],
        ),
        runner.invoke(
            main,
            [
                "matrix",
                "compare",
                "XNAS:MSFT",
                "XTKS:7203",
                "--matrix",
                matrix_id,
                "--fields",
                "close",
                "--output",
                "json",
            ],
        ),
    )

    assert all(result.exit_code == 0 for result in results)
    documents = [json.loads(result.stdout) for result in results]
    validate("market-matrix", documents[0])
    validate("market-matrix", documents[1])
    validate("market-matrix-row", documents[2])
    validate("market-matrix-comparison", documents[3])


@pytest.mark.parametrize(
    ("target", "arguments", "error_code"),
    (
        ("refresh_market_matrix", ("matrix", "refresh"), "matrix_refresh_failed"),
        ("show_market_matrix", ("matrix", "show"), "matrix_show_failed"),
        ("read_market_matrix_row", ("matrix", "row", "XNAS:MSFT"), "matrix_row_failed"),
        (
            "compare_market_matrix_rows",
            ("matrix", "compare", "XNAS:MSFT", "XTKS:7203"),
            "matrix_compare_failed",
        ),
    ),
)
def test_matrix_commands_normalize_failures(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    arguments: tuple[str, ...],
    error_code: str,
) -> None:
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise ValueError("fixture matrix failure")

    monkeypatch.setattr(cli_module, target, fail)
    result = CliRunner().invoke(main, [*arguments, "--output", "json"])

    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"] == error_code


def test_analysis_commands_project_matrix_context(monkeypatch: pytest.MonkeyPatch) -> None:
    context: dict[str, object] = {
        "context_id": "a" * 64,
        "schema": "analysis-context/v2",
        "as_of": "2026-08-07T00:00:00+00:00",
        "matrix": {
            "matrix_id": "b" * 64,
            "created_at": "2026-08-07T00:00:00+00:00",
            "row_count": 2,
            "field_count": 100,
            "quality_status": "ready",
            "coverage": {"overall": "1", "indices": {"sp500": "1"}},
            "manifest_path": "../matrices/manifest.json",
            "fields_path": "../matrices/fields.json",
            "index_summary_path": "../matrices/index-summary.json",
            "securities_jsonl_path": "../matrices/securities.jsonl",
            "failures_jsonl_path": "../matrices/failures.jsonl",
        },
        "constraints": ["Do not rank securities."],
    }
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")
    monkeypatch.setattr(
        cli_module,
        "create_analysis_workspace",
        lambda matrix_id: context if matrix_id == "b" * 64 else {},
    )
    monkeypatch.setattr(cli_module, "read_analysis_workspace", lambda: (context, "# Analysis\n"))
    runner = CliRunner()
    built = runner.invoke(main, ["analysis", "build", "--matrix", "b" * 64, "--output", "json"])
    shown = runner.invoke(main, ["analysis", "show", "--output", "json"])
    markdown = runner.invoke(main, ["analysis", "show", "--output", "text"])

    assert built.exit_code == shown.exit_code == markdown.exit_code == 0
    validate("analysis-context", json.loads(built.stdout), major=2)
    validate("analysis-context", json.loads(shown.stdout), major=2)
    assert markdown.stdout == "# Analysis\n"


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

    strategy = tmp_path / "strategy.toml"
    strategy.write_text("[experiment]\n", encoding="utf-8")
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")
    monkeypatch.setattr(cli_module, "build_experiment_service", StubExperimentService)
    runner = CliRunner()

    results = (
        runner.invoke(main, ["experiment", "run", str(strategy), "--output", "json"]),
        runner.invoke(main, ["experiment", "show", left, "--output", "json"]),
        runner.invoke(main, ["experiment", "compare", left, right, "--output", "json"]),
    )

    assert all(result.exit_code == 0 for result in results), [
        (result.output, result.exception) for result in results
    ]
    assert json.loads(results[0].stdout) == run_document
    assert json.loads(results[1].stdout) == run_document
    assert json.loads(results[2].stdout) == comparison_document


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

    strategy = tmp_path / "strategy.toml"
    strategy.write_text("[experiment]\n", encoding="utf-8")
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")
    monkeypatch.setattr(cli_module, "build_experiment_service", FailedExperimentService)
    digest = "a" * 64
    results = (
        CliRunner().invoke(main, ["experiment", "run", str(strategy), "--output", "json"]),
        CliRunner().invoke(main, ["experiment", "show", digest, "--output", "json"]),
        CliRunner().invoke(main, ["experiment", "compare", digest, digest, "--output", "json"]),
    )

    assert all(result.exit_code == 1 for result in results)
    assert [json.loads(result.stderr)["error"] for result in results] == [
        "experiment_run_failed",
        "experiment_show_failed",
        "experiment_compare_failed",
    ]
    assert all("Traceback" not in result.output for result in results)


def test_canonical_portfolio_import_and_show_are_offline_and_deterministic() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        source = Path("portfolio.csv")
        source.write_text(
            "mic,symbol,currency,timezone,quantity,average_acquisition_price,account_type\n"
            "XTKS,7203,JPY,Asia/Tokyo,10,2500,NISA\n",
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
        assert "watch_items" not in imported_document
        assert not any(
            path.read_bytes() == source.read_bytes()
            for path in Path(".marketsieve/portfolio").rglob("*")
            if path.is_file()
        )
    validate("portfolio-result", imported_document, major=3)
    validate("portfolio-result", shown_document, major=3)


def test_watchlist_commands_complete_an_offline_cli_flow() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        added = runner.invoke(main, ["watchlist", "add", "XNAS:MSFT", "--output", "json"])
        shown = runner.invoke(main, ["watchlist", "show", "--output", "json"])
        removed = runner.invoke(main, ["watchlist", "remove", "XNAS:MSFT", "--output", "json"])

        assert all(result.exit_code == 0 for result in (added, shown, removed))
        added_document = json.loads(added.stdout)
        shown_document = json.loads(shown.stdout)
        removed_document = json.loads(removed.stdout)
        validate("watchlist-result", added_document, major=2)
        validate("watchlist-result", shown_document, major=2)
        validate("watchlist-result", removed_document, major=2)
        assert shown_document["items"][0]["key"] == "XNAS:MSFT"
        assert removed_document["items"] == []


def test_watchlist_show_exposes_dangling_latest_object() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        added = runner.invoke(main, ["watchlist", "add", "XNAS:MSFT", "--output", "json"])
        document = json.loads(added.stdout)
        Path(f".marketsieve/watchlists/v2/objects/{document['watchlist_id']}.json").unlink()

        shown = runner.invoke(main, ["watchlist", "show", "--output", "json"])

    assert shown.exit_code == 1
    assert "watchlist object does not exist" in json.loads(shown.stderr)["message"]


def test_rakuten_empty_portfolio_import_is_offline_and_private() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        imported = runner.invoke(
            main,
            [
                "portfolio",
                "import",
                str(RAKUTEN_EMPTY_FIXTURE),
                "--broker",
                "rakuten",
                "--as-of",
                "2026-08-06T12:48:40+09:00",
                "--output",
                "json",
            ],
        )

        assert imported.exit_code == 0, imported.output
        document = json.loads(imported.stdout)
        assert document["holdings"] == []
        assert "watch_items" not in document
        assert document["source"] == "rakuten_assetbalance_empty"
        assert document["source_name"] == "rakuten"
        assert document["source_version"] == "0.9.0"
        assert document["dataset"] == "assetbalance-all-empty/v1"
        assert document["diagnostics"] == ["empty_portfolio"]
        assert not any(
            path.read_bytes() == RAKUTEN_EMPTY_FIXTURE.read_bytes()
            for path in Path(".marketsieve/portfolio").rglob("*")
            if path.is_file()
        )
    validate("portfolio-result", document, major=3)


@pytest.mark.parametrize(
    "failure",
    (ImportError("load failed"), LookupError("missing input"), RuntimeError("adapter failed")),
)
def test_portfolio_import_normalizes_plugin_operational_failures(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")

    def fail_import(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(cli_module, "import_portfolio", fail_import)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "portfolio",
            "import",
            str(RAKUTEN_EMPTY_FIXTURE),
            "--broker",
            "fixture",
            "--as-of",
            "2026-08-06T12:48:40+09:00",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "error": "portfolio_import_failed",
        "message": str(failure),
        "schema_version": "1.0.0",
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


def test_csv_import_and_snapshot_commands_are_one_offline_path(tmp_path: Path) -> None:
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


def test_report_commands_preserve_one_immutable_report() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        report_id = write_decision_report(Path(".marketsieve/reports/v2"))
        report_path = Path(f".marketsieve/reports/v2/objects/{report_id}.json")
        original_report = report_path.read_bytes()
        listed = runner.invoke(main, ["report", "list", "--output", "json"])
        shown = runner.invoke(main, ["report", "show", "latest", "--output", "json"])
        exported = runner.invoke(main, ["report", "export", "latest"])
        assert report_path.read_bytes() == original_report

    assert listed.exit_code == 0, listed.output
    list_document = json.loads(listed.stdout)
    validate("report-list", list_document)
    assert list_document["reports"][0]["report_id"] == report_id
    assert shown.exit_code == 0, shown.output
    shown_document = json.loads(shown.stdout)
    validate("decision-report", shown_document, major=2)
    assert shown_document["report_id"] == report_id
    assert exported.exit_code == 0
    assert exported.stdout.startswith("# Close Brief\n")


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

    assert missing.exit_code == 1
    validate("source-result", json.loads(missing.stdout))
    assert fetched.exit_code == 0
    fetch_document = json.loads(fetched.stdout)
    validate("source-result", fetch_document)
    assert fetch_document["status"] == "fetched"


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
    for mismatched in (mismatched_financial_result, mismatched_event_result):
        assert mismatched.exit_code == 1
        assert "preserve the exact request" in json.loads(mismatched.stderr)["message"]
