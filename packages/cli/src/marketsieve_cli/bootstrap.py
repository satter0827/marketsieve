"""Composition root for the public CLI application."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from marketsieve import __version__
from marketsieve_cli.adapters.ai_exchange import AiExchangeStore
from marketsieve_cli.adapters.config import Configuration
from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.adapters.experiments import ExperimentStore
from marketsieve_cli.adapters.explanations import ExplanationStore
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
from marketsieve_cli.adapters.screening import (
    ScreeningStore,
    screening_document,
    universe_document,
)
from marketsieve_cli.adapters.snapshots import SnapshotStore
from marketsieve_cli.application.ai import ManualAiService
from marketsieve_cli.application.diagnostics import DiagnosticsService
from marketsieve_cli.application.experiments import ExperimentService
from marketsieve_cli.application.routines import DailyBriefService, WeeklyBriefService
from marketsieve_cli.application.screening import ScreeningService
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

    return ReportStore(Path(".marketsieve/reports"))


def build_portfolio_store() -> PortfolioStore:
    """Build the canonical local portfolio repository."""

    return PortfolioStore(Path(".marketsieve/portfolio"))


def build_daily_brief_service(config_path: Path | None = None) -> DailyBriefService:
    """Build the one-command close-analysis workflow."""

    configuration = Configuration.resolve(config_path)
    return DailyBriefService(
        build_portfolio_store(),
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
        ScreeningStore(Path(".marketsieve/screening")),
    )


def build_experiment_service() -> ExperimentService:
    """Build the offline Strategy Lab workflow."""

    return ExperimentService(
        SnapshotStore(Path(".marketsieve/data")),
        ExperimentStore(Path(".marketsieve/experiments")),
    )


def build_screening_service(config_path: Path | None = None) -> ScreeningService:
    """Build explicit universe acquisition and offline screening workflows."""

    return ScreeningService(
        SourcePluginRegistry(),
        SnapshotStore(Path(".marketsieve/data")),
        build_portfolio_store(),
        ScreeningStore(Path(".marketsieve/screening")),
        Configuration.resolve(config_path),
    )


def update_screening(config_path: Path | None, market: str) -> dict[str, object]:
    """Acquire, persist, and project one bounded instrument universe."""

    return universe_document(build_screening_service(config_path).update(market))


def run_screening(config_path: Path | None, market: str, *, as_of: datetime) -> dict[str, object]:
    """Run and project one offline screening operation."""

    return screening_document(build_screening_service(config_path).run(market, as_of=as_of))


def read_screening(
    config_path: Path | None, report_id: str, *, market: str | None
) -> dict[str, object]:
    """Read and project one verified screening report."""

    return screening_document(build_screening_service(config_path).show(report_id, market=market))


def build_experiment_agent_service(config_path: Path | None = None) -> object:
    """Build the optional grounded experiment explanation workflow."""

    from marketsieve_cli.application.experiment_agent import ExperimentAgentService

    return ExperimentAgentService(
        ExperimentStore(Path(".marketsieve/experiments")),
        ExplanationStore(
            Path(".marketsieve/experiments/explanations"),
            schema="experiment-explanation/v1",
        ),
        Configuration.resolve(config_path),
        os.environ,
    )


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


def build_agent_service(config_path: Path | None = None) -> object:
    """Build the optional explanation service only when its command is invoked."""

    from marketsieve_cli.application.agent import AgentService

    configuration = Configuration.resolve(config_path)
    return AgentService(
        ReportStore(Path(".marketsieve/reports")),
        ExplanationStore(Path(".marketsieve/explanations")),
        configuration,
        os.environ,
    )


def build_ai_service() -> ManualAiService:
    """Build the offline, human-mediated AI exchange workflow."""

    return ManualAiService(
        ReportStore(Path(".marketsieve/reports")),
        AiExchangeStore(Path(".marketsieve/ai")),
    )


def sdk_version() -> str:
    """Return the installed public SDK version."""

    return __version__
