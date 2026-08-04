"""Composition root for the public CLI application."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from marketsieve import __version__
from marketsieve.data.daily import Adjustment, DailyBarRequest
from marketsieve.synthetic.daily import (
    JP_BARS,
    JP_INSTRUMENT,
    US_BARS,
    US_INSTRUMENT,
    jp_source,
    us_source,
)
from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.adapters.plugins import SourcePluginRegistry
from marketsieve_cli.adapters.snapshots import SnapshotStore
from marketsieve_cli.application.diagnostics import DiagnosticsService
from marketsieve_cli.application.report import ReportMarket, ReportService
from marketsieve_cli.application.snapshots import SnapshotService
from marketsieve_cli.observability import configure_logger


def build_console_output(
    mode: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
    width: int | None = None,
) -> ConsoleOutput:
    """Build the console projection selected by one command invocation."""

    return ConsoleOutput(OutputMode(mode), stdout=stdout, stderr=stderr, width=width)


def build_diagnostics_service(
    *, level: str | None = None, write_log_file: bool = False
) -> DiagnosticsService:
    """Build the diagnostics use case with its default dependencies."""

    return DiagnosticsService(logger=configure_logger(level=level, write_file=write_log_file))


def build_report_service(
    output: ConsoleOutput,
    *,
    level: str | None = None,
    write_log_file: bool = False,
) -> ReportService:
    """Build the deterministic historical-report use case."""

    markets = (
        ReportMarket(
            "jp",
            jp_source(),
            DailyBarRequest(
                JP_INSTRUMENT,
                JP_BARS[0].trading_date,
                JP_BARS[-1].trading_date,
                Adjustment.RAW,
            ),
            tuple(bar.available_at for bar in JP_BARS),
        ),
        ReportMarket(
            "us",
            us_source(),
            DailyBarRequest(
                US_INSTRUMENT,
                US_BARS[0].trading_date,
                US_BARS[-1].trading_date,
                Adjustment.RAW,
            ),
            tuple(bar.available_at for bar in US_BARS),
        ),
    )
    logger = configure_logger(level=level, write_file=write_log_file)
    return ReportService(markets, output, logger)


def build_snapshot_service() -> SnapshotService:
    """Build explicit source-import and offline snapshot use cases."""

    return SnapshotService(
        SourcePluginRegistry(),
        SnapshotStore(Path(".marketsieve/data")),
    )


def sdk_version() -> str:
    """Return the installed public SDK version."""

    return __version__
