"""Composition root for the public CLI application."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from marketsieve import __version__
from marketsieve_cli.adapters.config import Configuration
from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.adapters.plugins import SourcePluginRegistry
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


def sdk_version() -> str:
    """Return the installed public SDK version."""

    return __version__
