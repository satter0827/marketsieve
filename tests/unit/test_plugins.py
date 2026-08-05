from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from marketsieve_cli.adapters import plugins
from marketsieve_extension_api import (
    DailyBarFetchRequest,
    DailyBarSourceConfiguration,
    EconomicSeriesFetchRequest,
    EconomicSeriesSourceConfiguration,
    ImportedDailyBars,
    ImportedEconomicSeries,
    SourceDiagnostic,
)


class FakeDistribution:
    name = "marketsieve-source-fixture"
    version = "1.2.3"


class FakeImporter:
    def import_bundle(self, path: Path) -> ImportedDailyBars:
        raise NotImplementedError(path)


class FakeFetcher:
    def doctor(self, configuration: DailyBarSourceConfiguration) -> SourceDiagnostic:
        return SourceDiagnostic(True, "ready", str(configuration))

    def fetch(self, request: DailyBarFetchRequest) -> ImportedDailyBars:
        raise NotImplementedError(request)


class FakeEconomicFetcher:
    def doctor_economic_series(
        self, configuration: EconomicSeriesSourceConfiguration
    ) -> SourceDiagnostic:
        return SourceDiagnostic(True, "ready", str(configuration))

    def fetch_economic_series(self, request: EconomicSeriesFetchRequest) -> ImportedEconomicSeries:
        raise NotImplementedError(request)


class FakeEntryPoint:
    name = "fixture"
    value = "fixture:FakeImporter"
    dist = FakeDistribution()

    def __init__(self) -> None:
        self.loaded = False

    def load(self) -> type[FakeImporter]:
        self.loaded = True
        return FakeImporter


class FakeFetchEntryPoint:
    name = "fixture"
    value = "fixture:FakeFetcher"
    dist = FakeDistribution()

    def __init__(self) -> None:
        self.loaded = False

    def load(self) -> type[FakeFetcher]:
        self.loaded = True
        return FakeFetcher


class FakeEconomicEntryPoint:
    name = "fixture"
    value = "fixture:FakeEconomicFetcher"
    dist = FakeDistribution()

    def __init__(self) -> None:
        self.loaded = False

    def load(self) -> type[FakeEconomicFetcher]:
        self.loaded = True
        return FakeEconomicFetcher


def test_source_listing_does_not_import_plugin_code(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = FakeEntryPoint()
    monkeypatch.setattr(
        plugins,
        "source_entry_points",
        lambda **_: cast(Any, (entry,)),
    )
    monkeypatch.setattr(plugins, "importer_entry_points", lambda: cast(Any, (entry,)))
    monkeypatch.setattr(plugins, "fetcher_entry_points", lambda: cast(Any, ()))
    monkeypatch.setattr(plugins, "financial_entry_points", lambda: cast(Any, ()))
    monkeypatch.setattr(plugins, "event_entry_points", lambda: cast(Any, ()))
    monkeypatch.setattr(plugins, "economic_series_entry_points", lambda: cast(Any, ()))

    installed = plugins.SourcePluginRegistry().installed()

    assert installed[0].distribution == "marketsieve-source-fixture"
    assert installed[0].data_kinds == ("daily_bars",)
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


def test_explicit_fetch_plugin_uses_the_network_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = FakeFetchEntryPoint()
    monkeypatch.setattr(plugins, "source_entry_points", lambda **_: cast(Any, (entry,)))

    fetcher = plugins.SourcePluginRegistry().load_fetcher("fixture")

    assert isinstance(fetcher, FakeFetcher)
    assert entry.loaded is True


def test_fetch_capability_is_read_without_loading_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = FakeFetchEntryPoint()
    monkeypatch.setattr(
        plugins,
        "fetcher_entry_points",
        lambda: cast(Any, (entry,)),
    )

    assert plugins.SourcePluginRegistry().can_fetch("fixture") is True
    assert plugins.SourcePluginRegistry().can_fetch("csv") is False
    assert entry.loaded is False


def test_explicit_economic_series_plugin_uses_its_small_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = FakeEconomicEntryPoint()
    monkeypatch.setattr(plugins, "source_entry_points", lambda **_: cast(Any, (entry,)))

    fetcher = plugins.SourcePluginRegistry().load_economic_series_fetcher("fixture")

    assert isinstance(fetcher, FakeEconomicFetcher)
    assert entry.loaded is True
