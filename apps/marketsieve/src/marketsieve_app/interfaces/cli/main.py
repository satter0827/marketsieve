"""MarketSieve command-line entry point."""

from __future__ import annotations

import click

from marketsieve_app.bootstrap import build_diagnostics_service, sdk_version


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=sdk_version(), prog_name="marketsieve")
def main() -> None:
    """Operate the repository-local MarketSieve application."""


@main.command()
def doctor() -> None:
    """Check the local foundation without network access or secrets."""

    service = build_diagnostics_service()
    checks = service.collect()
    click.echo("MarketSieve doctor")
    for check in checks:
        marker = "ok" if check.passed else "error"
        click.echo(f"[{marker}] {check.name}: {check.detail}")

    succeeded = service.succeeded(checks)
    click.echo(f"Status: {'ready' if succeeded else 'not ready'}")
    if not succeeded:
        raise click.exceptions.Exit(1)
