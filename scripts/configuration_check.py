"""Validate the configuration required by the VS Code daily workflow."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
from typing import Any


def validate_toml_syntax(path: Path) -> None:
    """Validate existence and TOML syntax without importing project packages."""

    with path.open("rb") as stream:
        document = tomllib.load(stream)
    if not isinstance(document, dict):
        raise ValueError("configuration root must be a TOML table")


def daily_source_diagnostics(path: Path) -> dict[str, Any]:
    """Inspect each configured daily-bar provider without using the network."""

    from marketsieve_cli.adapters.config import Configuration
    from marketsieve_cli.adapters.plugins import SourcePluginRegistry
    from marketsieve_extension_api import DailyBarSourceConfiguration

    configuration = Configuration(path)
    sources = SourcePluginRegistry()
    diagnostics: dict[str, Any] = {}
    expected_markets = {
        "jp": ("JPY", "Asia/Tokyo"),
        "us": ("USD", "America/New_York"),
    }
    for market in ("jp", "us"):
        source_name, _, _ = configuration.daily_profile(market)
        profile = configuration.source_profile(source_name)
        if (profile.currency, profile.timezone) != expected_markets[market]:
            currency, timezone = expected_markets[market]
            raise ValueError(f"daily routine {market!r} requires {currency} and {timezone}")
        binding = profile.binding("daily_bars")
        diagnostics[market] = sources.load_fetcher(binding.plugin).doctor(
            DailyBarSourceConfiguration(profile.currency, profile.timezone, binding.settings)
        )
    return diagnostics


def validate_daily_configuration(path: Path) -> None:
    """Validate every configuration path used by the numbered workflow."""

    from marketsieve_cli.adapters.config import Configuration
    from marketsieve_cli.adapters.plugins import SourcePluginRegistry
    from marketsieve_extension_api import SourceConfiguration

    configuration = Configuration(path)
    sources = SourcePluginRegistry()
    daily_diagnostics = daily_source_diagnostics(path)
    for market in ("jp", "us"):
        source_name, _, _ = configuration.daily_profile(market)
        profile = configuration.source_profile(source_name)
        diagnostics = [daily_diagnostics[market]]
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
    parser.add_argument("--syntax-only", action="store_true")
    parser.add_argument("config", type=Path)
    arguments = parser.parse_args()
    try:
        validate_toml_syntax(arguments.config)
        if not arguments.syntax_only:
            validate_daily_configuration(arguments.config)
    except (
        ImportError,
        LookupError,
        OSError,
        TypeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ) as error:
        print(f"[invalid] configuration: {error}")
        return 2
    print(f"[ready] configuration: {arguments.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
