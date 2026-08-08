from __future__ import annotations

from importlib import metadata
from typing import Any, cast

import pytest

from marketsieve_cli.adapters import plugins


class FakeEntryPoint:
    name = "yfinance"

    def __init__(self, value: object) -> None:
        self.value = value

    def load(self) -> Any:
        return lambda: self.value


def test_registry_loads_only_the_explicit_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = cast(Any, object())
    monkeypatch.setattr(
        metadata,
        "entry_points",
        lambda **_: cast(Any, (FakeEntryPoint(candidate),)),
    )

    with pytest.raises(TypeError, match="EquityBatchFetcher"):
        plugins.SourcePluginRegistry().load_equity_batch_fetcher("yfinance")


def test_registry_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "entry_points", lambda **_: cast(Any, ()))

    with pytest.raises(LookupError, match="not installed"):
        plugins.SourcePluginRegistry().load_security_research_fetcher("yfinance")
