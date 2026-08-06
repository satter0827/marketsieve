"""Validate that the latest portfolio can support at least one daily analysis."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from marketsieve_cli.bootstrap import read_portfolio


def validate_portfolio_document(document: Mapping[str, Any]) -> None:
    """Reject a stored portfolio with no holdings or watch items."""

    holdings = document.get("holdings")
    watch_items = document.get("watch_items")
    if not isinstance(holdings, list) or not isinstance(watch_items, list):
        raise ValueError("portfolio structure is invalid")
    if not holdings and not watch_items:
        raise ValueError("portfolio has no holdings or watch items")


def main() -> int:
    """Validate the latest stored portfolio and print a concise result."""

    try:
        validate_portfolio_document(read_portfolio())
    except (LookupError, OSError, TypeError, ValueError) as error:
        print(f"[invalid] portfolio: {error}")
        return 2
    print("[ready] portfolio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
