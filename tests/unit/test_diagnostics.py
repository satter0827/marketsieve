from marketsieve_app.diagnostics import collect_diagnostics, diagnostics_succeeded


def test_supported_python_is_ready() -> None:
    checks = collect_diagnostics(python_version=(3, 13, 0))

    assert diagnostics_succeeded(checks)
    assert checks[0].detail == "3.13.0"


def test_unsupported_python_is_not_ready() -> None:
    checks = collect_diagnostics(python_version=(3, 15, 0))

    assert not diagnostics_succeeded(checks)
    assert not checks[0].passed
