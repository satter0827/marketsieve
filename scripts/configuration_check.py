"""Validate the configuration required by the VS Code daily workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from marketsieve_cli.adapters.config import Configuration
from marketsieve_cli.adapters.plugins import SourcePluginRegistry
from marketsieve_extension_api import DailyBarSourceConfiguration, SourceConfiguration


def validate_daily_configuration(path: Path) -> None:
    """Validate every configuration path used by the numbered workflow."""

    configuration = Configuration(path)
    sources = SourcePluginRegistry()
    for market in ("jp", "us"):
        source_name, _, _ = configuration.daily_profile(market)
        profile = configuration.source_profile(source_name)
        binding = profile.binding("daily_bars")
        diagnostic = sources.load_fetcher(binding.plugin).doctor(
            DailyBarSourceConfiguration(profile.currency, profile.timezone, binding.settings)
        )
        diagnostics = [diagnostic]
        if "financials" in profile.sources:
            financials = profile.binding("financials")
            diagnostics.append(
                sources.load_financial_fetcher(financials.plugin).doctor_financials(
                    SourceConfiguration(profile.currency, profile.timezone, financials.settings)
                )
            )
        if "events" in profile.sources:
            events = profile.binding("events")
            diagnostics.append(
                sources.load_event_fetcher(events.plugin).doctor_events(
                    SourceConfiguration(profile.currency, profile.timezone, events.settings)
                )
            )
        for diagnostic in diagnostics:
            if not diagnostic.ready and diagnostic.code != "missing_credential":
                raise ValueError(diagnostic.message)
    configuration.weekly_max_age_days()


def main() -> int:
    """Validate one configuration and print a concise readiness result."""

    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    arguments = parser.parse_args()
    try:
        validate_daily_configuration(arguments.config)
    except (LookupError, OSError, TypeError, ValueError) as error:
        print(f"[invalid] configuration: {error}")
        return 2
    print(f"[ready] configuration: {arguments.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
