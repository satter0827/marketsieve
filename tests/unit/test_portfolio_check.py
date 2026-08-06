import pytest
from scripts.portfolio_check import runnable_markets, supported_markets

from marketsieve_extension_api import SourceDiagnostic


def test_portfolio_readiness_accepts_holdings_or_watch_items() -> None:
    assert supported_markets(
        {"holdings": [{"instrument": {"currency": "JPY"}}], "watch_items": []}
    ) == frozenset({"jp"})
    assert supported_markets(
        {"holdings": [], "watch_items": [{"instrument": {"currency": "USD"}}]}
    ) == frozenset({"us"})


def test_portfolio_readiness_rejects_an_empty_portfolio() -> None:
    with pytest.raises(ValueError, match="no holdings or watch items"):
        supported_markets({"holdings": [], "watch_items": []})


def test_portfolio_readiness_uses_each_configured_provider_diagnostic() -> None:
    markets = frozenset({"jp", "us"})
    ready = SourceDiagnostic(True, "ready", "Custom source is configured.")
    blocked = SourceDiagnostic(
        False,
        "missing_credential",
        "Custom credential is not set.",
        "Set the custom credential.",
    )

    assert runnable_markets(markets, {"jp": ready, "us": blocked}) == frozenset({"jp"})
    assert runnable_markets(markets, {"jp": blocked, "us": ready}) == frozenset({"us"})
    assert runnable_markets(markets, {"jp": blocked, "us": blocked}) == frozenset()
