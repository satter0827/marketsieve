"""MarketSieve command-line entry point."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import click

from marketsieve_cli.bootstrap import (
    MARKET_EVIDENCE,
    MARKET_INDEX_GROUPS,
    MARKET_INDICES,
    RESEARCH_EVIDENCE,
    MarketBuildInputs,
    MarketCompareInputs,
    MarketDiffInputs,
    MarketQueryInputs,
    ResearchBuildInputs,
    artifact_doctor,
    artifact_inventory,
    build_console_output,
    build_diagnostics_service,
    build_market_snapshot,
    build_preview,
    build_security_research,
    capabilities_document,
    compare_market_snapshot_securities,
    configure_application_logging,
    diff_market_snapshots,
    list_market_snapshots,
    list_security_research,
    operation_runs,
    query_market_snapshot,
    read_market_snapshot_security,
    sdk_version,
    show_market_snapshot,
    show_security_research,
)

OUTPUT_CHOICES = ("auto", "rich", "text", "json")


def output_option(function: Any) -> Any:
    return click.option(
        "--output",
        "output_mode",
        type=click.Choice(OUTPUT_CHOICES),
        default="auto",
        show_default=True,
    )(function)


def _console(context: click.Context, output_mode: str) -> Any:
    return build_console_output(
        output_mode,
        stdout=click.get_text_stream("stdout"),
        stderr=click.get_text_stream("stderr"),
        locale=context.obj["locale"],
    )


def _indices(
    all_indices: bool, markets: tuple[str, ...], indices: tuple[str, ...]
) -> tuple[str, ...]:
    selected = set(indices)
    for market_name in markets:
        selected.update(MARKET_INDEX_GROUPS[market_name])
    if all_indices:
        selected.update(MARKET_INDICES)
    selectors = int(all_indices) + bool(markets) + bool(indices)
    if selectors != 1:
        raise ValueError("select exactly one scope: --all, --market, or --index")
    return tuple(sorted(selected))


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


def _emit_failure(console: Any, code: str, error: Exception) -> None:
    console.emit_error(code, str(error))
    raise click.exceptions.Exit(1)


@click.group(context_settings={"help_option_names": ["-h", "--help"]}, invoke_without_command=True)
@click.version_option(version=sdk_version(), prog_name="marketsieve")
@click.option("--settings", "settings_path", type=click.Path(path_type=Path, dir_okay=False))
@click.option("--log-level", type=click.Choice(("DEBUG", "INFO", "WARNING", "ERROR")))
@click.option("--log-file", is_flag=True)
@click.option("--locale", type=click.Choice(("ja", "en")), default="ja", show_default=True)
@click.pass_context
def main(
    context: click.Context,
    settings_path: Path | None,
    log_level: str | None,
    log_file: bool,
    locale: str,
) -> None:
    """Build reproducible Japanese and U.S. equity evidence."""

    context.ensure_object(dict)
    context.obj.update(
        settings_path=settings_path, log_level=log_level, log_file=log_file, locale=locale
    )
    configure_application_logging(level=log_level, write_log_file=log_file)
    if context.invoked_subcommand is None:
        _console(context, "auto").emit_landing(sdk_version())


@main.command()
@output_option
@click.pass_context
def doctor(context: click.Context, output_mode: str) -> None:
    """Check the local runtime and installed source."""

    console = _console(context, output_mode)
    service = build_diagnostics_service(
        level=context.obj["log_level"], write_log_file=context.obj["log_file"]
    )
    checks = service.collect()
    console.emit_doctor(checks)
    if not service.succeeded(checks):
        raise click.exceptions.Exit(1)


@main.command()
@output_option
@click.pass_context
def capabilities(context: click.Context, output_mode: str) -> None:
    """Describe stable commands, schemas, and side effects."""

    document = capabilities_document(sdk_version())
    _console(context, output_mode).emit_capabilities(document)


@main.group()
def market() -> None:
    """Build and inspect broad yfinance Market Snapshots."""


@market.command("build")
@click.option("--all", "all_indices", is_flag=True)
@click.option("--market", "markets", multiple=True, type=click.Choice(("jp", "us")))
@click.option("--index", "indices", multiple=True, type=click.Choice(MARKET_INDICES))
@click.option("--evidence", multiple=True, type=click.Choice(MARKET_EVIDENCE))
@click.option("--history-days", type=click.IntRange(30, 3653))
@click.option("--resume", "run_id")
@output_option
@click.pass_context
def market_build(
    context: click.Context,
    all_indices: bool,
    markets: tuple[str, ...],
    indices: tuple[str, ...],
    evidence: tuple[str, ...],
    history_days: int | None,
    run_id: str | None,
    output_mode: str,
) -> None:
    """Acquire an explicitly scoped market snapshot."""

    console = _console(context, output_mode)
    try:
        inputs = None
        if run_id is None:
            inputs = MarketBuildInputs(
                _indices(all_indices, markets, indices), tuple(sorted(set(evidence))), history_days
            )
        elif all_indices or markets or indices or evidence or history_days is not None:
            raise ValueError("--resume cannot be combined with build inputs")
        document = build_market_snapshot(context.obj["settings_path"], inputs, resume=run_id)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        _emit_failure(console, "market_build_failed", error)
    console.emit_document(document, title="Market Snapshot")
    if not document["price_coverage_gate_passed"]:
        raise click.exceptions.Exit(1)


@market.command("capture")
@click.option("--market", "market_name", required=True, type=click.Choice(("jp", "us")))
@click.option("--session", required=True, type=click.Choice(("close",)))
@click.option("--evidence", multiple=True, required=True, type=click.Choice(MARKET_EVIDENCE))
@click.option("--history-days", required=True, type=click.IntRange(30, 3653))
@click.option("--resume", "run_id")
@output_option
@click.pass_context
def market_capture(
    context: click.Context,
    market_name: str,
    session: str,
    evidence: tuple[str, ...],
    history_days: int,
    run_id: str | None,
    output_mode: str,
) -> None:
    """Capture one explicitly selected market close session."""

    console = _console(context, output_mode)
    try:
        inputs = None
        if run_id is None:
            inputs = MarketBuildInputs(
                MARKET_INDEX_GROUPS[market_name],
                tuple(sorted(set(evidence))),
                history_days,
                session=session,
            )
        document = build_market_snapshot(context.obj["settings_path"], inputs, resume=run_id)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        _emit_failure(console, "market_capture_failed", error)
    console.emit_document(document, title="Market Capture")
    if not document["price_coverage_gate_passed"]:
        raise click.exceptions.Exit(1)


@market.command("reconstruct")
@click.option("--market", "market_name", required=True, type=click.Choice(("jp", "us")))
@click.option("--date", "as_of", required=True, type=str)
@click.option("--history-days", required=True, type=click.IntRange(30, 3653))
@output_option
@click.pass_context
def market_reconstruct(
    context: click.Context,
    market_name: str,
    as_of: str,
    history_days: int,
    output_mode: str,
) -> None:
    """Reconstruct price and benchmark evidence without present-day financial data."""

    console = _console(context, output_mode)
    try:
        inputs = MarketBuildInputs(
            MARKET_INDEX_GROUPS[market_name],
            ("benchmarks", "price"),
            history_days,
            as_of=date.fromisoformat(as_of),
            mode="historical_price_reconstruction",
            session="close",
        )
        document = build_market_snapshot(context.obj["settings_path"], inputs)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        _emit_failure(console, "market_reconstruct_failed", error)
    console.emit_document(document, title="Historical Price Reconstruction")
    if not document["price_coverage_gate_passed"]:
        raise click.exceptions.Exit(1)


@market.command("list")
@output_option
@click.pass_context
def market_list(context: click.Context, output_mode: str) -> None:
    try:
        document = list_market_snapshots(context.obj["settings_path"])
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(_console(context, output_mode), "market_list_failed", error)
    _console(context, output_mode).emit_document(document, title="Market Snapshots")


@market.command("show")
@click.argument("snapshot_id", required=True)
@output_option
@click.pass_context
def market_show(context: click.Context, snapshot_id: str, output_mode: str) -> None:
    try:
        document = show_market_snapshot(context.obj["settings_path"], snapshot_id)
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(_console(context, output_mode), "market_show_failed", error)
    _console(context, output_mode).emit_document(document, title="Market Snapshot")


def _query_options(function: Any) -> Any:
    for name in ("industry", "sector", "currency", "country", "exchange", "mic"):
        function = click.option(f"--{name}", multiple=True)(function)
    function = click.option("--index", "indices", multiple=True, type=click.Choice(MARKET_INDICES))(
        function
    )
    function = click.option("--market", "markets", multiple=True, type=click.Choice(("jp", "us")))(
        function
    )
    function = click.option("--min", "minimum_values", multiple=True, metavar="FIELD=VALUE")(
        function
    )
    function = click.option("--max", "maximum_values", multiple=True, metavar="FIELD=VALUE")(
        function
    )
    function = click.option("--present", multiple=True)(function)
    function = click.option("--missing", multiple=True)(function)
    function = click.option("--fields", multiple=True)(function)
    function = click.option("--order", multiple=True, metavar="FIELD:asc|desc")(function)
    function = click.option("--limit", type=click.IntRange(min=1))(function)
    function = click.option("--domain", "domains", multiple=True)(function)
    function = click.option("--profile", type=click.Choice(("short-swing", "swing", "position")))(
        function
    )
    function = click.option("--budget", type=Decimal)(function)
    function = click.option("--budget-currency")(function)
    function = click.option("--trading-unit", type=click.IntRange(min=1))(function)
    function = click.option("--use-snapshot-fx", is_flag=True)(function)
    return function


@market.command("query")
@click.option("--snapshot", "snapshot_id", required=True)
@_query_options
@output_option
@click.pass_context
def market_query(
    context: click.Context, /, snapshot_id: str, output_mode: str, **values: Any
) -> None:
    """Filter stored rows without acquisition or recalculation."""

    console = _console(context, output_mode)
    try:
        option_names = {"index": "indices", "market": "markets"}
        filters = {
            key: tuple(values[option_names.get(key, key)])
            for key in (
                "market",
                "index",
                "mic",
                "exchange",
                "country",
                "currency",
                "sector",
                "industry",
            )
            if values[option_names.get(key, key)]
        }
        document = query_market_snapshot(
            context.obj["settings_path"],
            MarketQueryInputs(
                snapshot_id=snapshot_id,
                filters=filters,
                minimums=_numeric_bounds(values["minimum_values"], "--min"),
                maximums=_numeric_bounds(values["maximum_values"], "--max"),
                present=values["present"],
                missing=values["missing"],
                fields=values["fields"],
                order=values["order"],
                limit=values["limit"],
                domains=values["domains"],
                profile=values["profile"],
                budget=values["budget"],
                budget_currency=values["budget_currency"],
                trading_unit=values["trading_unit"],
                use_snapshot_fx=values["use_snapshot_fx"],
            ),
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(console, "market_query_failed", error)
    console.emit_document(document, title="Market Snapshot query")


@market.command("security")
@click.argument("instrument_id")
@click.option("--snapshot", "snapshot_id", required=True)
@output_option
@click.pass_context
def market_security(
    context: click.Context, instrument_id: str, snapshot_id: str, output_mode: str
) -> None:
    try:
        document = read_market_snapshot_security(
            context.obj["settings_path"], snapshot_id, instrument_id
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(_console(context, output_mode), "market_security_failed", error)
    _console(context, output_mode).emit_document(document, title="Market Snapshot security")


@market.command("compare")
@click.argument("instrument_ids", nargs=-1, required=True)
@click.option("--snapshot", "snapshot_id", required=True)
@click.option("--fields", multiple=True)
@output_option
@click.pass_context
def market_compare(
    context: click.Context,
    instrument_ids: tuple[str, ...],
    snapshot_id: str,
    fields: tuple[str, ...],
    output_mode: str,
) -> None:
    try:
        document = compare_market_snapshot_securities(
            context.obj["settings_path"], MarketCompareInputs(snapshot_id, instrument_ids, fields)
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(_console(context, output_mode), "market_compare_failed", error)
    _console(context, output_mode).emit_document(document, title="Market Snapshot comparison")


@market.command("diff")
@click.argument("left_snapshot_id")
@click.argument("right_snapshot_id")
@click.option("--fields", multiple=True)
@output_option
@click.pass_context
def market_diff(
    context: click.Context,
    left_snapshot_id: str,
    right_snapshot_id: str,
    fields: tuple[str, ...],
    output_mode: str,
) -> None:
    """Compare compatible stored fields across two snapshots."""

    try:
        document = diff_market_snapshots(
            context.obj["settings_path"],
            MarketDiffInputs(left_snapshot_id, right_snapshot_id, fields),
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(_console(context, output_mode), "market_diff_failed", error)
    _console(context, output_mode).emit_document(document, title="Market Snapshot diff")


@main.group()
def research() -> None:
    """Build and inspect yfinance evidence for snapshot securities."""


@research.command("build")
@click.argument("instrument_ids", nargs=-1, required=True)
@click.option("--snapshot", "snapshot_id", required=True)
@click.option("--evidence", multiple=True, type=click.Choice(RESEARCH_EVIDENCE))
@click.option("--history-days", type=click.IntRange(30, 3653))
@output_option
@click.pass_context
def research_build(
    context: click.Context,
    instrument_ids: tuple[str, ...],
    snapshot_id: str,
    evidence: tuple[str, ...],
    history_days: int | None,
    output_mode: str,
) -> None:
    console = _console(context, output_mode)
    try:
        inputs = ResearchBuildInputs(
            snapshot_id, instrument_ids, tuple(sorted(set(evidence))), history_days
        )
        document = build_security_research(context.obj["settings_path"], inputs)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        _emit_failure(console, "research_build_failed", error)
    console.emit_document(document, title="Security Research")
    if not document["requirements_met"]:
        raise click.exceptions.Exit(1)


@research.command("list")
@click.option("--snapshot", "snapshot_id")
@click.option("--security", "instrument_id")
@output_option
@click.pass_context
def research_list(
    context: click.Context, snapshot_id: str | None, instrument_id: str | None, output_mode: str
) -> None:
    try:
        document = list_security_research(
            context.obj["settings_path"], snapshot_id=snapshot_id, instrument_id=instrument_id
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(_console(context, output_mode), "research_list_failed", error)
    _console(context, output_mode).emit_document(document, title="Security Research")


@research.command("show")
@click.argument("research_id", required=True)
@click.option("--snapshot", "snapshot_id")
@click.option("--security", "instrument_id")
@output_option
@click.pass_context
def research_show(
    context: click.Context,
    research_id: str,
    snapshot_id: str | None,
    instrument_id: str | None,
    output_mode: str,
) -> None:
    try:
        document = show_security_research(
            context.obj["settings_path"],
            research_id,
            snapshot_id=snapshot_id,
            instrument_id=instrument_id,
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(_console(context, output_mode), "research_show_failed", error)
    _console(context, output_mode).emit_document(document, title="Security Research")


def _preview(
    context: click.Context,
    object_ref: str,
    security: str | None,
    port: int,
    open_browser: bool,
) -> None:
    try:
        server = build_preview(
            context.obj["settings_path"], object_ref, security=security, port=port
        )
    except (LookupError, OSError, TypeError, ValueError) as error:
        _emit_failure(_console(context, "text"), "preview_failed", error)
    click.echo(server.url)
    server.serve_forever(open_browser=open_browser)


@market.command("preview")
@click.argument("snapshot_id", default="latest")
@click.option("--port", type=click.IntRange(0, 65535), default=0, show_default=True)
@click.option("--open", "open_browser", is_flag=True)
@click.pass_context
def market_preview(context: click.Context, snapshot_id: str, port: int, open_browser: bool) -> None:
    """Preview one verified Market Snapshot over loopback HTTP."""

    _preview(context, f"snapshot:{snapshot_id}", None, port, open_browser)


@research.command("preview")
@click.argument("research_id", default="latest")
@click.option("--security")
@click.option("--port", type=click.IntRange(0, 65535), default=0, show_default=True)
@click.option("--open", "open_browser", is_flag=True)
@click.pass_context
def research_preview(
    context: click.Context,
    research_id: str,
    security: str | None,
    port: int,
    open_browser: bool,
) -> None:
    """Preview one verified Security Research object over loopback HTTP."""

    _preview(context, f"research:{research_id}", security, port, open_browser)


@main.group()
def operations() -> None:
    """Inspect evidence health and generation history."""


@operations.group()
def artifacts() -> None:
    """Inspect current, incompatible, and damaged evidence objects."""


@artifacts.command("doctor")
@output_option
@click.pass_context
def artifacts_doctor(context: click.Context, output_mode: str) -> None:
    _console(context, output_mode).emit_document(artifact_doctor(), title="Artifact health")


@artifacts.command("list")
@click.option("--type", "object_type", type=click.Choice(("snapshot", "research")))
@click.option("--status", type=click.Choice(("current", "incompatible", "corrupt", "orphan")))
@output_option
@click.pass_context
def artifacts_list(
    context: click.Context, object_type: str | None, status: str | None, output_mode: str
) -> None:
    document = artifact_inventory(object_type=object_type, status=status)
    _console(context, output_mode).emit_document(document, title="Artifacts")


@operations.group("run")
def run_group() -> None:
    """Inspect and prune structured generation history."""


@run_group.command("list")
@click.option("--status")
@click.option("--command")
@output_option
@click.pass_context
def run_list(
    context: click.Context, status: str | None, command: str | None, output_mode: str
) -> None:
    _console(context, output_mode).emit_document(
        operation_runs().list(status=status, command=command), title="Operation runs"
    )


@run_group.command("show")
@click.argument("run_id")
@output_option
@click.pass_context
def run_show(context: click.Context, run_id: str, output_mode: str) -> None:
    _console(context, output_mode).emit_document(
        operation_runs().show(run_id), title="Operation run"
    )


@run_group.command("events")
@click.argument("run_id")
@click.option("--level", type=click.Choice(("DEBUG", "INFO", "WARNING", "ERROR")))
@output_option
@click.pass_context
def run_events(context: click.Context, run_id: str, level: str | None, output_mode: str) -> None:
    _console(context, output_mode).emit_document(
        operation_runs().events(run_id, level=level), title="Operation events"
    )


@run_group.command("prune")
@click.argument("run_ids", nargs=-1)
@click.option("--before", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--status")
@click.option("--apply", is_flag=True)
@output_option
@click.pass_context
def run_prune(
    context: click.Context,
    run_ids: tuple[str, ...],
    before: Any,
    status: str | None,
    apply: bool,
    output_mode: str,
) -> None:
    if not run_ids and before is None:
        _emit_failure(
            _console(context, output_mode),
            "run_prune_failed",
            ValueError("specify run IDs or --before"),
        )
    document = operation_runs().prune(
        run_ids, before=None if before is None else before.date(), status=status, apply=apply
    )
    _console(context, output_mode).emit_document(document, title="Operation prune")


def entrypoint() -> None:
    """Run the installed console application."""

    main(prog_name="marketsieve")


if __name__ == "__main__":
    entrypoint()
