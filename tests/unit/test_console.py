from __future__ import annotations

from io import StringIO

from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.application.diagnostics import DiagnosticCheck


class TerminalBuffer(StringIO):
    def isatty(self) -> bool:
        return True


def console(
    mode: OutputMode, *, terminal: bool = False, locale: str = "en"
) -> tuple[ConsoleOutput, StringIO, StringIO]:
    stdout = TerminalBuffer() if terminal else StringIO()
    stderr = StringIO()
    return (
        ConsoleOutput(mode, stdout=stdout, stderr=stderr, width=80, locale=locale),
        stdout,
        stderr,
    )


def test_japanese_text_localizes_human_labels_only() -> None:
    output, stdout, _ = console(OutputMode.TEXT, locale="ja")

    output.emit_document(
        {"schema_version": "2.0.0", "sections": {"price": {"status": "available"}}},
        title="Equity inspection",
    )

    assert "スキーマ版" in stdout.getvalue()
    assert "価格" in stdout.getvalue()
    assert "利用可能" in stdout.getvalue()


def test_auto_mode_selects_rich_for_a_terminal_landing() -> None:
    output, stdout, _ = console(OutputMode.AUTO, terminal=True)

    output.emit_landing("0.1.0")

    assert output.mode is OutputMode.RICH
    assert "MarketSieve 0.1.0" in stdout.getvalue()
    assert "Quick start" not in stdout.getvalue()


def test_rich_doctor_shows_failure_and_recovery_action() -> None:
    output, stdout, _ = console(OutputMode.RICH)

    output.emit_doctor(
        (
            DiagnosticCheck("Python", "3.13", True),
            DiagnosticCheck("Application", "missing", False, "Run make sync."),
        )
    )

    rendered = stdout.getvalue()
    assert "PASS" in rendered
    assert "FAIL" in rendered
    assert "Run make sync." in rendered
    assert "Not ready" in rendered


def test_capabilities_support_text_and_rich_projections() -> None:
    payload = {
        "commands": [
            {"name": "report", "summary": "Generate a report.", "output_schema": "urn:test"}
        ]
    }
    text_output, text_stdout, _ = console(OutputMode.TEXT)
    rich_output, rich_stdout, _ = console(OutputMode.RICH)

    text_output.emit_capabilities(payload)
    rich_output.emit_capabilities(payload)

    assert text_stdout.getvalue() == "report: Generate a report.\n"
    assert "CLI capabilities" in rich_stdout.getvalue()
    assert "urn:test" in rich_stdout.getvalue()


def test_errors_follow_the_selected_output_contract() -> None:
    text_output, _, text_stderr = console(OutputMode.TEXT)
    rich_output, _, rich_stderr = console(OutputMode.RICH)
    json_output, _, json_stderr = console(OutputMode.JSON)

    text_output.emit_error("failed", "Try again.")
    rich_output.emit_error("failed", "Try again.")
    json_output.emit_error("failed", "Try again.")

    assert text_stderr.getvalue() == "ERROR failed: Try again.\n"
    assert "Error" in rich_stderr.getvalue()
    assert '"error":"failed"' in json_stderr.getvalue()
