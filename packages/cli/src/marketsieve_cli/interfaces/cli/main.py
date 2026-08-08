"""MarketSieve command-line entry point."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import click

from marketsieve_cli.bootstrap import (
    add_watchlist_instrument,
    build_console_output,
    build_daily_brief_service,
    build_diagnostics_service,
    build_experiment_service,
    build_security_research,
    build_snapshot_service,
    build_weekly_brief_service,
    compare_market_snapshot_securities,
    import_portfolio,
    list_decision_reports,
    list_market_snapshots,
    list_security_research,
    project_decision_report,
    query_market_snapshot,
    read_decision_report,
    read_market_snapshot_security,
    read_portfolio,
    read_watchlist,
    refresh_market_snapshot,
    remove_watchlist_instrument,
    render_decision_report,
    sdk_version,
    show_market_snapshot,
    show_security_research,
)

OUTPUT_CHOICES = ("auto", "rich", "text", "json")
MARKET_INDEX_CHOICES = ("dow30", "nasdaq100", "nikkei225", "sp500", "topix500")
CAPABILITIES_SCHEMA_VERSION = "4.0.0"
COMMAND_METADATA: dict[str, dict[str, Any]] = {
    "market refresh": {
        "output_schema": "urn:marketsieve:schema:market-snapshot:2.0.0",
        "effects": {
            "network": True,
            "secrets": False,
            "optional_writes": ["market_snapshot_run", "market_snapshot"],
        },
    },
    "market show": {
        "output_schema": "urn:marketsieve:schema:market-snapshot:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "market list": {
        "output_schema": "urn:marketsieve:schema:market-snapshot-list:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "market query": {
        "output_schema": "urn:marketsieve:schema:market-snapshot-query-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "market security": {
        "output_schema": "urn:marketsieve:schema:market-snapshot-security-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "market compare": {
        "output_schema": "urn:marketsieve:schema:market-snapshot-comparison:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "research build": {
        "output_schema": "urn:marketsieve:schema:security-research:1.0.0",
        "effects": {
            "network": True,
            "secrets": False,
            "optional_writes": ["security_research"],
        },
    },
    "research list": {
        "output_schema": "urn:marketsieve:schema:security-research-list:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "research show": {
        "output_schema": "urn:marketsieve:schema:security-research:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "watchlist add": {
        "output_schema": "urn:marketsieve:schema:watchlist-result:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["watchlist"]},
    },
    "watchlist remove": {
        "output_schema": "urn:marketsieve:schema:watchlist-result:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["watchlist"]},
    },
    "watchlist show": {
        "output_schema": "urn:marketsieve:schema:watchlist-result:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "experiment run": {
        "output_schema": "urn:marketsieve:schema:experiment-run:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["experiment"]},
    },
    "experiment show": {
        "output_schema": "urn:marketsieve:schema:experiment-run:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "experiment compare": {
        "output_schema": "urn:marketsieve:schema:experiment-comparison:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "capabilities": {
        "output_schema": "urn:marketsieve:schema:capabilities-result:4.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "doctor": {
        "output_schema": "urn:marketsieve:schema:doctor-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["log_file"]},
    },
    "daily": {
        "output_schema": "urn:marketsieve:schema:decision-report:2.0.0",
        "effects": {"network": True, "secrets": True, "optional_writes": ["snapshot", "report"]},
    },
    "report list": {
        "output_schema": "urn:marketsieve:schema:report-list:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "report show": {
        "output_schema": "urn:marketsieve:schema:decision-report:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "report export": {
        "output_schema": None,
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "portfolio import": {
        "output_schema": "urn:marketsieve:schema:portfolio-result:3.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["portfolio"]},
    },
    "portfolio show": {
        "output_schema": "urn:marketsieve:schema:portfolio-result:3.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "source list": {
        "output_schema": "urn:marketsieve:schema:source-result:1.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": []},
    },
    "weekly": {
        "output_schema": "urn:marketsieve:schema:decision-report:2.0.0",
        "effects": {"network": False, "secrets": False, "optional_writes": ["report"]},
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


@main.group()
def market() -> None:
    """Build and inspect broad yfinance Market Snapshots."""


@market.command("refresh")
@click.option("--resume", "run_id", default=None, help="Resume one matching interrupted run.")
@output_option
@click.pass_context
def market_refresh(context: click.Context, run_id: str | None, output_mode: str) -> None:
    """Acquire all configured index constituents through yfinance."""

    console = _console(context, output_mode)
    try:
        document = refresh_market_snapshot(context.obj["config_path"], resume=run_id)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        console.emit_error("market_refresh_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Market Snapshot")
    if not document["price_requirements_met"]:
        raise click.exceptions.Exit(1)


@market.command("show")
@click.argument("snapshot_id", default="latest")
@output_option
@click.pass_context
def market_show(context: click.Context, snapshot_id: str, output_mode: str) -> None:
    """Show one persisted Market Snapshot and its artifact paths."""

    console = _console(context, output_mode)
    try:
        document = show_market_snapshot(context.obj["config_path"], snapshot_id)
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("market_show_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Market Snapshot")


@market.command("list")
@output_option
@click.pass_context
def market_list(context: click.Context, output_mode: str) -> None:
    """List verified persisted Market Snapshots, newest first."""

    console = _console(context, output_mode)
    try:
        document = list_market_snapshots(context.obj["config_path"])
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("market_list_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Market Snapshots")


def _numeric_bounds(values: tuple[str, ...], option: str) -> dict[str, Decimal]:
    bounds: dict[str, Decimal] = {}
    for value in values:
        field, separator, raw = value.partition("=")
        if not separator or not field or not raw:
            raise ValueError(f"{option} requires FIELD=VALUE")
        if field in bounds:
            raise ValueError(f"{option} contains a duplicate field: {field}")
        try:
            number = Decimal(raw)
        except InvalidOperation as error:
            raise ValueError(f"{option} requires a decimal value: {value}") from error
        if not number.is_finite():
            raise ValueError(f"{option} requires a finite decimal value: {value}")
        bounds[field] = number
    return bounds


@market.command("query")
@click.option("--snapshot", "snapshot_id", default="latest", show_default=True)
@click.option("--market", multiple=True, type=click.Choice(("jp", "us")))
@click.option("--index", "indices", multiple=True, type=click.Choice(MARKET_INDEX_CHOICES))
@click.option("--mic", multiple=True)
@click.option("--exchange", multiple=True)
@click.option("--country", multiple=True)
@click.option("--currency", multiple=True)
@click.option("--sector", multiple=True)
@click.option("--industry", multiple=True)
@click.option("--min", "minimum_values", multiple=True, metavar="FIELD=VALUE")
@click.option("--max", "maximum_values", multiple=True, metavar="FIELD=VALUE")
@click.option("--present", multiple=True)
@click.option("--missing", multiple=True)
@click.option("--fields", multiple=True)
@output_option
@click.pass_context
def market_query(
    context: click.Context,
    snapshot_id: str,
    market: tuple[str, ...],
    indices: tuple[str, ...],
    mic: tuple[str, ...],
    exchange: tuple[str, ...],
    country: tuple[str, ...],
    currency: tuple[str, ...],
    sector: tuple[str, ...],
    industry: tuple[str, ...],
    minimum_values: tuple[str, ...],
    maximum_values: tuple[str, ...],
    present: tuple[str, ...],
    missing: tuple[str, ...],
    fields: tuple[str, ...],
    output_mode: str,
) -> None:
    """Filter one persisted Market Snapshot without network access or recalculation."""

    console = _console(context, output_mode)
    try:
        document = query_market_snapshot(
            context.obj["config_path"],
            snapshot_id,
            filters={
                name: values
                for name, values in {
                    "market": market,
                    "index": indices,
                    "mic": mic,
                    "exchange": exchange,
                    "country": country,
                    "currency": currency,
                    "sector": sector,
                    "industry": industry,
                }.items()
                if values
            },
            minimums=_numeric_bounds(minimum_values, "--min"),
            maximums=_numeric_bounds(maximum_values, "--max"),
            present=present,
            missing=missing,
            fields=fields,
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("market_query_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Market Snapshot query")


@market.command("security")
@click.argument("instrument_id")
@click.option("--snapshot", "snapshot_id", default="latest", show_default=True)
@output_option
@click.pass_context
def market_security(
    context: click.Context, instrument_id: str, snapshot_id: str, output_mode: str
) -> None:
    """Read one computed security without network access."""

    console = _console(context, output_mode)
    try:
        document = read_market_snapshot_security(
            context.obj["config_path"], snapshot_id, instrument_id
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("market_security_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Market Snapshot security")


@market.command("compare")
@click.argument("instrument_ids", nargs=-1, required=True)
@click.option("--snapshot", "snapshot_id", default="latest", show_default=True)
@click.option("--fields", "fields", multiple=True, help="Select one computed field per option.")
@output_option
@click.pass_context
def market_compare(
    context: click.Context,
    instrument_ids: tuple[str, ...],
    snapshot_id: str,
    fields: tuple[str, ...],
    output_mode: str,
) -> None:
    """Compare computed rows without network access or recalculation."""

    console = _console(context, output_mode)
    try:
        document = compare_market_snapshot_securities(
            context.obj["config_path"], snapshot_id, instrument_ids, fields
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("market_compare_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Market Snapshot comparison")


@main.group()
def research() -> None:
    """Build and inspect yfinance research for one Snapshot security."""


@research.command("build")
@click.argument("instrument_id")
@click.option("--snapshot", "snapshot_id", default="latest", show_default=True)
@output_option
@click.pass_context
def research_build(
    context: click.Context, instrument_id: str, snapshot_id: str, output_mode: str
) -> None:
    """Acquire detailed evidence for one security in a Market Snapshot."""

    console = _console(context, output_mode)
    try:
        document = build_security_research(context.obj["config_path"], snapshot_id, instrument_id)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        console.emit_error("research_build_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Security Research Pack")
    if not document["price_requirements_met"]:
        raise click.exceptions.Exit(1)


@research.command("list")
@click.option("--snapshot", "snapshot_id", default=None)
@click.option("--security", "instrument_id", default=None)
@output_option
@click.pass_context
def research_list(
    context: click.Context,
    snapshot_id: str | None,
    instrument_id: str | None,
    output_mode: str,
) -> None:
    """List locally stored Security Research Packs."""

    console = _console(context, output_mode)
    try:
        document = list_security_research(
            context.obj["config_path"],
            snapshot_id=snapshot_id,
            instrument_id=instrument_id,
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("research_list_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Security Research Packs")


@research.command("show")
@click.argument("research_id", default="latest")
@click.option("--snapshot", "snapshot_id", default="latest", show_default=True)
@click.option("--security", "instrument_id", default=None)
@output_option
@click.pass_context
def research_show(
    context: click.Context,
    research_id: str,
    snapshot_id: str,
    instrument_id: str | None,
    output_mode: str,
) -> None:
    """Show one exact or security-specific latest research pack."""

    console = _console(context, output_mode)
    try:
        document = show_security_research(
            context.obj["config_path"],
            research_id,
            snapshot_id=snapshot_id,
            instrument_id=instrument_id,
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("research_show_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Security Research Pack")


@main.group()
def portfolio() -> None:
    """Import and inspect the local brokerage-neutral portfolio."""


@portfolio.command("import")
@click.argument("path", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--broker",
    required=True,
    help="Use 'canonical' or the name of one installed portfolio importer.",
)
@click.option("--as-of", required=True, help="Use an ISO 8601 timestamp with a UTC offset.")
@output_option
@click.pass_context
def portfolio_import(
    context: click.Context, path: Path, broker: str, as_of: str, output_mode: str
) -> None:
    """Import a portfolio CSV without retaining the source file."""

    console = _console(context, output_mode)
    try:
        document = import_portfolio(path, broker=broker, as_of=as_of)
    except (ImportError, LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        console.emit_error("portfolio_import_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Portfolio")


@portfolio.command("show")
@output_option
@click.pass_context
def portfolio_show(context: click.Context, output_mode: str) -> None:
    """Show the verified latest normalized portfolio without network access."""

    console = _console(context, output_mode)
    try:
        document = read_portfolio()
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("portfolio_show_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Portfolio")


@main.group()
def watchlist() -> None:
    """Maintain instruments selected for routine observation."""


@watchlist.command("add")
@click.argument("instrument")
@output_option
@click.pass_context
def watchlist_add(
    context: click.Context,
    instrument: str,
    output_mode: str,
) -> None:
    """Add one supported MIC:SYMBOL."""

    console = _console(context, output_mode)
    try:
        document = add_watchlist_instrument(
            instrument,
            as_of=datetime.now().astimezone(),
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("watchlist_add_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Watchlist")


@watchlist.command("remove")
@click.argument("instrument")
@output_option
@click.pass_context
def watchlist_remove(context: click.Context, instrument: str, output_mode: str) -> None:
    """Remove one supported MIC:SYMBOL from the latest watchlist."""

    console = _console(context, output_mode)
    try:
        document = remove_watchlist_instrument(instrument, as_of=datetime.now().astimezone())
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("watchlist_remove_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Watchlist")


@watchlist.command("show")
@output_option
@click.pass_context
def watchlist_show(context: click.Context, output_mode: str) -> None:
    """Show the latest watchlist and its content-addressed history."""

    try:
        document = read_watchlist()
    except (LookupError, OSError, TypeError, ValueError) as error:
        _console(context, output_mode).emit_error("watchlist_show_failed", str(error))
        raise click.exceptions.Exit(1) from None
    _console(context, output_mode).emit_document(document, title="Watchlist")


@main.command()
@click.argument("market", type=click.Choice(("jp", "us")))
@click.option(
    "--as-of",
    default=None,
    help="Use an explicit ISO 8601 knowledge time; defaults to the current time.",
)
@output_option
@click.pass_context
def daily(context: click.Context, market: str, as_of: str | None, output_mode: str) -> None:
    """Acquire one market and create its immutable Close Brief."""

    console = _console(context, output_mode)
    try:
        instant = datetime.now().astimezone() if as_of is None else datetime.fromisoformat(as_of)
        report = build_daily_brief_service(context.obj["config_path"]).run(market, as_of=instant)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        console.emit_error("daily_failed", str(error))
        raise click.exceptions.Exit(1) from None
    if output_mode == "json":
        console.emit_document(read_decision_report(report.report_id), title="Decision report")
    else:
        click.echo(project_decision_report(report.report_id), nl=False)


@main.command()
@click.option(
    "--as-of",
    default=None,
    help="Use an explicit ISO 8601 knowledge time; defaults to the current time.",
)
@output_option
@click.pass_context
def weekly(context: click.Context, as_of: str | None, output_mode: str) -> None:
    """Create the offline weekend briefing from eligible daily reports."""

    console = _console(context, output_mode)
    try:
        instant = datetime.now().astimezone() if as_of is None else datetime.fromisoformat(as_of)
        report = build_weekly_brief_service(context.obj["config_path"]).run(as_of=instant)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        console.emit_error("weekly_failed", str(error))
        raise click.exceptions.Exit(1) from None
    if output_mode == "json":
        console.emit_document(read_decision_report(report.report_id), title="Decision report")
    else:
        click.echo(project_decision_report(report.report_id), nl=False)


@main.group()
def experiment() -> None:
    """Replay and compare deterministic decision policies offline."""


@experiment.command("run")
@click.argument("spec", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@output_option
@click.pass_context
def experiment_run(context: click.Context, spec: Path, output_mode: str) -> None:
    """Run one fixed strategy specification against verified snapshots."""

    console = _console(context, output_mode)
    try:
        document = build_experiment_service().run(spec)
    except (KeyError, LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("experiment_run_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Experiment run")


@experiment.command("show")
@click.argument("run_id")
@output_option
@click.pass_context
def experiment_show(context: click.Context, run_id: str, output_mode: str) -> None:
    """Show one immutable experiment run without network access."""

    console = _console(context, output_mode)
    try:
        document = build_experiment_service().show(run_id)
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("experiment_show_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Experiment run")


@experiment.command("compare")
@click.argument("left_run_id")
@click.argument("right_run_id")
@output_option
@click.pass_context
def experiment_compare(
    context: click.Context, left_run_id: str, right_run_id: str, output_mode: str
) -> None:
    """Compare deterministic metrics from two stored runs."""

    console = _console(context, output_mode)
    try:
        document = build_experiment_service().compare(left_run_id, right_run_id)
    except (LookupError, OSError, TypeError, ValueError) as error:
        console.emit_error("experiment_compare_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(document, title="Experiment comparison")


@main.group()
def report() -> None:
    """Read immutable decision reports."""


@report.command("list")
@output_option
@click.pass_context
def report_list(context: click.Context, output_mode: str) -> None:
    """List stored decision reports without contacting a provider."""

    console = _console(context, output_mode)
    try:
        document = list_decision_reports()
    except (LookupError, TypeError, ValueError, OSError) as error:
        console.emit_error("report_list_failed", str(error))
        raise click.exceptions.Exit(1) from None
    console.emit_document(
        document,
        title="Decision reports",
    )


@report.command("show")
@click.argument("report_id")
@output_option
@click.pass_context
def report_show(context: click.Context, report_id: str, output_mode: str) -> None:
    """Show an exact report ID or the newest stored report."""

    console = _console(context, output_mode)
    try:
        document = read_decision_report(report_id) if output_mode == "json" else None
        markdown = project_decision_report(report_id) if output_mode != "json" else None
    except (LookupError, TypeError, ValueError, OSError) as error:
        console.emit_error("report_show_failed", str(error))
        raise click.exceptions.Exit(1) from None
    if output_mode == "json":
        assert document is not None
        console.emit_document(document, title="Decision report")
    else:
        assert markdown is not None
        click.echo(markdown, nl=False)


@report.command("export")
@click.argument("report_id")
@click.option("--format", "export_format", type=click.Choice(("markdown",)), default="markdown")
def report_export(report_id: str, export_format: str) -> None:
    """Export a verified projection of an exact or latest report."""

    del export_format
    try:
        markdown = render_decision_report(report_id)
    except (LookupError, TypeError, ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(markdown, nl=False)


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
