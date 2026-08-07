"""Composition root for the public CLI application."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from marketsieve import __version__
from marketsieve_cli.adapters.analysis import AnalysisWorkspace
from marketsieve_cli.adapters.config import Configuration
from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.adapters.experiments import ExperimentStore
from marketsieve_cli.adapters.matrices import MatrixStore
from marketsieve_cli.adapters.plugins import SourcePluginRegistry
from marketsieve_cli.adapters.portfolio_plugins import PortfolioPluginRegistry
from marketsieve_cli.adapters.portfolios import (
    PortfolioStore,
    import_canonical_csv,
    portfolio_document,
)
from marketsieve_cli.adapters.reports import (
    ReportStore,
    create_report,
    report_document,
)
from marketsieve_cli.adapters.snapshots import SnapshotStore
from marketsieve_cli.adapters.watchlists import (
    PortfolioWatchlistReader,
    WatchlistStore,
    parse_instrument_key,
)
from marketsieve_cli.application.diagnostics import DiagnosticsService
from marketsieve_cli.application.experiments import ExperimentService
from marketsieve_cli.application.matrix import MatrixService
from marketsieve_cli.application.routines import DailyBriefService, WeeklyBriefService
from marketsieve_cli.application.snapshots import SnapshotService
from marketsieve_cli.observability import configure_logger
from marketsieve_extension_api import verify_portfolio_snapshot_importer


def build_console_output(
    mode: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
    width: int | None = None,
    locale: str = "ja",
) -> ConsoleOutput:
    """Build the console projection selected by one command invocation."""

    return ConsoleOutput(OutputMode(mode), stdout=stdout, stderr=stderr, width=width, locale=locale)


def build_diagnostics_service(
    *, level: str | None = None, write_log_file: bool = False
) -> DiagnosticsService:
    """Build the diagnostics use case with its default dependencies."""

    return DiagnosticsService(logger=configure_logger(level=level, write_file=write_log_file))


def build_snapshot_service(config_path: Path | None = None) -> SnapshotService:
    """Build explicit source-import and offline snapshot use cases."""

    return SnapshotService(
        SourcePluginRegistry(),
        SnapshotStore(Path(".marketsieve/data")),
        Configuration.resolve(config_path),
    )


def build_report_store() -> ReportStore:
    """Build the canonical decision-report repository."""

    return ReportStore(Path(".marketsieve/reports/v2"))


def build_portfolio_store() -> PortfolioStore:
    """Build the canonical local portfolio repository."""

    return PortfolioStore(Path(".marketsieve/portfolio"))


def build_watchlist_store() -> WatchlistStore:
    """Build the independent watchlist history repository."""

    return WatchlistStore(Path(".marketsieve/watchlists/v2"))


def build_daily_brief_service(config_path: Path | None = None) -> DailyBriefService:
    """Build the one-command close-analysis workflow."""

    configuration = Configuration.resolve(config_path)
    return DailyBriefService(
        PortfolioWatchlistReader(build_portfolio_store(), build_watchlist_store()),
        build_snapshot_service(config_path),
        build_report_store(),
        configuration,
        create_report,
    )


def build_weekly_brief_service(config_path: Path | None = None) -> WeeklyBriefService:
    """Build the offline weekly Close Brief workflow."""

    configuration = Configuration.resolve(config_path)
    return WeeklyBriefService(
        build_report_store(),
        configuration,
        create_report,
    )


def build_experiment_service() -> ExperimentService:
    """Build the offline Strategy Lab workflow."""

    return ExperimentService(
        SnapshotStore(Path(".marketsieve/data")),
        ExperimentStore(Path(".marketsieve/experiments")),
    )


def build_matrix_service(config_path: Path | None = None) -> MatrixService:
    """Build the zero-configuration yfinance market-matrix workflow."""

    return MatrixService(
        SourcePluginRegistry(),
        MatrixStore(Path(".marketsieve/matrices")),
        Configuration.resolve(config_path),
    )


def refresh_market_matrix(config_path: Path | None, *, resume: str | None = None) -> dict[str, Any]:
    """Acquire and persist the configured broad-equity matrix."""

    return build_matrix_service(config_path).refresh(resume=resume)


def show_market_matrix(config_path: Path | None, matrix_id: str) -> dict[str, Any]:
    """Show one persisted matrix manifest and its artifacts."""

    return build_matrix_service(config_path).show(matrix_id)


def read_market_matrix_row(
    config_path: Path | None, matrix_id: str, instrument_id: str
) -> dict[str, Any]:
    """Read one already-computed matrix row without network access."""

    return build_matrix_service(config_path).row(matrix_id, instrument_id)


def compare_market_matrix_rows(
    config_path: Path | None,
    matrix_id: str,
    instrument_ids: tuple[str, ...],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Compare already-computed matrix cells without recalculation."""

    return build_matrix_service(config_path).compare(matrix_id, instrument_ids, fields)


def build_analysis_workspace() -> AnalysisWorkspace:
    """Build the deterministic matrix-backed external-analysis projection."""

    return AnalysisWorkspace(
        Path(".marketsieve/analysis/v2"),
        MatrixStore(Path(".marketsieve/matrices")),
    )


def create_analysis_workspace(matrix_id: str = "latest") -> dict[str, Any]:
    """Create or replace deterministic workspace projection files."""

    return build_analysis_workspace().build(matrix_id)


def read_analysis_workspace() -> tuple[dict[str, Any], str]:
    """Read and verify the current workspace projection."""

    return build_analysis_workspace().show()


def import_portfolio(path: Path, *, broker: str, as_of: str) -> dict[str, object]:
    """Import one explicit portfolio file through a selected normalizer."""

    observed_at = datetime.fromisoformat(as_of)
    if broker == "canonical":
        imported = import_canonical_csv(path.read_bytes(), as_of=observed_at)
    else:
        imported = verify_portfolio_snapshot_importer(
            PortfolioPluginRegistry().load(broker), path, as_of=observed_at
        )
    object_id = build_portfolio_store().put(imported)
    return portfolio_document(imported, object_id=object_id)


def read_portfolio() -> dict[str, object]:
    """Read and validate the latest normalized portfolio."""

    object_id, imported = build_portfolio_store().latest()
    return portfolio_document(imported, object_id=object_id)


def add_watchlist_instrument(value: str, *, as_of: datetime) -> dict[str, Any]:
    """Add one explicitly selected instrument."""

    instrument = parse_instrument_key(value)
    return build_watchlist_store().add(instrument, as_of=as_of)


def remove_watchlist_instrument(value: str, *, as_of: datetime) -> dict[str, Any]:
    """Remove one explicitly selected instrument from the latest watchlist."""

    return build_watchlist_store().remove(parse_instrument_key(value), as_of=as_of)


def read_watchlist() -> dict[str, Any]:
    """Read the latest watchlist and expose its immutable history IDs."""

    store = build_watchlist_store()
    if not store.exists():
        return {
            "watchlist_id": None,
            "schema": "watchlist-result/v2",
            "as_of": None,
            "previous_watchlist_id": None,
            "change": None,
            "items": [],
            "history_ids": [],
        }
    document = store.latest()
    return {**document, "history_ids": [item["watchlist_id"] for item in store.history()]}


def list_decision_reports() -> dict[str, Any]:
    """Project the stored decision-report index."""

    return {
        "schema_version": "1.0.0",
        "reports": [
            {
                "report_id": item.report_id,
                "session": item.session.value,
                "as_of": item.as_of.isoformat(),
            }
            for item in build_report_store().list()
        ],
    }


def read_decision_report(report_id: str) -> dict[str, object]:
    """Read one canonical report document through the composition root."""

    return report_document(build_report_store().resolve(report_id))


def render_decision_report(report_id: str) -> str:
    """Read one verified Markdown report through the composition root."""

    store = build_report_store()
    selected = store.resolve(report_id)
    return store.markdown(selected.report_id)


def project_decision_report(report_id: str) -> str:
    """Read the verified canonical Markdown projection."""

    return render_decision_report(report_id)


def sdk_version() -> str:
    """Return the installed public SDK version."""

    return __version__
