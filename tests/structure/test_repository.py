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
    assert all(
        all(ord(character) < 128 for character in path.read_text(encoding="utf-8"))
        for path in vscode.glob("*.json")
    )

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

    tasks_document = json.loads((vscode / "tasks.json").read_text(encoding="utf-8"))
    tasks = tasks_document["tasks"]
    assert [task["label"] for task in tasks] == [
        "01 First Run: Create Configuration",
        "02 First Run: Import Portfolio CSV",
        "03 First Run: Check Readiness",
        "10 Daily: Analyze JP Close and Prepare ChatGPT Request (Network)",
        "20 Daily: Analyze US Close and Prepare ChatGPT Request (Network)",
        "30 Weekly: Build Brief and Prepare ChatGPT Request (After JP and US)",
        "40 ChatGPT: Import Saved Response and Show Explanation",
        "Advanced: Prepare ChatGPT Request from Latest Report",
        "Advanced: Show Portfolio",
        "Advanced: Import ChatGPT Response Only",
        "Advanced: Show Latest AI Explanation Only",
        "Developer: Sync",
        "Developer: Format",
        "Developer: Test Current File",
        "Developer: Check",
        "Developer: Review Evidence",
    ]
    commands = [" ".join([task["command"], *task.get("args", [])]) for task in tasks]
    assert commands == [
        "make setup-config",
        "make portfolio-import PORTFOLIO=${input:portfolioPath} BROKER=${input:portfolioBroker}",
        "make daily-status",
        "make daily-jp-ai",
        "make daily-us-ai",
        "make weekly-ai",
        "make ai-import-show RESPONSE=${input:aiResponsePath} CONTROLLED=${input:aiControlled}",
        "make ai-prepare",
        "make portfolio-show",
        "make ai-import RESPONSE=${input:aiResponsePath} CONTROLLED=${input:aiControlled}",
        "make ai-show",
        "make sync",
        "make format",
        "make test TEST=${relativeFile}",
        "make check",
        "make evidence",
    ]
    import_task = tasks[6]
    assert import_task["type"] == "process"
    assert import_task["command"] == "make"
    assert import_task["args"] == [
        "ai-import-show",
        "RESPONSE=${input:aiResponsePath}",
        "CONTROLLED=${input:aiControlled}",
    ]
    assert all(task["type"] == "process" for task in tasks[:11])
    assert all("detail" in task for task in tasks[:7])
    task_input_ids = {entry["id"] for entry in tasks_document["inputs"]}
    assert task_input_ids == {
        "portfolioPath",
        "portfolioBroker",
        "aiResponsePath",
        "aiControlled",
    }
    task_input_pattern = re.compile(r"\$\{input:([^}]+)\}")
    assert all(
        set(task_input_pattern.findall(json.dumps(task))) <= task_input_ids for task in tasks
    )
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
    operational_launches = launches[:7]
    assert [launch["name"] for launch in operational_launches] == [
        task["label"] for task in tasks[:7]
    ]
    assert [launch["command"] for launch in operational_launches] == [
        "make setup-config",
        "make portfolio-import",
        "make daily-status",
        "make daily-jp-ai",
        "make daily-us-ai",
        "make weekly-ai",
        "make ai-import-show",
    ]
    assert all(launch["type"] == "node-terminal" for launch in operational_launches)
    assert all(launch["request"] == "launch" for launch in operational_launches)
    assert all(launch["cwd"] == "${workspaceFolder}" for launch in operational_launches)
    assert operational_launches[1]["env"] == {
        "PORTFOLIO": "${input:portfolioPath}",
        "BROKER": "${input:portfolioBroker}",
    }
    assert operational_launches[6]["env"] == {
        "RESPONSE": "${input:aiResponsePath}",
        "CONTROLLED": "${input:aiControlled}",
    }

    debug_launches = launches[7:]
    debug_by_name = {launch["name"]: launch for launch in debug_launches}
    assert set(debug_by_name) == {
        "Advanced: Debug CLI Command",
        "Advanced: Debug ChatGPT Request Preparation (Existing Report Required)",
        "Advanced: Debug ChatGPT Response Import",
    }
    assert debug_by_name["Advanced: Debug CLI Command"]["args"] == ("${command:pickArgs}")
    assert all(not launch["name"].startswith(("Developer", "Debug")) for launch in launches)

    input_ids = {entry["id"] for entry in launch_document["inputs"]}
    assert len(input_ids) == len(launch_document["inputs"])
    assert input_ids == {
        "portfolioPath",
        "portfolioBroker",
        "aiResponsePath",
        "aiControlled",
    }
    assert all(
        "${workspaceFolder}" not in str(entry.get("default", ""))
        for entry in launch_document["inputs"]
    )
    input_pattern = re.compile(r"\$\{input:([^}]+)\}")
    assert all(set(input_pattern.findall(json.dumps(launch))) <= input_ids for launch in launches)
    for launch in debug_launches:
        assert launch["type"] == "debugpy"
        assert launch["request"] == "launch"
        assert launch["module"] == "marketsieve_cli"
        assert launch["console"] == "integratedTerminal"
        assert launch["justMyCode"] is True
        assert (
            launch.get("env", {}).get("PYTHONPYCACHEPREFIX")
            == "${workspaceFolder}/.marketsieve/cache/python"
        )

    assert debug_by_name["Advanced: Debug ChatGPT Request Preparation (Existing Report Required)"][
        "args"
    ] == [
        "ai",
        "prepare",
        "report",
        "latest",
    ]
    assert debug_by_name["Advanced: Debug ChatGPT Response Import"]["args"][:2] == [
        "ai",
        "import",
    ]


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
        "setup-config",
        "portfolio-import",
        "portfolio-show",
        "daily-status",
        "daily-jp-ai",
        "daily-us-ai",
        "weekly-ai",
        "ai-prepare",
        "ai-import",
        "ai-import-show",
        "ai-show",
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

    for target, report_command in (
        ("daily-jp-ai", "daily jp"),
        ("daily-us-ai", "daily us"),
        ("weekly-ai", "weekly"),
    ):
        recipe = makefile.split(f"{target}:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
        assert recipe.index(report_command) < recipe.index("ai prepare report latest")
    assert makefile.index("daily-jp-ai:") < makefile.index("sync:")
    assert makefile.index("setup-config:") < makefile.index("daily-jp-ai:")
    assert "daily-jp-ai: ## Daily JP close report (Network)" in makefile
    assert "daily-us-ai: ## Daily US close report (Network)" in makefile
    ai_import_show_recipe = makefile.split("ai-import-show:", maxsplit=1)[1].split(
        "\n\n", maxsplit=1
    )[0]
    assert "ai-import-show: ai-import" in makefile
    assert "ai show latest" not in ai_import_show_recipe


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
    assert str(config) in first.stdout

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


def test_daily_status_rejects_an_invalid_configuration_before_portfolio_check(
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
    assert "[missing] portfolio" not in result.stderr


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
