"""Composition root for repository-local application services."""

from marketsieve import __version__
from marketsieve_app.application.diagnostics import DiagnosticsService


def build_diagnostics_service() -> DiagnosticsService:
    """Build the diagnostics use case with its default dependencies."""

    return DiagnosticsService()


def sdk_version() -> str:
    """Return the installed public SDK version."""

    return __version__
