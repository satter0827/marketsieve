"""Composition root for repository-local application services."""

from marketsieve import __version__
from marketsieve_app.application.diagnostics import DiagnosticsService
from marketsieve_app.observability import configure_logger


def build_diagnostics_service(
    *, level: str = "WARNING", write_log_file: bool = False
) -> DiagnosticsService:
    """Build the diagnostics use case with its default dependencies."""

    return DiagnosticsService(logger=configure_logger(level=level, write_file=write_log_file))


def sdk_version() -> str:
    """Return the installed public SDK version."""

    return __version__
