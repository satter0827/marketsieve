from marketsieve_app.application.diagnostics import DiagnosticsService


def test_supported_python_is_ready() -> None:
    service = DiagnosticsService(python_version=(3, 13, 0))
    checks = service.collect()

    assert service.succeeded(checks)
    assert checks[0].detail == "3.13.0"


def test_unsupported_python_is_not_ready() -> None:
    service = DiagnosticsService(python_version=(3, 15, 0))
    checks = service.collect()

    assert not service.succeeded(checks)
    assert not checks[0].passed
