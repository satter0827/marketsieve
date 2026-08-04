"""MarketSieve command-line entry point."""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from marketsieve_cli.bootstrap import (
    build_console_output,
    build_diagnostics_service,
    build_report_service,
    sdk_version,
)

OUTPUT_CHOICES = ("auto", "rich", "text", "json")
CAPABILITIES_SCHEMA_VERSION = "1.0.0"
COMMAND_METADATA = {
    "capabilities": {
        "output_schema": "urn:marketsieve:schema:capabilities-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "doctor": {
        "output_schema": "urn:marketsieve:schema:doctor-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["log_file"]},
    },
    "report": {
        "output_schema": "urn:marketsieve:schema:report-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["log_file"]},
    },
}


def output_option(function: Any) -> Any:
    """Add the shared console-output selector."""

    return click.option(
        "--output",
        "output_mode",
        type=click.Choice(OUTPUT_CHOICES),
        default="auto",
        show_default=True,
        help="Choose automatic, styled, plain-text, or JSON output.",
    )(function)


def _console(context: click.Context, output_mode: str) -> Any:
    return build_console_output(
        output_mode,
        stdout=click.get_text_stream("stdout"),
        stderr=click.get_text_stream("stderr"),
    )


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(version=sdk_version(), prog_name="marketsieve")
@click.option(
    "--log-level",
    type=click.Choice(("DEBUG", "INFO", "WARNING", "ERROR"), case_sensitive=False),
    default=None,
    help="Emit structured JSON Lines logs to stderr at this level.",
)
@click.option("--log-file", is_flag=True, help="Also write logs below .marketsieve/logs.")
@click.pass_context
def main(context: click.Context, log_level: str | None, log_file: bool) -> None:
    """Analyze Japanese and U.S. equities with reproducible evidence."""

    context.ensure_object(dict)
    context.obj["log_level"] = log_level.upper() if log_level else None
    context.obj["log_file"] = log_file
    if context.invoked_subcommand is None:
        _console(context, "auto").emit_landing(sdk_version())


@main.command()
@output_option
@click.pass_context
def doctor(context: click.Context, output_mode: str) -> None:
    """Check whether the local environment is ready."""

    console = _console(context, output_mode)
    service = build_diagnostics_service(
        level=context.obj["log_level"], write_log_file=context.obj["log_file"]
    )
    checks = service.collect()
    console.emit_doctor(checks)
    if not service.succeeded(checks):
        raise click.exceptions.Exit(1)


@main.command()
@click.option("--market", type=click.Choice(("jp", "us", "all")), default="all", show_default=True)
@output_option
@click.pass_context
def report(context: click.Context, market: str, output_mode: str) -> None:
    """Generate an evidence-backed historical SMA20 report."""

    console = _console(context, output_mode)
    service = build_report_service(
        console,
        level=context.obj["log_level"],
        write_log_file=context.obj["log_file"],
    )
    try:
        service.run(market)
    except (RuntimeError, TypeError, ValueError) as error:
        console.emit_error("report_failed", str(error))
        raise click.exceptions.Exit(1) from None


def capabilities_document() -> dict[str, Any]:
    """Describe the real Click command surface and its operational contract."""

    def option_payload(parameter: click.Option) -> dict[str, Any]:
        choices = list(parameter.type.choices) if isinstance(parameter.type, click.Choice) else None
        return {
            "name": parameter.name,
            "flags": list(parameter.opts),
            "required": parameter.required,
            "default": parameter.default,
            "choices": choices,
        }

    global_options = [
        option_payload(parameter)
        for parameter in main.params
        if isinstance(parameter, click.Option) and parameter.name != "version"
    ]
    commands = []
    for name, command in sorted(main.commands.items()):
        options = []
        for parameter in command.params:
            if not isinstance(parameter, click.Option):
                continue
            options.append(option_payload(parameter))
        metadata = COMMAND_METADATA[name]
        commands.append(
            {
                "name": name,
                "summary": command.help or "",
                "options": options,
                "output_schema": metadata["output_schema"],
                "effects": metadata["effects"],
            }
        )
    return {
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "program": "marketsieve",
        "version": sdk_version(),
        "global_options": global_options,
        "commands": commands,
        "streams": {
            "success": "stdout",
            "errors": "stderr",
            "structured_logs": "stderr_when_requested",
        },
        "exit_codes": [
            {"code": 0, "meaning": "success"},
            {"code": 1, "meaning": "runtime_data_or_contract_error"},
            {"code": 2, "meaning": "invalid_cli_usage"},
        ],
    }


@main.command()
@output_option
@click.pass_context
def capabilities(context: click.Context, output_mode: str) -> None:
    """Describe commands, schemas, exit codes, and side effects."""

    _console(context, output_mode).emit_capabilities(capabilities_document())


def _json_output_requested(arguments: list[str]) -> bool:
    return any(
        argument == "--output=json"
        or (
            argument == "--output" and index + 1 < len(arguments) and arguments[index + 1] == "json"
        )
        for index, argument in enumerate(arguments)
    )


def entrypoint() -> None:
    """Run Click while preserving the machine-readable usage-error contract."""

    arguments = sys.argv[1:]
    try:
        exit_code = main.main(args=arguments, prog_name="marketsieve", standalone_mode=False)
    except click.ClickException as error:
        if _json_output_requested(arguments):
            payload = {
                "schema_version": "1.0.0",
                "error": "invalid_cli_usage",
                "message": error.format_message(),
            }
            click.echo(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                err=True,
            )
        else:
            error.show()
        raise SystemExit(error.exit_code) from None
    raise SystemExit(exit_code or 0)
