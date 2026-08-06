import pytest
from scripts.portfolio_check import runnable_markets, supported_markets

from marketsieve_extension_api import SourceDiagnostic


def test_portfolio_readiness_accepts_holdings_or_watch_items() -> None:
    assert supported_markets(
        {"holdings": [{"instrument": {"currency": "JPY"}}]}, {"items": []}
    ) == frozenset({"jp"})
    assert supported_markets(
        {"holdings": []}, {"items": [{"instrument": {"currency": "USD"}}]}
    ) == frozenset({"us"})


def test_portfolio_readiness_accepts_an_empty_portfolio_and_watchlist() -> None:
    assert supported_markets({"holdings": []}, {"items": []}) == frozenset()


def test_portfolio_readiness_rejects_nonempty_unsupported_market() -> None:
    with pytest.raises(ValueError, match="JPY or USD"):
        supported_markets(
            {"holdings": [{"instrument": {"currency": "EUR"}}]},
            {"items": []},
        )


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
