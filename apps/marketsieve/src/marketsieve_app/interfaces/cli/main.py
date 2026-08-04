"""MarketSieve command-line entry point."""

from __future__ import annotations

import click

from marketsieve_app.bootstrap import build_diagnostics_service, sdk_version


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
