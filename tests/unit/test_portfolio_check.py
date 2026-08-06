import pytest
from scripts.portfolio_check import runnable_markets, supported_markets


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


def test_portfolio_readiness_combines_markets_with_credentials() -> None:
    markets = frozenset({"jp", "us"})

    jp_environment = dict.fromkeys(("JQUANTS_API_KEY",), "present")
    us_environment = dict.fromkeys(("ALPHAVANTAGE_API_KEY",), "present")
    assert runnable_markets(markets, jp_environment) == frozenset({"jp"})
    assert runnable_markets(markets, us_environment) == frozenset({"us"})
    assert runnable_markets(markets, {}) == frozenset()
