import pytest
from scripts import portfolio_check
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


def test_empty_portfolio_guidance_uses_current_market_and_watchlist_tasks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(portfolio_check, "read_portfolio", lambda: {"holdings": []})
    monkeypatch.setattr(portfolio_check, "read_watchlist", lambda: {"items": []})
    monkeypatch.setattr(portfolio_check, "daily_source_diagnostics", lambda path: {})
    monkeypatch.setattr("sys.argv", ["portfolio_check", "marketsieve.toml"])

    assert portfolio_check.main() == 0
    output = capsys.readouterr().out
    assert "Market: Refresh Snapshot (Network)" in output
    assert "Watchlist: Add" in output
    assert "Discovery" not in output


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
