"""Offline installation diagnostics."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from marketsieve import __version__ as sdk_version

SUPPORTED_PYTHON = ((3, 12), (3, 13), (3, 14))


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """One deterministic environment diagnostic."""

    name: str
    detail: str
    passed: bool
    action: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticsService:
    """Collect diagnostics without reading secrets or performing I/O."""

    logger: logging.Logger
    python_version: tuple[int, int, int] | None = None

    def collect(self) -> tuple[DiagnosticCheck, ...]:
        """Return the supported-Python and package installation checks."""

        detected_python = self.python_version or sys.version_info[:3]
        python_supported = detected_python[:2] in SUPPORTED_PYTHON

        try:
            application_version = version("marketsieve-app")
            application_installed = True
        except PackageNotFoundError:
            application_version = "not installed"
            application_installed = False

        checks = (
            DiagnosticCheck(
                name="Python",
                detail=".".join(str(part) for part in detected_python),
                passed=python_supported,
                action=None
                if python_supported
                else "Use Python 3.12, 3.13, or 3.14 and run make sync.",
            ),
            DiagnosticCheck(name="MarketSieve SDK", detail=sdk_version, passed=True),
            DiagnosticCheck(
                name="MarketSieve application",
                detail=application_version,
                passed=application_installed,
                action=None if application_installed else "Run make sync.",
            ),
        )
        self.logger.info(
            "Offline diagnostics completed",
            extra={
                "event_name": "diagnostics.completed",
                "attributes": {
                    "check_count": len(checks),
                    "succeeded": self.succeeded(checks),
                },
            },
        )
        return checks

    def succeeded(self, checks: tuple[DiagnosticCheck, ...]) -> bool:
        """Return whether every diagnostic check passed."""

        return all(check.passed for check in checks)
