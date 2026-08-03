"""Offline diagnostics for the repository-local application."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from marketsieve import __version__ as sdk_version


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """One deterministic diagnostic result."""

    name: str
    detail: str
    passed: bool


def collect_diagnostics(
    *,
    python_version: tuple[int, int, int] | None = None,
) -> tuple[DiagnosticCheck, ...]:
    """Return local checks without reading secrets or contacting external services."""

    detected_python = python_version or sys.version_info[:3]
    supported_python = (3, 12) <= detected_python[:2] < (3, 15)

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
            passed=supported_python,
        ),
        DiagnosticCheck(name="MarketSieve SDK", detail=sdk_version, passed=True),
        DiagnosticCheck(
            name="MarketSieve application",
            detail=application_version,
            passed=application_installed,
        ),
    )


def diagnostics_succeeded(checks: tuple[DiagnosticCheck, ...]) -> bool:
    """Return whether every diagnostic passed."""

    return all(check.passed for check in checks)
