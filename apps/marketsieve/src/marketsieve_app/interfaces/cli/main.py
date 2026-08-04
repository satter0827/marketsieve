"""MarketSieve command-line entry point."""

from __future__ import annotations

import json
from typing import Any

import click

from marketsieve_app.bootstrap import build_demo_service, build_diagnostics_service, sdk_version


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=sdk_version(), prog_name="marketsieve")
@click.option(
    "--log-level",
    type=click.Choice(("DEBUG", "INFO", "WARNING", "ERROR"), case_sensitive=False),
    default="WARNING",
    show_default=True,
)
@click.option("--log-file", is_flag=True, help="Also write JSON Lines under .marketsieve/logs.")
@click.pass_context
def main(context: click.Context, log_level: str, log_file: bool) -> None:
    """Operate the repository-local MarketSieve application."""

    context.ensure_object(dict)
    context.obj["log_level"] = log_level.upper()
    context.obj["log_file"] = log_file


@main.command()
@click.pass_context
def doctor(context: click.Context) -> None:
    """Check the local foundation without network access or secrets."""

    service = build_diagnostics_service(
        level=context.obj["log_level"], write_log_file=context.obj["log_file"]
    )
    checks = service.collect()
    click.echo("MarketSieve doctor")
    for check in checks:
        marker = "ok" if check.passed else "error"
        click.echo(f"[{marker}] {check.name}: {check.detail}")

    succeeded = service.succeeded(checks)
    click.echo(f"Status: {'ready' if succeeded else 'not ready'}")
    if not succeeded:
        raise click.exceptions.Exit(1)


def render_demo_text(document: dict[str, Any]) -> tuple[str, ...]:
    """Render the human projection of a structured demo document."""

    lines = []
    for item in document["results"]:
        instrument = item["instrument"]
        analysis = item["analysis"]
        state = analysis["current_state"] or analysis["status"]
        transition = analysis["transition"] or "none"
        lines.append(
            f"{item['market'].upper()} {instrument['mic']}:{instrument['symbol']} "
            f"SMA20={analysis['current_sma']} state={state} transition={transition} "
            f"evidence={item['evidence_id']}"
        )
    return tuple(lines)


@main.command()
@click.option("--market", type=click.Choice(("jp", "us", "all")), default="all", show_default=True)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("text", "json")),
    default="text",
    show_default=True,
)
@click.pass_context
def demo(context: click.Context, market: str, output_format: str) -> None:
    """Run the deterministic synthetic daily-bar SMA20 preview."""

    service = build_demo_service(
        level=context.obj["log_level"], write_log_file=context.obj["log_file"]
    )
    try:
        document = service.run(market)
    except (RuntimeError, TypeError, ValueError):
        raise click.exceptions.Exit(1) from None
    if output_format == "json":
        click.echo(json.dumps(document, sort_keys=True, separators=(",", ":")))
        return
    for line in render_demo_text(document):
        click.echo(line)
