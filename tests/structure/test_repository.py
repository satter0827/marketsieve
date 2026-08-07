from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from scripts.package_catalog import load_package_catalog

ROOT = Path(__file__).parents[2]


def test_license_copies_match() -> None:
    root_license = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert all(
        (spec.path / "LICENSE").read_text(encoding="utf-8") == root_license
        for spec in load_package_catalog(ROOT)
    )


def test_readmes_expose_the_self_contained_matrix_path() -> None:
    readmes = tuple(
        (ROOT / name).read_text(encoding="utf-8") for name in ("README.md", "README.ja.md")
    )
    for command in ("make daily-status", "make market-matrix", "marketsieve matrix query"):
        assert all(command in document for document in readmes)


def test_workspace_package_versions_and_tool_catalog_match() -> None:
    workspace = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    specs = load_package_catalog(ROOT)
    relative_paths = {spec.path.relative_to(ROOT).as_posix() for spec in specs}
    source_paths = {f"{path}/src" for path in relative_paths}
    modules = {spec.module for spec in specs}

    assert len({spec.project_version for spec in specs}) == 1
    assert set(workspace["tool"]["uv"]["workspace"]["members"]) == relative_paths
    assert source_paths <= set(workspace["tool"]["ruff"]["src"])
    assert source_paths <= set(workspace["tool"]["mypy"]["files"])
    assert modules == set(workspace["tool"]["importlinter"]["root_packages"])
    assert modules == set(workspace["tool"]["coverage"]["run"]["source"])
    assert {spec.distribution for spec in specs}.isdisjoint({"marketsieve-agent", "marketsieve-ai"})


def test_generated_state_is_centralized() -> None:
    forbidden = (
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".coverage",
        "coverage.json",
        "htmlcov",
        "dist",
        "build",
    )
    assert [name for name in forbidden if (ROOT / name).exists()] == []


def test_ignore_files_exclude_private_key_suffixes() -> None:
    required = {"*.key", "*.pem", "*.p12", "*.pfx", "*.private-key"}
    for name in (".gitignore", ".dockerignore"):
        assert required <= set((ROOT / name).read_text(encoding="utf-8").splitlines())


def test_vscode_is_an_ascii_operational_entry_point() -> None:
    vscode = ROOT / ".vscode"
    assert {path.name for path in vscode.glob("*.json")} == {
        "extensions.json",
        "launch.json",
        "settings.json",
        "tasks.json",
    }
    assert all(
        all(ord(character) < 128 for character in path.read_text(encoding="utf-8"))
        for path in vscode.glob("*.json")
    )

    settings = json.loads((vscode / "settings.json").read_text(encoding="utf-8"))
    assert settings["python.defaultInterpreterPath"] == "${workspaceFolder}/.venv/bin/python"
    assert settings["python.testing.pytestArgs"] == ["tests"]
    assert settings["python.testing.pytestEnabled"] is True

    launch_document = json.loads((vscode / "launch.json").read_text(encoding="utf-8"))
    launches = launch_document["configurations"]
    assert [item["name"] for item in launches] == [
        "01 First Run: Create Configuration",
        "02 First Run: Import Rakuten Portfolio",
        "03 Daily Use: Check Readiness",
        "10 Market Matrix: Refresh All Indices (Network)",
        "30 Watchlist: Add Instrument",
        "40 Daily Use: Analyze JP Watchlist (Network)",
        "50 Daily Use: Analyze US Watchlist (Network)",
        "60 Weekly Use: Build Brief",
        "90 Debug: CLI Command",
        "91 Debug: JP Daily Analysis",
    ]
    assert [item["command"] for item in launches[:8]] == [
        "make setup-config",
        "make portfolio-import BROKER=rakuten",
        "make daily-status",
        "make market-matrix",
        "make watchlist-add",
        "make daily-jp",
        "make daily-us",
        "make weekly",
    ]
    assert all(item["type"] == "node-terminal" for item in launches[:8])
    assert all(item["type"] == "debugpy" for item in launches[8:])
    assert all(item["module"] == "marketsieve_cli" for item in launches[8:])
    assert launches[9]["args"] == ["--config", "marketsieve.toml", "daily", "jp"]

    task_document = json.loads((vscode / "tasks.json").read_text(encoding="utf-8"))
    tasks = task_document["tasks"]
    assert all(task["type"] == "process" and task["command"] == "make" for task in tasks)
    assert {task["label"].partition(":")[0] for task in tasks} == {
        "First Run",
        "Market Matrix",
        "Daily",
        "Developer",
    }
    assert {entry["id"] for entry in task_document["inputs"]} == {
        "portfolioPath",
        "instrument",
    }
    make_targets = set(
        re.findall(r"^([a-zA-Z0-9_-]+):", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M)
    )
    assert {task["args"][0] for task in tasks} <= make_targets


def test_synthetic_timezones_work_without_an_os_timezone_database() -> None:
    code = """
from zoneinfo import reset_tzpath
reset_tzpath(())
from marketsieve.synthetic.daily import JP_INSTRUMENT, US_INSTRUMENT
assert JP_INSTRUMENT.exchange_timezone.key == "Asia/Tokyo"
assert US_INSTRUMENT.exchange_timezone.key == "America/New_York"
"""
    environment = os.environ.copy()
    environment["PYTHONTZPATH"] = ""
    subprocess.run([sys.executable, "-c", code], check=True, env=environment)


def test_makefile_exposes_stable_operational_and_developer_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    targets = {
        "help",
        "setup-config",
        "portfolio-import",
        "portfolio-show",
        "daily-status",
        "market-matrix",
        "watchlist-add",
        "watchlist-remove",
        "watchlist-show",
        "daily-jp",
        "daily-us",
        "weekly",
        "sync",
        "format",
        "format-check",
        "lint",
        "typecheck",
        "test",
        "check",
        "evidence",
        "build",
    }
    assert all(f"{target}:" in makefile for target in targets)
    assert makefile.index("market-matrix:") < makefile.index("sync:")
    assert 'uv run marketsieve --config "$(CONFIG)" matrix refresh' in makefile
    assert '"$(origin CONFIG)" != "file"' in makefile
    assert "scripts.portfolio_check" in makefile
    assert "ai prepare" not in makefile and "ai import" not in makefile


def test_setup_config_is_idempotent_and_does_not_overwrite(tmp_path: Path) -> None:
    config_directory = tmp_path / "directory with spaces"
    config_directory.mkdir()
    config = config_directory / "marketsieve.toml"
    first = subprocess.run(
        ["make", "setup-config", f"CONFIG={config}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert config.read_bytes() == (ROOT / "marketsieve.example.toml").read_bytes()
    assert "Created configuration" in first.stdout

    config.write_text("sentinel = true\n", encoding="utf-8")
    second = subprocess.run(
        ["make", "setup-config", f"CONFIG={config}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert config.read_text(encoding="utf-8") == "sentinel = true\n"
    assert "already exists" in second.stdout


def test_market_matrix_rejects_a_missing_environment_configuration(tmp_path: Path) -> None:
    config = tmp_path / "missing.toml"
    environment = {**os.environ, "CONFIG": str(config)}

    result = subprocess.run(
        ["make", "market-matrix"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 2
    assert f"Configuration file not found: {config}" in result.stderr


def test_daily_status_rejects_invalid_configuration_before_portfolio_check(
    tmp_path: Path,
) -> None:
    config = tmp_path / "invalid.toml"
    config.write_text("not = [valid\n", encoding="utf-8")
    result = subprocess.run(
        ["make", "daily-status", f"CONFIG={config}", f"STATE_DIR={tmp_path / 'state'}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "[invalid] configuration" in result.stdout
    assert "correct" in result.stderr


def test_daily_status_rejects_invalid_configuration_before_uv(tmp_path: Path) -> None:
    config = tmp_path / "invalid.toml"
    config.write_text("not = [valid\n", encoding="utf-8")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    uv = binaries / "uv"
    uv.write_text("#!/bin/sh\necho uv-was-invoked\nexit 99\n", encoding="utf-8")
    uv.chmod(0o755)
    environment = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"}

    result = subprocess.run(
        ["make", "daily-status", f"CONFIG={config}", f"STATE_DIR={tmp_path / 'state'}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 2
    assert "[invalid] configuration" in result.stdout
    assert "uv-was-invoked" not in result.stdout


def test_daily_status_uses_the_project_python_before_uv() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    syntax_check = makefile.index("scripts.configuration_check --syntax-only")
    doctor = makefile.index("uv run marketsieve doctor")

    assert "CONFIGURATION_PYTHON ?= .venv/bin/python" in makefile
    assert syntax_check < doctor


def test_ci_and_rulesets_use_stable_gate_names() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "name: Develop Gate" in workflow
    assert "name: Evidence Gate" in workflow
    assert "name: Release Gate" in workflow
    assert workflow.count("fetch-depth: 0") == 2
    assert workflow.count("enable-cache: false") == workflow.count("astral-sh/setup-uv@")

    develop = json.loads((ROOT / ".github/rulesets/develop.json").read_text(encoding="utf-8"))
    main = json.loads((ROOT / ".github/rulesets/main.json").read_text(encoding="utf-8"))
    develop_checks = develop["rules"][-1]["parameters"]["required_status_checks"]
    main_checks = main["rules"][-1]["parameters"]["required_status_checks"]
    assert {check["context"] for check in develop_checks} == {
        "Pre-PR Review",
        "Develop Gate",
        "Evidence Gate",
    }
    assert {check["context"] for check in main_checks} == {"Release Gate"}
