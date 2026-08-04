"""Deterministic source checks and evidence generation for develop changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]
STATE_ROOT = ROOT / ".marketsieve"
RUNTIME_WHEELHOUSE = STATE_ROOT / "cache" / "runtime-wheelhouse"


def run(command: Sequence[str], *, cwd: Path = ROOT) -> None:
    """Run a command and fail immediately when it is unsuccessful."""

    subprocess.run(command, cwd=cwd, check=True)


def capture(command: Sequence[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    """Run a command and capture separate text streams."""

    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)


def head_sha() -> str:
    return capture(("git", "rev-parse", "HEAD")).stdout.strip()


def evidence_dir() -> Path:
    configured = os.environ.get("EVIDENCE_DIR")
    return Path(configured) if configured else STATE_ROOT / "artifacts" / "checks" / head_sha()


def reset_evidence(path: Path) -> None:
    resolved = path.resolve()
    state = STATE_ROOT.resolve()
    if state not in resolved.parents:
        raise RuntimeError("evidence directory must be inside .marketsieve")
    shutil.rmtree(resolved, ignore_errors=True)
    resolved.mkdir(parents=True)


def check_quality() -> None:
    run(("uv", "run", "ruff", "format", "--check", "."))
    run(("uv", "run", "ruff", "check", "."))
    run(("uv", "run", "mypy"))
    run(
        (
            "uv",
            "run",
            "lint-imports",
            "--cache-dir",
            str(STATE_ROOT / "cache" / "import-linter"),
        )
    )
    if (ROOT / ".git").exists():
        run(("git", "diff", "--check"))


def check_structure() -> None:
    run(("uv", "run", "pytest", "tests/structure"))


def check_tests(path: Path) -> None:
    coverage_dir = STATE_ROOT / "coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)
    junit = path / "junit.xml"
    coverage_json = path / "coverage.json"
    run(
        (
            "uv",
            "run",
            "coverage",
            "run",
            "-m",
            "pytest",
            f"--junitxml={junit}",
        )
    )
    run(("uv", "run", "coverage", "report"))
    run(("uv", "run", "coverage", "json", "-o", str(coverage_json)))


def validate_schemas() -> None:
    schemas = sorted((ROOT / "schemas").glob("*/v*/schema.json"))
    if not schemas:
        raise RuntimeError("at least one versioned schema is required")
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def check_smoke(path: Path) -> None:
    version = capture(("uv", "run", "marketsieve", "--version"))
    doctor = capture(
        ("uv", "run", "marketsieve", "--log-level", "INFO", "doctor", "--output", "json")
    )
    module = capture(("uv", "run", "python", "-m", "marketsieve_cli", "doctor", "--output", "json"))
    capabilities = capture(("uv", "run", "marketsieve", "capabilities", "--output", "json"))
    report_first = capture(
        ("uv", "run", "marketsieve", "--log-level", "INFO", "report", "--output", "json")
    )
    report_second = capture(("uv", "run", "marketsieve", "report", "--output", "json"))
    if report_first.stdout != report_second.stdout:
        raise RuntimeError("historical report JSON is not reproducible")
    documents = {
        "doctor-result": json.loads(doctor.stdout),
        "capabilities-result": json.loads(capabilities.stdout),
        "report-result": json.loads(report_first.stdout),
    }
    for name, document in documents.items():
        major = "v2" if name == "capabilities-result" else "v1"
        schema = json.loads(
            (ROOT / f"schemas/{name}/{major}/schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    smoke = {
        "version": {"exit_code": version.returncode, "stdout": version.stdout},
        "doctor": {"exit_code": doctor.returncode, "result": documents["doctor-result"]},
        "module_doctor": {"exit_code": module.returncode, "result": json.loads(module.stdout)},
        "capabilities": {
            "exit_code": capabilities.returncode,
            "result": documents["capabilities-result"],
        },
        "report": {
            "exit_code": report_first.returncode,
            "schema_valid": True,
            "reproducible": True,
            "reports": documents["report-result"]["reports"],
        },
    }
    (path / "smoke.json").write_text(
        json.dumps(smoke, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    logs = doctor.stderr + report_first.stderr
    (path / "logs.jsonl").write_text(logs, encoding="utf-8")

    log_schema = json.loads(
        (ROOT / "schemas/log-record/v1/schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(log_schema)
    for line in logs.splitlines():
        validator.validate(json.loads(line))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_core_wheel(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = sorted(archive.namelist())
    required = ("marketsieve/__init__.py", "marketsieve/py.typed")
    if any(not any(name.endswith(suffix) for name in names) for suffix in required):
        raise RuntimeError("wheel is missing required SDK files")
    forbidden = ("marketsieve_cli/", "/tests/", "/schemas/", ".marketsieve/", "__pycache__")
    violations = [name for name in names if any(fragment in name for fragment in forbidden)]
    if violations:
        raise RuntimeError(f"wheel contains private or generated files: {violations}")
    return names


def verify_cli_wheel(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = sorted(archive.namelist())
    if not any(name.endswith("marketsieve_cli/__init__.py") for name in names):
        raise RuntimeError("CLI wheel is missing its public module")
    if any(name.startswith("marketsieve/") for name in names):
        raise RuntimeError("CLI wheel must depend on, not contain, the SDK")
    return names


def verify_module_wheel(wheel: Path, module: str, *, forbidden: tuple[str, ...]) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = sorted(archive.namelist())
    if not any(name.endswith(f"{module}/__init__.py") for name in names):
        raise RuntimeError(f"wheel is missing its public module: {module}")
    violations = [name for name in names if any(fragment in name for fragment in forbidden)]
    if violations:
        raise RuntimeError(f"wheel crosses a distribution boundary: {violations}")
    return names


def verify_sdist(sdist: Path, *, forbidden_package: str) -> list[str]:
    with tarfile.open(sdist) as archive:
        names = sorted(archive.getnames())
    forbidden = (forbidden_package, "/tests/", "/schemas/", ".marketsieve", "__pycache__")
    violations = [name for name in names if any(fragment in name for fragment in forbidden)]
    if violations:
        raise RuntimeError(f"sdist contains private or generated files: {violations}")
    return names


def python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def verify_isolated_target(
    root: Path,
    *,
    target: Path,
    dist: Path,
    import_statement: str,
) -> None:
    venv = root / target.stem
    run((sys.executable, "-m", "venv", str(venv)))
    isolated = python_in_venv(venv)
    run(
        (
            str(isolated),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--find-links",
            str(RUNTIME_WHEELHOUSE),
            "--find-links",
            str(dist),
            str(target),
        )
    )
    run((str(isolated), "-c", import_statement))


def check_package(path: Path) -> None:
    dist = (path / "dist").resolve()
    dist.mkdir()
    for package_name in (
        "marketsieve",
        "marketsieve-extension-api",
        "marketsieve-cli",
        "marketsieve-source-csv",
        "marketsieve-source-jquants",
    ):
        run(("uv", "build", "--package", package_name, "--out-dir", str(dist)))
    wheels = tuple(dist.glob("*.whl"))
    sdists = tuple(dist.glob("*.tar.gz"))
    if len(wheels) != 5 or len(sdists) != 5:
        raise RuntimeError("the public build must produce five wheels and five sdists")
    run(("uv", "run", "twine", "check", *(str(path) for path in (*wheels, *sdists))))
    core_wheel = next(item for item in wheels if item.name.startswith("marketsieve-"))
    cli_wheel = next(item for item in wheels if item.name.startswith("marketsieve_cli-"))
    extension_wheel = next(
        item for item in wheels if item.name.startswith("marketsieve_extension_api-")
    )
    csv_wheel = next(item for item in wheels if item.name.startswith("marketsieve_source_csv-"))
    jquants_wheel = next(
        item for item in wheels if item.name.startswith("marketsieve_source_jquants-")
    )
    core_sdist = next(item for item in sdists if item.name.startswith("marketsieve-"))
    cli_sdist = next(item for item in sdists if item.name.startswith("marketsieve_cli-"))
    extension_sdist = next(
        item for item in sdists if item.name.startswith("marketsieve_extension_api-")
    )
    csv_sdist = next(item for item in sdists if item.name.startswith("marketsieve_source_csv-"))
    jquants_sdist = next(
        item for item in sdists if item.name.startswith("marketsieve_source_jquants-")
    )
    wheel_files = {
        "marketsieve": verify_core_wheel(core_wheel),
        "marketsieve-cli": verify_cli_wheel(cli_wheel),
        "marketsieve-extension-api": verify_module_wheel(
            extension_wheel,
            "marketsieve_extension_api",
            forbidden=("marketsieve_cli/", "marketsieve_source_csv/", "marketsieve/"),
        ),
        "marketsieve-source-csv": verify_module_wheel(
            csv_wheel,
            "marketsieve_source_csv",
            forbidden=("marketsieve_cli/", "marketsieve_extension_api/", "marketsieve/"),
        ),
        "marketsieve-source-jquants": verify_module_wheel(
            jquants_wheel,
            "marketsieve_source_jquants",
            forbidden=("marketsieve_cli/", "marketsieve_extension_api/", "marketsieve/"),
        ),
    }
    sdist_files = {
        "marketsieve": verify_sdist(core_sdist, forbidden_package="marketsieve_cli"),
        "marketsieve-cli": verify_sdist(cli_sdist, forbidden_package="packages/core"),
        "marketsieve-extension-api": verify_sdist(
            extension_sdist, forbidden_package="marketsieve_source_csv"
        ),
        "marketsieve-source-csv": verify_sdist(csv_sdist, forbidden_package="packages/cli"),
        "marketsieve-source-jquants": verify_sdist(jquants_sdist, forbidden_package="packages/cli"),
    }

    with tempfile.TemporaryDirectory(prefix="marketsieve-install-") as temp_dir:
        temporary_root = Path(temp_dir)
        isolated_targets = (
            (core_wheel, "import marketsieve"),
            (extension_wheel, "import marketsieve_extension_api"),
            (cli_wheel, "import marketsieve_cli"),
            (csv_wheel, "import marketsieve_source_csv"),
            (jquants_wheel, "import marketsieve_source_jquants"),
        )
        for target, statement in isolated_targets:
            verify_isolated_target(
                temporary_root,
                target=target,
                dist=dist,
                import_statement=statement,
            )
        venv = temporary_root / "integrated"
        run((sys.executable, "-m", "venv", str(venv)))
        isolated = python_in_venv(venv)
        run(
            (
                str(isolated),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--find-links",
                str(RUNTIME_WHEELHOUSE),
                str(core_wheel),
                str(extension_wheel),
                str(cli_wheel),
                str(csv_wheel),
                str(jquants_wheel),
            )
        )
        installed = capture(
            (
                str(isolated),
                "-c",
                "import marketsieve; import marketsieve_cli; import marketsieve_extension_api; "
                "import marketsieve_source_csv; import marketsieve_source_jquants; "
                "import marketsieve.analysis.sma20; "
                "import marketsieve.analysis.replay; import marketsieve.data.daily; "
                "import marketsieve.domain; import marketsieve.reporting.sma20; "
                "import marketsieve.synthetic.daily; print(marketsieve.__version__)",
            )
        ).stdout.strip()
        run((str(isolated), "-m", "marketsieve_cli", "doctor", "--output", "json"))

    package = {
        "version": installed,
        "artifacts": [
            {"name": item.name, "sha256": sha256(item), "size": item.stat().st_size}
            for item in (*wheels, *sdists)
        ],
        "wheel_files": wheel_files,
        "sdist_files": sdist_files,
    }
    (path / "package.json").write_text(
        json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def check_secrets(path: Path) -> None:
    command = ["uv", "run", "python", "scripts/secret_gate.py"]
    base_sha = os.environ.get("BASE_SHA")
    if base_sha:
        command.extend(("--base", base_sha))
    command.extend(("--path", str(path)))
    run(tuple(command))


def check_all() -> None:
    path = evidence_dir()
    reset_evidence(path)
    check_secrets(path)
    check_quality()
    check_tests(path)
    validate_schemas()
    check_smoke(path)
    check_package(path)
    check_secrets(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("scope", choices=("quality", "structure", "tests", "package", "all"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = evidence_dir()
    if args.scope in {"tests", "package"}:
        path.mkdir(parents=True, exist_ok=True)
    checks = {
        "quality": check_quality,
        "structure": check_structure,
        "tests": lambda: check_tests(path),
        "package": lambda: check_package(path),
        "all": check_all,
    }
    checks[args.scope]()


if __name__ == "__main__":
    main()
