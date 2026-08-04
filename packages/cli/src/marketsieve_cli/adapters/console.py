"""Rich, plain-text, and JSON console projections."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any, TextIO

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from marketsieve_cli.application.diagnostics import DiagnosticCheck
from marketsieve_cli.application.report import ReportDocument, serialize_report_document

DOCTOR_SCHEMA_VERSION = "1.0.0"
CAPABILITIES_SCHEMA_VERSION = "1.0.0"
ERROR_SCHEMA_VERSION = "1.0.0"
DISCLAIMER = "Observed market-data conditions; not investment advice."


class OutputMode(StrEnum):
    """Supported console projections."""

    AUTO = "auto"
    RICH = "rich"
    TEXT = "text"
    JSON = "json"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def doctor_document(checks: tuple[DiagnosticCheck, ...]) -> dict[str, Any]:
    """Build the machine-readable diagnostics document."""

    ready = all(check.passed for check in checks)
    return {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "checks": [
            {
                "name": check.name,
                "detail": check.detail,
                "status": "pass" if check.passed else "fail",
                "action": check.action,
            }
            for check in checks
        ],
        "status": "ready" if ready else "not_ready",
    }


class ConsoleOutput:
    """Write application documents without changing their semantics."""

    def __init__(
        self,
        mode: OutputMode,
        *,
        stdout: TextIO,
        stderr: TextIO,
        width: int | None = None,
    ) -> None:
        self._requested = mode
        self._mode = self._resolve(mode, stdout)
        self._stdout = stdout
        self._stderr = stderr
        self._console = Console(
            file=stdout,
            width=width,
            force_terminal=self._mode is OutputMode.RICH,
            no_color=None,
            safe_box=True,
        )
        self._error_console = Console(file=stderr, force_terminal=self._mode is OutputMode.RICH)

    @staticmethod
    def _resolve(mode: OutputMode, stream: TextIO) -> OutputMode:
        if mode is not OutputMode.AUTO:
            return mode
        return OutputMode.RICH if stream.isatty() else OutputMode.TEXT

    @property
    def mode(self) -> OutputMode:
        return self._mode

    def emit_landing(self, version: str) -> None:
        if self._mode is OutputMode.RICH:
            body = Text.from_markup(
                "[bold]Reproducible Japanese and U.S. equity analysis[/bold]\n"
                "Offline by default. Evidence attached.\n\n"
                "[cyan]marketsieve doctor[/cyan]\n"
                "[cyan]marketsieve report --market all[/cyan]\n"
                "[cyan]marketsieve capabilities --output json[/cyan]"
            )
            self._console.print(Panel(body, title=f"MarketSieve {version}", border_style="cyan"))
            return
        self._stdout.write(
            f"MarketSieve {version}\n"
            "Reproducible Japanese and U.S. equity analysis. Offline by default.\n"
            "Quick start:\n"
            "  marketsieve doctor\n"
            "  marketsieve report --market all\n"
            "  marketsieve capabilities --output json\n"
        )

    def emit_doctor(self, checks: tuple[DiagnosticCheck, ...]) -> None:
        document = doctor_document(checks)
        if self._mode is OutputMode.JSON:
            self._stdout.write(_json(document) + "\n")
            return
        if self._mode is OutputMode.TEXT:
            for check in document["checks"]:
                self._stdout.write(
                    f"{check['status'].upper()} {check['name']}: {check['detail']}\n"
                )
                if check["action"]:
                    self._stdout.write(f"ACTION {check['action']}\n")
            self._stdout.write(f"STATUS {document['status'].replace('_', ' ').title()}\n")
            return
        table = Table(title="Environment diagnostics", box=box.ROUNDED, expand=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Check")
        table.add_column("Detail")
        for check in document["checks"]:
            passed = check["status"] == "pass"
            table.add_row(
                "[bold green]PASS[/]" if passed else "[bold red]FAIL[/]",
                check["name"],
                check["detail"],
            )
            if check["action"]:
                table.add_row("", "Action", check["action"], style="yellow")
        self._console.print(table)
        ready = document["status"] == "ready"
        self._console.print(
            Panel(
                "[bold green]Ready[/]" if ready else "[bold red]Not ready[/]",
                border_style="green" if ready else "red",
            )
        )

    def emit_report(self, document: ReportDocument) -> None:
        payload = serialize_report_document(document)
        if self._mode is OutputMode.JSON:
            self._stdout.write(_json(payload) + "\n")
            return
        if self._mode is OutputMode.TEXT:
            self._emit_report_text(payload)
            return
        self._emit_report_rich(payload)

    def _emit_report_text(self, payload: dict[str, Any]) -> None:
        for item in payload["reports"]:
            latest = item["latest"]
            state = latest["current_state"] or latest["status"]
            self._stdout.write(
                f"{item['market'].upper()} {item['instrument']['mic']}:"
                f"{item['instrument']['symbol']} date={latest['current_date']} "
                f"close={latest['current_close']} sma20={latest['current_sma']} "
                f"state={state} transitions={len(item['transitions'])}\n"
            )
            for transition in item["transitions"]:
                self._stdout.write(
                    f"TRANSITION {transition['trading_date']} "
                    f"{transition['previous_state']}->{transition['current_state']} "
                    f"evidence={transition['evidence_id']}\n"
                )
            self._stdout.write(f"REPORT {item['report_id']}\n")
            self._stdout.write(f"LATEST_EVIDENCE {latest['evidence_id']}\n")
        self._stdout.write(f"NOTICE {DISCLAIMER}\n")

    def _emit_report_rich(self, payload: dict[str, Any]) -> None:
        reports = payload["reports"]
        markets = ", ".join(item["market"].upper() for item in reports)
        first = min(item["input"]["start"] for item in reports)
        last = max(item["input"]["end"] for item in reports)
        last_as_of = max(
            datetime.fromisoformat(item["input"]["last_as_of"]) for item in reports
        ).isoformat()
        self._console.print(
            Panel(
                f"Markets: [bold]{markets}[/]\nPeriod: {first} to {last}\nAs of: {last_as_of}",
                title="MarketSieve Report",
                border_style="cyan",
            )
        )
        summary = Table(box=box.ROUNDED, expand=True)
        for heading in ("Market", "Instrument", "Date", "Close", "SMA20", "State", "Changes"):
            summary.add_column(heading, no_wrap=heading in {"Market", "Date", "State"})
        state_styles = {"above": "green", "below": "red", "equal": "yellow"}
        for item in reports:
            latest = item["latest"]
            state = latest["current_state"] or latest["status"]
            style = state_styles.get(state, "dim")
            summary.add_row(
                item["market"].upper(),
                f"{item['instrument']['mic']}:{item['instrument']['symbol']}",
                latest["current_date"] or "-",
                latest["current_close"] or "-",
                latest["current_sma"] or "-",
                f"[{style}]{state}[/]",
                str(len(item["transitions"])),
            )
        self._console.print(summary)
        for item in reports:
            transitions = item["transitions"]
            if transitions:
                table = Table(title=f"{item['market'].upper()} state changes", box=box.SIMPLE_HEAVY)
                table.add_column("Date")
                table.add_column("Change")
                table.add_column("Evidence")
                for transition in transitions:
                    table.add_row(
                        transition["trading_date"],
                        f"{transition['previous_state']} → {transition['current_state']}",
                        transition["evidence_id"],
                    )
                self._console.print(table)
            evidence = (
                f"Report: {item['report_id']}\n"
                f"Replay: {item['replay_id']}\n"
                f"Latest evidence: {item['latest']['evidence_id']}"
            )
            if transitions:
                evidence += "\nTransition evidence:\n" + "\n".join(
                    transition["evidence_id"] for transition in transitions
                )
            self._console.print(Panel(evidence, title=f"{item['market'].upper()} evidence"))
        self._console.print(f"[dim]{DISCLAIMER}[/]")

    def emit_capabilities(self, payload: dict[str, Any]) -> None:
        if self._mode is OutputMode.JSON:
            self._stdout.write(_json(payload) + "\n")
            return
        if self._mode is OutputMode.TEXT:
            for command in payload["commands"]:
                self._stdout.write(f"{command['name']}: {command['summary']}\n")
            return
        table = Table(title="CLI capabilities", box=box.ROUNDED, expand=True)
        table.add_column("Command")
        table.add_column("Purpose")
        table.add_column("Output schema")
        for command in payload["commands"]:
            table.add_row(command["name"], command["summary"], command["output_schema"] or "-")
        self._console.print(table)

    def emit_error(self, code: str, message: str) -> None:
        if self._mode is OutputMode.JSON:
            payload = {"schema_version": ERROR_SCHEMA_VERSION, "error": code, "message": message}
            self._stderr.write(_json(payload) + "\n")
            return
        if self._mode is OutputMode.RICH:
            self._error_console.print(Panel(message, title="Error", border_style="red"))
            return
        self._stderr.write(f"ERROR {code}: {message}\n")
