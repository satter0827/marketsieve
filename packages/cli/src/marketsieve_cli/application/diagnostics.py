"""Offline installation diagnostics."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

SUPPORTED_PYTHON = ((3, 12), (3, 13), (3, 14))
SUITE_DISTRIBUTIONS = (
    ("MarketSieve SDK", "marketsieve"),
    ("MarketSieve extension API", "marketsieve-extension-api"),
    ("yfinance source", "marketsieve-source-yfinance"),
    ("MarketSieve CLI", "marketsieve-cli"),
)


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

        installed: dict[str, str | None] = {}
        for _label, distribution in SUITE_DISTRIBUTIONS:
            try:
                installed[distribution] = version(distribution)
            except PackageNotFoundError:
                installed[distribution] = None
        observed_versions = {value for value in installed.values() if value is not None}
        versions_match = len(observed_versions) == 1 and all(
            value is not None for value in installed.values()
        )

        checks = (
            DiagnosticCheck(
                name="Python",
                detail=".".join(str(part) for part in detected_python),
                passed=python_supported,
                action=None
                if python_supported
                else "Use Python 3.12, 3.13, or 3.14 and run make sync.",
            ),
            *(
                DiagnosticCheck(
                    name=label,
                    detail=installed[distribution] or "not installed",
                    passed=versions_match,
                    action=None
                    if versions_match
                    else "Install all four MarketSieve distributions at the same version.",
                )
                for label, distribution in SUITE_DISTRIBUTIONS
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
