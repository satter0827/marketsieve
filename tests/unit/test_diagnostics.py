import logging
from importlib.metadata import PackageNotFoundError

import pytest

import marketsieve_cli.application.diagnostics as diagnostics_module
from marketsieve_cli.application.diagnostics import DiagnosticsService

LOGGER = logging.getLogger("marketsieve.tests.diagnostics")


def test_supported_python_is_ready() -> None:
    service = DiagnosticsService(logger=LOGGER, python_version=(3, 13, 0))
    checks = service.collect()

    assert service.succeeded(checks)
    assert checks[0].detail == "3.13.0"


def test_unsupported_python_is_not_ready() -> None:
    service = DiagnosticsService(logger=LOGGER, python_version=(3, 15, 0))
    checks = service.collect()

    assert not service.succeeded(checks)
    assert not checks[0].passed


def test_missing_application_distribution_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_version(_: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(diagnostics_module, "version", missing_version)
    service = DiagnosticsService(logger=LOGGER, python_version=(3, 13, 0))

    checks = service.collect()

    assert all(check.detail == "not installed" for check in checks[1:])
    assert all(not check.passed for check in checks[1:])


def test_mixed_suite_versions_are_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {
        "marketsieve": "1.0.0rc3",
        "marketsieve-extension-api": "1.0.0rc3",
        "marketsieve-source-yfinance": "1.0.0rc2",
        "marketsieve-cli": "1.0.0rc3",
    }
    monkeypatch.setattr(diagnostics_module, "version", versions.__getitem__)

    checks = DiagnosticsService(logger=LOGGER, python_version=(3, 13, 0)).collect()

    assert not DiagnosticsService(logger=LOGGER).succeeded(checks)
    assert all(not check.passed for check in checks[1:])
    assert all("same version" in (check.action or "") for check in checks[1:])
