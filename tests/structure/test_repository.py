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
    package_licenses = tuple(
        (spec.path / "LICENSE").read_text(encoding="utf-8") for spec in load_package_catalog(ROOT)
    )

    assert all(package_license == root_license for package_license in package_licenses)


def test_readmes_show_the_same_commands() -> None:
    commands = (
        "make sync",
        "make doctor",
        "make test",
        "make check",
        "make build",
        "make capabilities-json",
    )
    readmes = (
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "README.ja.md").read_text(encoding="utf-8"),
    )

    for command in commands:
        assert all(command in readme for readme in readmes)


def test_workspace_package_versions_match() -> None:
    versions = {spec.project_version for spec in load_package_catalog(ROOT)}

    assert len(versions) == 1


def test_public_package_catalog_drives_workspace_tools() -> None:
    workspace = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    specs = load_package_catalog(ROOT)
    relative_paths = {spec.path.relative_to(ROOT).as_posix() for spec in specs}
    source_paths = {f"{path}/src" for path in relative_paths}
    modules = {spec.module for spec in specs}

    assert set(workspace["tool"]["uv"]["workspace"]["members"]) == relative_paths
    assert source_paths <= set(workspace["tool"]["ruff"]["src"])
    assert source_paths <= set(workspace["tool"]["mypy"]["files"])
    assert modules == set(workspace["tool"]["importlinter"]["root_packages"])
    assert modules == set(workspace["tool"]["coverage"]["run"]["source"])


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
        patterns = set((ROOT / name).read_text(encoding="utf-8").splitlines())
        assert required <= patterns


def test_vscode_configuration_uses_installed_workspace_contracts() -> None:
    vscode = ROOT / ".vscode"
    assert {path.name for path in vscode.glob("*.json")} == {
        "extensions.json",
        "launch.json",
        "settings.json",
        "tasks.json",
    }

    workspace = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_names = {
        re.split(r"[<>=!~\[]", dependency, maxsplit=1)[0]
        for dependency in workspace["dependency-groups"]["dev"]
    }
    assert {"coverage", "pytest", "pytest-cov"} <= dependency_names

    settings = json.loads((vscode / "settings.json").read_text(encoding="utf-8"))
    assert settings["python.defaultInterpreterPath"] == "${workspaceFolder}/.venv/bin/python"
    assert settings["python.testing.pytestArgs"] == ["tests"]
    assert settings["python.testing.pytestEnabled"] is True
    assert settings["python.testing.unittestEnabled"] is False

    tasks = json.loads((vscode / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    commands = {task["command"] for task in tasks}
    assert commands == {
        "make check",
        "make doctor",
        "make format",
        "make sync",
        "make test TEST=${relativeFile}",
        "make evidence",
        "make evidence-validate",
        "make capabilities-json",
    }
    make_targets = set(
        re.findall(r"^([a-zA-Z0-9_-]+):", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M)
    )
    referenced_targets = {
        command.removeprefix("make ").split(maxsplit=1)[0] for command in commands
    }
    assert referenced_targets <= make_targets

    launch_document = json.loads((vscode / "launch.json").read_text(encoding="utf-8"))
    launches = launch_document["configurations"]
    launches_by_name = {launch["name"]: launch for launch in launches}
    assert len(launches_by_name) == len(launches)
    assert launches_by_name["App: Command (Prompt for Arguments)"]["args"] == (
        "${command:pickArgs}"
    )

    command_paths = {
        "App: Doctor": ("doctor",),
        "App: Capabilities JSON": ("capabilities",),
        "Data: Source List": ("source", "list"),
        "Data: Import Example CSV": ("source", "import"),
        "Data: Source Doctor": ("source", "doctor"),
        "Data: Source Fetch (Network)": ("source", "fetch"),
        "Data: Snapshot List": ("snapshot", "list"),
        "Data: Snapshot Show": ("snapshot", "show"),
        "Data: Snapshot Verify": ("snapshot", "verify"),
        "Analysis: Inspect": ("inspect",),
        "Analysis: Indicator": ("analyze",),
        "Analysis: Compare": ("compare",),
        "Portfolio: Import": ("portfolio", "import"),
        "Portfolio: Show Latest": ("portfolio", "show"),
        "Screen: Update (Network)": ("screen", "update"),
        "Screen: Run Offline": ("screen", "run"),
        "Brief: Daily (Network)": ("daily",),
        "Brief: Weekly Offline": ("weekly",),
        "Report: List": ("report", "list"),
        "Report: Show": ("report", "show"),
        "Report: Explain Dry Run": ("report", "explain"),
        "Experiment: Run": ("experiment", "run"),
        "Agent: Doctor": ("agent", "doctor"),
    }
    assert set(launches_by_name) == {"App: Command (Prompt for Arguments)", *command_paths}

    input_ids = {entry["id"] for entry in launch_document["inputs"]}
    assert len(input_ids) == len(launch_document["inputs"])
    inputs_by_id = {entry["id"]: entry for entry in launch_document["inputs"]}
    assert all(
        "${workspaceFolder}" not in str(entry.get("default", ""))
        for entry in launch_document["inputs"]
    )
    example_manifest = json.loads(
        (ROOT / "examples/csv-daily-bars/manifest.json").read_text(encoding="utf-8")
    )
    assert inputs_by_id["sourceProfile"]["default"] == example_manifest["source_profile"]
    example_configuration = tomllib.loads(
        (ROOT / "marketsieve.example.toml").read_text(encoding="utf-8")
    )
    assert (
        inputs_by_id["configuredSourceProfile"]["default"]
        in example_configuration["source_profiles"]
    )
    assert "default" not in inputs_by_id["secondInstrument"]
    input_pattern = re.compile(r"\$\{input:([^}]+)\}")
    for launch in launches:
        assert launch["type"] == "debugpy"
        assert launch["request"] == "launch"
        assert launch["module"] == "marketsieve_cli"
        assert launch["console"] == "integratedTerminal"
        assert launch["justMyCode"] is True
        assert (
            launch.get("env", {}).get("PYTHONPYCACHEPREFIX")
            == "${workspaceFolder}/.marketsieve/cache/python"
        )

        serialized = json.dumps(launch)
        assert set(input_pattern.findall(serialized)) <= input_ids

    for name, command_path in command_paths.items():
        args = launches_by_name[name]["args"]
        assert tuple(args[: len(command_path)]) == command_path
        environment = os.environ.copy()
        environment["PYTHONPYCACHEPREFIX"] = str(ROOT / ".marketsieve/cache/python")
        subprocess.run(
            [sys.executable, "-m", "marketsieve_cli", *command_path, "--help"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    for name in ("App: Doctor", "App: Capabilities JSON"):
        launch = launches_by_name[name]
        subprocess.run(
            [sys.executable, "-m", launch["module"], *launch["args"]],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )


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


def test_makefile_exposes_stable_entry_points() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    targets = (
        "help",
        "sync",
        "format",
        "format-check",
        "lint",
        "typecheck",
        "test",
        "secret-check",
        "check",
        "doctor",
        "capabilities-json",
        "build",
        "clean-generated",
        "evidence",
        "evidence-bundle",
        "evidence-validate",
        "review-attest",
        "governance-check",
        "release-build",
        "release-verify",
        "release-check",
    )

    for target in targets:
        assert f"{target}:" in makefile


def test_ci_and_rulesets_use_stable_gate_names() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "name: Develop Gate" in workflow
    assert "name: Evidence Gate" in workflow
    assert "name: Review Gate" not in workflow
    assert "name: Release Gate" in workflow
    assert workflow.count("fetch-depth: 0") == 2
    assert 'make check BASE_SHA="$BASE_SHA"' in workflow
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert workflow.count(".marketsieve/artifacts/checks/${{ github.sha }}") == 0
    assert workflow.count("uv build") == 0
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
