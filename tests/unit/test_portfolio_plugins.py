from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest

from marketsieve_cli.adapters import portfolio_plugins
from marketsieve_extension_api import ImportedPortfolioSnapshot


class FakeImporter:
    def import_portfolio(self, path: Path, *, as_of: datetime) -> ImportedPortfolioSnapshot:
        raise NotImplementedError(path, as_of)


class FakeEntryPoint:
    name = "fixture"

    def load(self) -> type[FakeImporter]:
        return FakeImporter


class WrongEntryPoint:
    name = "fixture"

    def load(self) -> type[object]:
        return object


def test_portfolio_registry_loads_one_explicit_importer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        portfolio_plugins,
        "portfolio_importer_entry_points",
        lambda: cast(Any, (FakeEntryPoint(),)),
    )

    assert isinstance(portfolio_plugins.PortfolioPluginRegistry().load("fixture"), FakeImporter)


@pytest.mark.parametrize("entries", ((), (FakeEntryPoint(), FakeEntryPoint())))
def test_portfolio_registry_rejects_missing_or_ambiguous_importer(
    monkeypatch: pytest.MonkeyPatch, entries: tuple[FakeEntryPoint, ...]
) -> None:
    monkeypatch.setattr(
        portfolio_plugins,
        "portfolio_importer_entry_points",
        lambda: cast(Any, entries),
    )

    with pytest.raises(ValueError, match="exactly one"):
        portfolio_plugins.PortfolioPluginRegistry().load("fixture")


def test_portfolio_registry_rejects_wrong_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        portfolio_plugins,
        "portfolio_importer_entry_points",
        lambda: cast(Any, (WrongEntryPoint(),)),
    )

    with pytest.raises(TypeError, match="does not implement"):
        portfolio_plugins.PortfolioPluginRegistry().load("fixture")
