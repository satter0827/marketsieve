"""MarketSieve command-line entry point."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from marketsieve_cli.bootstrap import (
    build_console_output,
    build_diagnostics_service,
    build_snapshot_service,
    sdk_version,
)

OUTPUT_CHOICES = ("auto", "rich", "text", "json")
CAPABILITIES_SCHEMA_VERSION = "2.0.0"
COMMAND_METADATA = {
    "capabilities": {
        "output_schema": "urn:marketsieve:schema:capabilities-result:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "doctor": {
        "output_schema": "urn:marketsieve:schema:doctor-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["log_file"]},
    },
    "report": {
        "output_schema": "urn:marketsieve:schema:report-result:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["log_file"]},
    },
    "compare": {
        "output_schema": "urn:marketsieve:schema:comparison-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "source list": {
        "output_schema": "urn:marketsieve:schema:source-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "source import": {
        "output_schema": "urn:marketsieve:schema:source-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["snapshot"]},
    },
    "source doctor": {
        "output_schema": "urn:marketsieve:schema:source-result:1.0.0",
        "effects": {"network": False, "secrets": True, "optional_writes": []},
    },
    "source fetch": {
        "output_schema": "urn:marketsieve:schema:source-result:1.0.0",
        "effects": {"network": True, "secrets": True, "optional_writes": ["snapshot"]},
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
        "output_schema": "urn:marketsieve:schema:inspect-result:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    **{
        f"analyze {name}": {
            "output_schema": "urn:marketsieve:schema:indicator-result:1.0.0",
            "effects": {"network": False, "secrets": False, "optional_writes": []},
        }
        for name in (
            "atr",
            "ema",
            "macd",
            "maximum-drawdown",
            "period-return",
            "rsi",
            "sma",
        )
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
        locale=context.obj["locale"],
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
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Use this non-secret TOML configuration file.",
)
@click.option(
    "--locale",
    type=click.Choice(("ja", "en")),
    default="ja",
    show_default=True,
    help="表示言語を選択します。JSONのキーは変わりません。",
)
@click.pass_context
def main(
    context: click.Context,
    log_level: str | None,
    log_file: bool,
    config_path: Path | None,
    locale: str,
) -> None:
    """Analyze Japanese and U.S. equities with reproducible evidence."""

    context.ensure_object(dict)
    context.obj["log_level"] = log_level.upper() if log_level else None
    context.obj["log_file"] = log_file
    context.obj["config_path"] = config_path
    context.obj["locale"] = locale
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
@click.argument("instrument")
@click.option("--source-profile", required=True, help="Select the exact stored source profile.")
@click.option(
    "--format",
    "report_format",
    type=click.Choice(("rich", "text", "json")),
    default="text",
    show_default=True,
)
@output_option
@click.pass_context
def report(
    context: click.Context,
    instrument: str,
    source_profile: str,
    report_format: str,
    output_mode: str,
) -> None:
    """Project one stored equity view as a durable offline report."""

    selected_output = report_format if output_mode == "auto" else output_mode
    console = _console(context, selected_output)
    try:
        document = build_snapshot_service(context.obj["config_path"]).report(
            instrument, source_profile
        )
    except (LookupError, RuntimeError, TypeError, ValueError, OSError) as error:
        console.emit_error("report_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Equity report")


@main.command()
@click.argument("instruments", nargs=-1, required=True)
@click.option("--source-profile", required=True, help="Select the exact stored source profile.")
@output_option
@click.pass_context
def compare(
    context: click.Context,
    instruments: tuple[str, ...],
    source_profile: str,
    output_mode: str,
) -> None:
    """Compare stored equity views at one explicit knowledge horizon."""

    if len(instruments) < 2:
        raise click.UsageError("comparison requires at least two instruments")
    console = _console(context, output_mode)
    try:
        document = build_snapshot_service(context.obj["config_path"]).compare(
            instruments, source_profile
        )
    except (LookupError, RuntimeError, TypeError, ValueError, OSError) as error:
        console.emit_error("compare_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Equity comparison")


@main.group()
def source() -> None:
    """Inspect installed sources and explicitly import local data."""


@source.command("list")
@output_option
@click.pass_context
def source_list(context: click.Context, output_mode: str) -> None:
    """List source package metadata without loading plugin code."""

    _console(context, output_mode).emit_document(
        build_snapshot_service(context.obj["config_path"]).sources(), title="Installed sources"
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
        document = build_snapshot_service(context.obj["config_path"]).import_bundle(path, plugin)
    except (LookupError, RuntimeError, TypeError, ValueError, OSError) as error:
        console.emit_error("source_import_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Imported snapshot")


@source.command("doctor")
@click.argument("source_profile")
@click.option(
    "--kind",
    type=click.Choice(("daily_bars", "financials", "events")),
    default="daily_bars",
    show_default=True,
)
@output_option
@click.pass_context
def source_doctor(context: click.Context, source_profile: str, kind: str, output_mode: str) -> None:
    """Check one configured source without making a network request."""

    console = _console(context, output_mode)
    try:
        document = build_snapshot_service(context.obj["config_path"]).doctor_source(
            source_profile, kind
        )
    except (LookupError, RuntimeError, TypeError, ValueError, OSError) as error:
        console.emit_error("source_doctor_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Source diagnostics")
    if not document["ready"]:
        raise click.exceptions.Exit(1)


@source.command("fetch")
@click.argument("source_profile")
@click.argument("instrument")
@click.option("--start", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
@click.option("--end", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
@click.option(
    "--adjustment",
    type=click.Choice(("raw", "adjusted")),
    default="raw",
    show_default=True,
)
@click.option(
    "--kind",
    type=click.Choice(("daily_bars", "financials", "events")),
    default="daily_bars",
    show_default=True,
)
@output_option
@click.pass_context
def source_fetch(
    context: click.Context,
    source_profile: str,
    instrument: str,
    start: datetime,
    end: datetime,
    adjustment: str,
    kind: str,
    output_mode: str,
) -> None:
    """Fetch one exact range and persist an immutable normalized snapshot."""

    console = _console(context, output_mode)
    try:
        document = build_snapshot_service(context.obj["config_path"]).fetch(
            source_profile, instrument, start.date(), end.date(), adjustment, kind
        )
    except (LookupError, RuntimeError, TypeError, ValueError, OSError) as error:
        console.emit_error("source_fetch_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Fetched snapshot")


@main.group()
def snapshot() -> None:
    """List, show, and verify immutable snapshots."""


@snapshot.command("list")
@output_option
@click.pass_context
def snapshot_list(context: click.Context, output_mode: str) -> None:
    """List locally stored snapshots."""

    _console(context, output_mode).emit_document(
        build_snapshot_service(context.obj["config_path"]).snapshots(), title="Snapshots"
    )


@snapshot.command("show")
@click.argument("object_id")
@output_option
@click.pass_context
def snapshot_show(context: click.Context, object_id: str, output_mode: str) -> None:
    """Show one snapshot manifest."""

    _snapshot_read(
        context,
        output_mode,
        "Snapshot",
        lambda: build_snapshot_service(context.obj["config_path"]).show(object_id),
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
        lambda: build_snapshot_service(context.obj["config_path"]).verify(object_id),
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
        document = build_snapshot_service(context.obj["config_path"]).inspect(
            instrument, source_profile
        )
    except (LookupError, TypeError, ValueError, OSError) as error:
        console.emit_error("inspect_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Equity inspection")


@main.group()
def analyze() -> None:
    """Calculate one deterministic technical indicator offline."""


def _run_analysis(
    context: click.Context,
    output_mode: str,
    instrument: str,
    source_profile: str,
    indicator: str,
    parameters: dict[str, int],
) -> None:
    console = _console(context, output_mode)
    try:
        document = build_snapshot_service(context.obj["config_path"]).analyze(
            instrument, source_profile, indicator, **parameters
        )
    except (LookupError, RuntimeError, TypeError, ValueError, OSError) as error:
        console.emit_error("analyze_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Indicator analysis")


def period_option(default: int) -> Callable[[Any], Any]:
    return click.option(
        "--period",
        type=click.IntRange(min=1),
        default=default,
        show_default=True,
    )


def _period_analysis(
    context: click.Context,
    instrument: str,
    source_profile: str,
    period: int,
    output_mode: str,
    indicator: str,
) -> None:
    _run_analysis(context, output_mode, instrument, source_profile, indicator, {"period": period})


@analyze.command("sma")
@click.argument("instrument")
@period_option(20)
@click.option("--source-profile", required=True)
@output_option
@click.pass_context
def analyze_sma(
    context: click.Context, instrument: str, period: int, source_profile: str, output_mode: str
) -> None:
    """Calculate a simple moving average."""

    _period_analysis(context, instrument, source_profile, period, output_mode, "sma")


@analyze.command("ema")
@click.argument("instrument")
@period_option(20)
@click.option("--source-profile", required=True)
@output_option
@click.pass_context
def analyze_ema(
    context: click.Context, instrument: str, period: int, source_profile: str, output_mode: str
) -> None:
    """Calculate an exponential moving average."""

    _period_analysis(context, instrument, source_profile, period, output_mode, "ema")


@analyze.command("rsi")
@click.argument("instrument")
@period_option(14)
@click.option("--source-profile", required=True)
@output_option
@click.pass_context
def analyze_rsi(
    context: click.Context, instrument: str, period: int, source_profile: str, output_mode: str
) -> None:
    """Calculate Wilder's relative strength index."""

    _period_analysis(context, instrument, source_profile, period, output_mode, "rsi")


@analyze.command("atr")
@click.argument("instrument")
@period_option(14)
@click.option("--source-profile", required=True)
@output_option
@click.pass_context
def analyze_atr(
    context: click.Context, instrument: str, period: int, source_profile: str, output_mode: str
) -> None:
    """Calculate Wilder's average true range."""

    _period_analysis(context, instrument, source_profile, period, output_mode, "atr")


@analyze.command("period-return")
@click.argument("instrument")
@period_option(20)
@click.option("--source-profile", required=True)
@output_option
@click.pass_context
def analyze_period_return(
    context: click.Context, instrument: str, period: int, source_profile: str, output_mode: str
) -> None:
    """Calculate simple return over a closing-price period."""

    _period_analysis(context, instrument, source_profile, period, output_mode, "period_return")


@analyze.command("maximum-drawdown")
@click.argument("instrument")
@period_option(252)
@click.option("--source-profile", required=True)
@output_option
@click.pass_context
def analyze_maximum_drawdown(
    context: click.Context, instrument: str, period: int, source_profile: str, output_mode: str
) -> None:
    """Calculate maximum peak-relative drawdown over a period."""

    _period_analysis(context, instrument, source_profile, period, output_mode, "maximum_drawdown")


@analyze.command("macd")
@click.argument("instrument")
@click.option("--fast-period", type=click.IntRange(min=1), default=12, show_default=True)
@click.option("--slow-period", type=click.IntRange(min=1), default=26, show_default=True)
@click.option("--signal-period", type=click.IntRange(min=1), default=9, show_default=True)
@click.option("--source-profile", required=True)
@output_option
@click.pass_context
def analyze_macd(
    context: click.Context,
    instrument: str,
    fast_period: int,
    slow_period: int,
    signal_period: int,
    source_profile: str,
    output_mode: str,
) -> None:
    """Calculate MACD, signal, and histogram values."""

    _run_analysis(
        context,
        output_mode,
        instrument,
        source_profile,
        "macd",
        {
            "fast_period": fast_period,
            "slow_period": slow_period,
            "signal_period": signal_period,
        },
    )


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
