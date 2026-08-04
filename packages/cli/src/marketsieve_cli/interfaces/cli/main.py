"""MarketSieve command-line entry point."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from marketsieve_cli.bootstrap import (
    build_console_output,
    build_diagnostics_service,
    build_report_service,
    build_snapshot_service,
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
    "source list": {
        "output_schema": "urn:marketsieve:schema:source-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "source import": {
        "output_schema": "urn:marketsieve:schema:source-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["snapshot"]},
    },
    "snapshot list": {
        "output_schema": "urn:marketsieve:schema:snapshot-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "snapshot show": {
        "output_schema": "urn:marketsieve:schema:snapshot-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "snapshot verify": {
        "output_schema": "urn:marketsieve:schema:snapshot-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "inspect": {
        "output_schema": "urn:marketsieve:schema:inspect-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
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


@main.group()
def source() -> None:
    """Inspect installed sources and explicitly import local data."""


@source.command("list")
@output_option
@click.pass_context
def source_list(context: click.Context, output_mode: str) -> None:
    """List source package metadata without loading plugin code."""

    _console(context, output_mode).emit_document(
        build_snapshot_service().sources(), title="Installed sources"
    )


@source.command("import")
@click.argument("path", type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.option("--plugin", default="csv", show_default=True, help="Select one installed source.")
@output_option
@click.pass_context
def source_import(context: click.Context, path: Path, plugin: str, output_mode: str) -> None:
    """Import one local dataset bundle into immutable storage."""

    console = _console(context, output_mode)
    try:
        document = build_snapshot_service().import_bundle(path, plugin)
    except (LookupError, RuntimeError, TypeError, ValueError, OSError) as error:
        console.emit_error("source_import_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Imported snapshot")


@main.group()
def snapshot() -> None:
    """List, show, and verify immutable snapshots."""


@snapshot.command("list")
@output_option
@click.pass_context
def snapshot_list(context: click.Context, output_mode: str) -> None:
    """List locally stored snapshots."""

    _console(context, output_mode).emit_document(
        build_snapshot_service().snapshots(), title="Snapshots"
    )


@snapshot.command("show")
@click.argument("object_id")
@output_option
@click.pass_context
def snapshot_show(context: click.Context, object_id: str, output_mode: str) -> None:
    """Show one snapshot manifest."""

    _snapshot_read(
        context, output_mode, "Snapshot", lambda: build_snapshot_service().show(object_id)
    )


@snapshot.command("verify")
@click.argument("object_id")
@output_option
@click.pass_context
def snapshot_verify(context: click.Context, object_id: str, output_mode: str) -> None:
    """Verify one snapshot's checksums and content identity."""

    _snapshot_read(
        context,
        output_mode,
        "Snapshot verification",
        lambda: build_snapshot_service().verify(object_id),
    )


def _snapshot_read(
    context: click.Context,
    output_mode: str,
    title: str,
    operation: Callable[[], dict[str, Any]],
) -> None:
    console = _console(context, output_mode)
    try:
        document = operation()
    except (LookupError, TypeError, ValueError, OSError) as error:
        console.emit_error("snapshot_read_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title=title)


@main.command()
@click.argument("instrument")
@click.option("--source-profile", required=True, help="Select the exact stored source profile.")
@output_option
@click.pass_context
def inspect(context: click.Context, instrument: str, source_profile: str, output_mode: str) -> None:
    """Inspect available and missing equity sections offline."""

    if instrument.count(":") != 1:
        raise click.UsageError("instrument must use MIC:SYMBOL form")
    console = _console(context, output_mode)
    try:
        document = build_snapshot_service().inspect(instrument, source_profile)
    except (LookupError, TypeError, ValueError, OSError) as error:
        console.emit_error("inspect_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Equity inspection")


def capabilities_document() -> dict[str, Any]:
    """Describe the real Click command surface and its operational contract."""

    def option_payload(parameter: click.Option) -> dict[str, Any]:
        choices = list(parameter.type.choices) if isinstance(parameter.type, click.Choice) else None
        default = parameter.default
        if not isinstance(default, (str, int, float, bool, list, dict, type(None))):
            default = None
        return {
            "name": parameter.name,
            "flags": list(parameter.opts),
            "required": parameter.required,
            "default": default,
            "choices": choices,
        }

    global_options = [
        option_payload(parameter)
        for parameter in main.params
        if isinstance(parameter, click.Option) and parameter.name != "version"
    ]

    def leaf_commands(group: click.Group, prefix: str = "") -> list[tuple[str, click.Command]]:
        leaves: list[tuple[str, click.Command]] = []
        for name, command in sorted(group.commands.items()):
            qualified = f"{prefix} {name}".strip()
            if isinstance(command, click.Group):
                leaves.extend(leaf_commands(command, qualified))
            else:
                leaves.append((qualified, command))
        return leaves

    commands = []
    for name, command in leaf_commands(main):
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
