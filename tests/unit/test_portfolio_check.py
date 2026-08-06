import pytest
from scripts.portfolio_check import validate_portfolio_document


def test_portfolio_readiness_accepts_holdings_or_watch_items() -> None:
    validate_portfolio_document({"holdings": [{}], "watch_items": []})
    validate_portfolio_document({"holdings": [], "watch_items": [{}]})


def test_portfolio_readiness_rejects_an_empty_portfolio() -> None:
    with pytest.raises(ValueError, match="no holdings or watch items"):
        validate_portfolio_document({"holdings": [], "watch_items": []})
