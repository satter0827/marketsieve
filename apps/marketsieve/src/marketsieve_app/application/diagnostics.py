"""Offline installation diagnostics."""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class DiagnosticsService:
    """Collect diagnostics without reading secrets or performing I/O."""

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

        return (
            DiagnosticCheck(
                name="Python",
                detail=".".join(str(part) for part in detected_python),
                passed=python_supported,
            ),
            DiagnosticCheck(name="MarketSieve SDK", detail=sdk_version, passed=True),
            DiagnosticCheck(
                name="MarketSieve application",
                detail=application_version,
                passed=application_installed,
            ),
        )

    def succeeded(self, checks: tuple[DiagnosticCheck, ...]) -> bool:
        """Return whether every diagnostic check passed."""

        return all(check.passed for check in checks)
