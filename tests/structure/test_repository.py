from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from scripts.package_catalog import load_package_catalog

ROOT = Path(__file__).parents[2]


def test_workspace_contains_only_the_supported_public_packages() -> None:
    workspace = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    specs = load_package_catalog(ROOT)

    assert {spec.distribution for spec in specs} == {
        "marketsieve",
        "marketsieve-extension-api",
        "marketsieve-cli",
        "marketsieve-source-yfinance",
    }
    assert set(workspace["tool"]["uv"]["workspace"]["members"]) == {
        spec.path.relative_to(ROOT).as_posix() for spec in specs
    }
    assert all(spec.project_version == "0.16.0" for spec in specs)


def test_removed_capabilities_and_packages_are_absent() -> None:
    for name in (
        "import-rakuten",
        "source-csv",
        "source-jquants",
        "source-alphavantage",
        "source-fred",
        "source-sec",
        "source-edinet",
    ):
        assert not (ROOT / "packages" / name / "pyproject.toml").exists()
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "packages/cli/src/marketsieve_cli").rglob("*.py")
    )
    for removed in ("PortfolioStore", "WatchlistStore", "ExperimentService", "SnapshotService"):
        assert removed not in source


def test_makefile_has_explicit_inputs_and_no_legacy_workflows() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"^([a-zA-Z0-9_-]+):", makefile, re.M))

    assert {
        "market-build",
        "market-resume",
        "market-list",
        "market-show",
        "market-query",
        "market-security",
        "market-compare",
        "market-diff",
        "research-build",
        "research-list",
        "research-show",
        "doctor",
        "check",
        "build",
    } <= targets
    for removed in ("portfolio-import:", "watchlist-add:", "daily-jp:", "weekly:"):
        assert removed not in makefile
    assert "--settings" in makefile and "--config" not in makefile
    assert "uv run python scripts/" not in makefile


def test_vscode_exposes_simple_launches_and_complete_tasks_in_english() -> None:
    vscode = ROOT / ".vscode"
    launch = json.loads((vscode / "launch.json").read_text(encoding="utf-8"))
    tasks = json.loads((vscode / "tasks.json").read_text(encoding="utf-8"))
    settings = json.loads((vscode / "settings.json").read_text(encoding="utf-8"))

    assert [item["name"] for item in launch["configurations"]] == [
        "01 Market: Capture JP Close (Network)",
        "02 Market: Capture US Close (Network)",
        "03 Market: Preview Latest Explorer",
        "04 Market: Explore Swing Candidates",
        "05 Research: Build Security Evidence (Network)",
        "06 Research: Preview Latest Explorer",
    ]
    assert {item["label"].partition(":")[0] for item in tasks["tasks"]} == {
        "Setup",
        "Market",
        "Research",
        "Developer",
    }
    assert settings["files.exclude"]["**/.marketsieve"] is False
    assert settings["files.watcherExclude"]["**/.marketsieve/**"] is True
    assert all(
        all(ord(character) < 128 for character in path.read_text(encoding="utf-8"))
        for path in vscode.glob("*.json")
    )


def test_generated_state_and_private_files_are_not_tracked() -> None:
    assert ".marketsieve/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    required = {"*.key", "*.pem", "*.p12", "*.pfx", "*.private-key"}
    assert required <= set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())


def test_license_copies_match() -> None:
    root_license = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert all(
        (spec.path / "LICENSE").read_text(encoding="utf-8") == root_license
        for spec in load_package_catalog(ROOT)
    )
