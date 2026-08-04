from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from marketsieve_cli.adapters import plugins
from marketsieve_extension_api import ImportedDailyBars


class FakeDistribution:
    name = "marketsieve-source-fixture"
    version = "1.2.3"


class FakeImporter:
    def import_bundle(self, path: Path) -> ImportedDailyBars:
        raise NotImplementedError(path)


class FakeEntryPoint:
    name = "fixture"
    value = "fixture:FakeImporter"
    dist = FakeDistribution()

    def __init__(self) -> None:
        self.loaded = False

    def load(self) -> type[FakeImporter]:
        self.loaded = True
        return FakeImporter


def test_source_listing_does_not_import_plugin_code(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = FakeEntryPoint()
    monkeypatch.setattr(
        plugins,
        "source_entry_points",
        lambda **_: cast(Any, (entry,)),
    )

    installed = plugins.SourcePluginRegistry().installed()

    assert installed[0].distribution == "marketsieve-source-fixture"
    assert entry.loaded is False


def test_only_explicitly_selected_plugin_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = FakeEntryPoint()
    monkeypatch.setattr(
        plugins,
        "source_entry_points",
        lambda **_: cast(Any, (entry,)),
    )

    importer = plugins.SourcePluginRegistry().load_daily_bars("fixture")

    assert isinstance(importer, FakeImporter)
    assert entry.loaded is True


def test_missing_plugin_is_not_replaced_by_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plugins,
        "source_entry_points",
        lambda **_: cast(Any, ()),
    )

    with pytest.raises(ValueError, match="exactly one"):
        plugins.SourcePluginRegistry().load_daily_bars("missing")
