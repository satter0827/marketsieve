"""MarketSieve command-line entry point."""

from __future__ import annotations

import click

from marketsieve import __version__
from marketsieve_app.diagnostics import collect_diagnostics, diagnostics_succeeded


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="marketsieve")
def main() -> None:
    """Operate the repository-local MarketSieve application."""


@main.command()
def doctor() -> None:
    """Check the local foundation without network access or secrets."""

    checks = collect_diagnostics()
    click.echo("MarketSieve doctor")
    for check in checks:
        marker = "ok" if check.passed else "error"
        click.echo(f"[{marker}] {check.name}: {check.detail}")

    succeeded = diagnostics_succeeded(checks)
    click.echo(f"Status: {'ready' if succeeded else 'not ready'}")
    if not succeeded:
        raise click.exceptions.Exit(1)
