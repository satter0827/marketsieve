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

    assert checks[-1].detail == "not installed"
    assert not checks[-1].passed
