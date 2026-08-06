"""Validate that the latest portfolio can support at least one daily analysis."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from marketsieve_cli.bootstrap import read_portfolio, read_watchlist
from marketsieve_extension_api import SourceDiagnostic
from scripts.configuration_check import daily_source_diagnostics


def supported_markets(portfolio: Mapping[str, Any], watchlist: Mapping[str, Any]) -> frozenset[str]:
    """Return supported markets represented by holdings or independent watchlist items."""

    holdings = portfolio.get("holdings")
    watch_items = watchlist.get("items")
    if not isinstance(holdings, list) or not isinstance(watch_items, list):
        raise ValueError("portfolio or watchlist structure is invalid")
    markets: set[str] = set()
    for item in [*holdings, *watch_items]:
        if not isinstance(item, Mapping) or not isinstance(item.get("instrument"), Mapping):
            raise ValueError("portfolio instrument structure is invalid")
        currency = item["instrument"].get("currency")
        if currency == "JPY":
            markets.add("jp")
        elif currency == "USD":
            markets.add("us")
        else:
            raise ValueError("portfolio instruments must use JPY or USD")
    return frozenset(markets)


def runnable_markets(
    markets: frozenset[str], diagnostics: Mapping[str, SourceDiagnostic]
) -> frozenset[str]:
    """Return portfolio markets whose configured daily provider is ready."""

    return frozenset(market for market in markets if diagnostics[market].ready)


def main() -> int:
    """Validate the latest stored portfolio and print a concise result."""

    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    arguments = parser.parse_args()
    try:
        markets = supported_markets(read_portfolio(), read_watchlist())
        diagnostics = daily_source_diagnostics(arguments.config)
    except (LookupError, OSError, TypeError, ValueError) as error:
        print(f"[invalid] portfolio: {error}")
        print("Next VS Code operation: 02 First Run: Import Portfolio CSV")
        return 2
    if not markets:
        print("[ready] portfolio and watchlist are empty")
        print("Next: run 10 Discovery: Refresh JP Candidates (Network),")
        print("20 Discovery: Refresh US Candidates (Network), or 30 Watchlist: Add Instrument")
        return 0
    print(f"[ready] analysis markets: {', '.join(sorted(markets))}")
    runnable = runnable_markets(markets, diagnostics)
    for market in sorted(markets):
        diagnostic = diagnostics[market]
        status = "ready" if diagnostic.ready else "blocked"
        print(f"[{status}] {market} daily source: {diagnostic.message}")
        if not diagnostic.ready and diagnostic.recovery:
            print(f"Next: {diagnostic.recovery}")
    if not runnable:
        print("[blocked] fix the configured daily source, then rerun 03 First Run: Check Readiness")
        return 2
    operations = [
        "40 Daily Use: Analyze JP Watchlist (Network)"
        if market == "jp"
        else "50 Daily Use: Analyze US Watchlist (Network)"
        for market in sorted(runnable)
    ]
    print(f"Next daily operation: {', or '.join(operations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
