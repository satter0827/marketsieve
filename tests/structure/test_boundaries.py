from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
SDK_SOURCE = ROOT / "packages" / "core" / "src" / "marketsieve"
FORBIDDEN_SDK_IMPORTS = {
    "click",
    "http",
    "logging",
    "marketsieve_cli",
    "marketsieve_agent",
    "marketsieve_extension_api",
    "marketsieve_source_csv",
    "marketsieve_source_jquants",
    "marketsieve_source_alphavantage",
    "os",
    "smtplib",
    "sqlite3",
    "tomllib",
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def test_sdk_has_no_application_or_io_imports() -> None:
    violations = {
        str(path.relative_to(ROOT)): sorted(imported_roots(path) & FORBIDDEN_SDK_IMPORTS)
        for path in SDK_SOURCE.rglob("*.py")
        if imported_roots(path) & FORBIDDEN_SDK_IMPORTS
    }

    assert violations == {}


def test_application_depends_on_public_sdk() -> None:
    application_source = ROOT / "packages" / "cli" / "src" / "marketsieve_cli"
    imports = set().union(*(imported_roots(path) for path in application_source.rglob("*.py")))

    assert "marketsieve" in imports


def test_agent_is_independent_from_cli_sources_and_io() -> None:
    agent_source = ROOT / "packages" / "agent" / "src" / "marketsieve_agent"
    imports = set().union(*(imported_roots(path) for path in agent_source.rglob("*.py")))

    assert not imports & {
        "click",
        "http",
        "marketsieve",
        "marketsieve_cli",
        "marketsieve_extension_api",
        "marketsieve_source_csv",
        "marketsieve_source_jquants",
        "marketsieve_source_alphavantage",
        "os",
    }


def test_extension_and_source_packages_follow_inward_dependencies() -> None:
    extension = ROOT / "packages/extension-api/src/marketsieve_extension_api"
    csv_source = ROOT / "packages/source-csv/src/marketsieve_source_csv"
    jquants_source = ROOT / "packages/source-jquants/src/marketsieve_source_jquants"
    alphavantage_source = ROOT / "packages/source-alphavantage/src/marketsieve_source_alphavantage"
    extension_imports = set().union(*(imported_roots(path) for path in extension.rglob("*.py")))
    csv_imports = set().union(*(imported_roots(path) for path in csv_source.rglob("*.py")))
    jquants_imports = set().union(*(imported_roots(path) for path in jquants_source.rglob("*.py")))
    alphavantage_imports = set().union(
        *(imported_roots(path) for path in alphavantage_source.rglob("*.py"))
    )

    assert "marketsieve" in extension_imports
    assert (
        "marketsieve_cli"
        not in extension_imports | csv_imports | jquants_imports | alphavantage_imports
    )
    assert "marketsieve_source_csv" not in extension_imports
    assert "marketsieve_extension_api" in csv_imports
    assert "marketsieve_extension_api" in jquants_imports
    assert "marketsieve_extension_api" in alphavantage_imports


def test_analysis_and_synthetic_sources_do_not_reference_each_other() -> None:
    analysis = SDK_SOURCE / "analysis"
    synthetic = SDK_SOURCE / "synthetic"
    analysis_imports = {
        node.module
        for path in analysis.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    synthetic_imports = {
        node.module
        for path in synthetic.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not any(module.startswith("marketsieve.synthetic") for module in analysis_imports)
    assert not any(module.startswith("marketsieve.analysis") for module in synthetic_imports)


def test_cli_depends_on_composition_root_only() -> None:
    cli_source = ROOT / "packages/cli/src/marketsieve_cli/interfaces/cli"
    internal_imports = {
        node.module
        for path in cli_source.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("marketsieve_cli")
    }

    assert internal_imports <= {
        "marketsieve_cli.bootstrap",
        "marketsieve_cli.interfaces.cli.main",
    }


def test_application_does_not_depend_on_output_adapters() -> None:
    application = ROOT / "packages/cli/src/marketsieve_cli/application"
    imports = {
        node.module
        for path in application.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not any(module.startswith("marketsieve_cli.adapters") for module in imports)
