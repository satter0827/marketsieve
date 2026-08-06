"""Validate the configuration required by the VS Code daily workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from marketsieve_cli.adapters.config import Configuration
from marketsieve_cli.adapters.plugins import SourcePluginRegistry


def validate_daily_configuration(path: Path) -> None:
    """Validate every configuration path used by the numbered workflow."""

    configuration = Configuration(path)
    sources = SourcePluginRegistry()
    for market in ("jp", "us"):
        source_name, _, _ = configuration.daily_profile(market)
        binding = configuration.source_profile(source_name).binding("daily_bars")
        sources.load_fetcher(binding.plugin)
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
