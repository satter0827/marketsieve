"""Composition root for the public CLI application."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TextIO

from marketsieve import __version__
from marketsieve_cli.adapters.config import Configuration
from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.adapters.explanations import ExplanationStore
from marketsieve_cli.adapters.plugins import SourcePluginRegistry
from marketsieve_cli.adapters.reports import ReportStore, render_markdown, report_document
from marketsieve_cli.adapters.snapshots import SnapshotStore
from marketsieve_cli.application.diagnostics import DiagnosticsService
from marketsieve_cli.application.snapshots import SnapshotService
from marketsieve_cli.observability import configure_logger


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
    """Render one report directly from its validated canonical model."""

    return render_markdown(build_report_store().resolve(report_id))


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


def sdk_version() -> str:
    """Return the installed public SDK version."""

    return __version__
