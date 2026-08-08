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
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

from scripts.package_catalog import PackageSpec, load_package_catalog
from scripts.parallel import Task, TaskGroupError, run_tasks, worker_count

ROOT = Path(__file__).parents[1]
STATE_ROOT = ROOT / ".marketsieve"
RUNTIME_WHEELHOUSE = STATE_ROOT / "cache" / "runtime-wheelhouse"
EXTERNAL_PLUGIN_EXAMPLES: tuple[Path, ...] = ()
MINIMUM_STATEMENT_COVERAGE_PERCENT = 85.0
MINIMUM_BRANCH_COVERAGE_PERCENT = 75.0
MINIMUM_CRITICAL_MODULE_COVERAGE_PERCENT = 80.0
CRITICAL_MODULE_SUFFIXES = (
    "application/market.py",
    "application/research.py",
    "adapters/market_snapshots.py",
    "adapters/research.py",
    "develop_gate.py",
    "release_gate.py",
    "review_gate.py",
    "governance_gate.py",
)


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
    run(("uv", "run", "coverage", "erase"))
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
    run(("uv", "run", "coverage", "report", "--fail-under=0"))
    run(("uv", "run", "coverage", "json", "-o", str(coverage_json)))
    coverage = json.loads(coverage_json.read_text(encoding="utf-8"))
    metrics = coverage_metrics(coverage)
    validate_coverage(metrics)
    configuration = (ROOT / "pyproject.toml").read_bytes()
    (path / "coverage-metadata.json").write_text(
        json.dumps(
            {
                "commit_sha": head_sha(),
                "configuration_hash": hashlib.sha256(configuration).hexdigest(),
                "targets": sorted(coverage["files"]),
                "thresholds": {
                    "statement_percent": MINIMUM_STATEMENT_COVERAGE_PERCENT,
                    "branch_percent": MINIMUM_BRANCH_COVERAGE_PERCENT,
                    "critical_module_percent": MINIMUM_CRITICAL_MODULE_COVERAGE_PERCENT,
                },
                "metrics": metrics,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def coverage_metrics(document: dict[str, object]) -> dict[str, object]:
    """Calculate separate statement, branch, and critical-module coverage."""

    totals = document["totals"]
    files = document["files"]
    if not isinstance(totals, dict) or not isinstance(files, dict):
        raise ValueError("coverage JSON has an invalid shape")

    def percent(covered: int, total: int) -> float:
        return 100.0 if total == 0 else covered / total * 100

    statement = percent(int(totals["covered_lines"]), int(totals["num_statements"]))
    branch = percent(int(totals["covered_branches"]), int(totals["num_branches"]))
    critical: dict[str, float] = {}
    for name, value in files.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ValueError("coverage file entry has an invalid shape")
        if not name.endswith(CRITICAL_MODULE_SUFFIXES):
            continue
        summary = value.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("coverage file summary has an invalid shape")
        critical[name] = percent(
            int(summary["covered_lines"]),
            int(summary["num_statements"]),
        )
    return {"statement_percent": statement, "branch_percent": branch, "critical": critical}


def validate_coverage(metrics: dict[str, object]) -> None:
    """Fail with actionable independent threshold evidence."""

    statement = cast(float, metrics["statement_percent"])
    branch = cast(float, metrics["branch_percent"])
    critical = metrics["critical"]
    if not isinstance(critical, dict):
        raise ValueError("critical coverage metrics have an invalid shape")
    failures = []
    if statement < MINIMUM_STATEMENT_COVERAGE_PERCENT:
        failures.append(
            f"statement coverage {statement:.2f}% < {MINIMUM_STATEMENT_COVERAGE_PERCENT:.2f}%"
        )
    if branch < MINIMUM_BRANCH_COVERAGE_PERCENT:
        failures.append(f"branch coverage {branch:.2f}% < {MINIMUM_BRANCH_COVERAGE_PERCENT:.2f}%")
    failures.extend(
        f"critical module {name} coverage {float(value):.2f}% "
        f"< {MINIMUM_CRITICAL_MODULE_COVERAGE_PERCENT:.2f}%"
        for name, value in sorted(critical.items())
        if float(value) < MINIMUM_CRITICAL_MODULE_COVERAGE_PERCENT
    )
    if failures:
        raise RuntimeError("; ".join(failures))


def validate_schemas() -> None:
    schemas = sorted((ROOT / "schemas").glob("*/v*/schema.json"))
    if not schemas:
        raise RuntimeError("at least one versioned schema is required")
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def check_smoke(path: Path, *, jobs: int = 1) -> None:
    commands = {
        "version": ("uv", "run", "marketsieve", "--version"),
        "doctor": (
            "uv",
            "run",
            "marketsieve",
            "--log-level",
            "INFO",
            "doctor",
            "--output",
            "json",
        ),
        "module": (
            "uv",
            "run",
            "python",
            "-m",
            "marketsieve_cli",
            "doctor",
            "--output",
            "json",
        ),
        "capabilities": ("uv", "run", "marketsieve", "capabilities", "--output", "json"),
        "market_help": ("uv", "run", "marketsieve", "market", "build", "--help"),
        "research_help": ("uv", "run", "marketsieve", "research", "build", "--help"),
    }
    captured: dict[str, subprocess.CompletedProcess[str]] = {}

    def operation(name: str, command: tuple[str, ...]) -> Callable[[], None]:
        def execute() -> None:
            captured[name] = capture(command)

        return execute

    run_tasks(
        [Task(name, operation(name, command)) for name, command in commands.items()],
        jobs=jobs,
    )
    version = captured["version"]
    doctor = captured["doctor"]
    module = captured["module"]
    capabilities = captured["capabilities"]
    market_help = captured["market_help"]
    research_help = captured["research_help"]
    documents = {
        "doctor-result": json.loads(doctor.stdout),
        "capabilities-result": json.loads(capabilities.stdout),
    }
    for name, document in documents.items():
        major = "v8" if name == "capabilities-result" else "v1"
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
        "market_help": {"exit_code": market_help.returncode},
        "research_help": {"exit_code": research_help.returncode},
    }
    (path / "smoke.json").write_text(
        json.dumps(smoke, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    logs = doctor.stderr
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


def verify_catalog_wheel(
    spec: PackageSpec, wheel: Path, catalog: tuple[PackageSpec, ...]
) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = sorted(archive.namelist())
    required = [f"{spec.module}/__init__.py"]
    if spec.role == "sdk":
        required.append(f"{spec.module}/py.typed")
    if any(not any(name.endswith(suffix) for name in names) for suffix in required):
        raise RuntimeError(f"wheel is missing required files for {spec.distribution}")
    forbidden = (
        *(f"{other.module}/" for other in catalog if other.distribution != spec.distribution),
        "/tests/",
        "/schemas/",
        ".marketsieve/",
        "__pycache__",
    )
    violations = [name for name in names if any(fragment in name for fragment in forbidden)]
    if violations:
        raise RuntimeError(f"wheel crosses a distribution boundary: {violations}")
    return names


def verify_catalog_sdist(sdist: Path) -> list[str]:
    with tarfile.open(sdist) as archive:
        names = sorted(archive.getnames())
    forbidden = ("/packages/", "/tests/", "/schemas/", ".marketsieve", "__pycache__")
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


def check_package(path: Path, *, jobs: int = 1) -> None:
    catalog = load_package_catalog()
    dist = (path / "dist").resolve()
    dist.mkdir()
    build_roots = {
        spec.distribution: path / "package-build" / spec.artifact_stem for spec in catalog
    }
    for build_root in build_roots.values():
        build_root.mkdir(parents=True)
    run_tasks(
        [
            Task(
                f"build:{spec.distribution}",
                partial(
                    run,
                    (
                        "uv",
                        "build",
                        "--package",
                        spec.distribution,
                        "--out-dir",
                        str(build_roots[spec.distribution]),
                    ),
                ),
            )
            for spec in catalog
        ],
        jobs=jobs,
    )
    for spec in catalog:
        for artifact in sorted(build_roots[spec.distribution].iterdir()):
            shutil.copy2(artifact, dist / artifact.name)
    wheels = tuple(dist.glob("*.whl"))
    sdists = tuple(dist.glob("*.tar.gz"))
    if len(wheels) != len(catalog) or len(sdists) != len(catalog):
        raise RuntimeError("the public build must produce one wheel and sdist per catalog entry")
    run(("uv", "run", "twine", "check", *(str(path) for path in (*wheels, *sdists))))
    wheel_files = {
        spec.distribution: verify_catalog_wheel(spec, spec.wheel(dist), catalog) for spec in catalog
    }
    sdist_files = {spec.distribution: verify_catalog_sdist(spec.sdist(dist)) for spec in catalog}
    external_dist = (path / "external-plugin").resolve()
    external_dist.mkdir()
    for example in EXTERNAL_PLUGIN_EXAMPLES:
        run(("uv", "build", str(example), "--out-dir", str(external_dist)))
    external_wheels = tuple(sorted(external_dist.glob("*.whl")))
    if len(external_wheels) != len(EXTERNAL_PLUGIN_EXAMPLES):
        raise RuntimeError("each external plugin example must build exactly one wheel")

    with tempfile.TemporaryDirectory(prefix="marketsieve-install-") as temp_dir:
        temporary_root = Path(temp_dir)
        isolated_targets = tuple((spec.wheel(dist), f"import {spec.module}") for spec in catalog)
        run_tasks(
            [
                Task(
                    f"install:{target.name}",
                    partial(
                        verify_isolated_target,
                        temporary_root,
                        target=target,
                        dist=dist,
                        import_statement=statement,
                    ),
                )
                for target, statement in isolated_targets
            ],
            jobs=jobs,
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
                *(str(spec.wheel(dist)) for spec in catalog),
            )
        )
        installed = capture(
            (
                str(isolated),
                "-c",
                "; ".join(f"import {spec.module}" for spec in catalog)
                + "; import marketsieve.analysis.indicators; import marketsieve.data.daily; "
                "import marketsieve.domain; import marketsieve.synthetic.daily; "
                "print(marketsieve.__version__)",
            )
        ).stdout.strip()
        cli_module = next(spec.module for spec in catalog if spec.role == "cli")
        run((str(isolated), "-m", cli_module, "doctor", "--output", "json"))

    package = {
        "version": installed,
        "artifacts": [
            {"name": item.name, "sha256": sha256(item), "size": item.stat().st_size}
            for item in (*wheels, *sdists)
        ],
        "wheel_files": wheel_files,
        "sdist_files": sdist_files,
        "external_plugins": [
            {"name": wheel.name, "sha256": sha256(wheel)} for wheel in external_wheels
        ],
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


def check_quality_and_schemas() -> None:
    """Run static source checks followed by schema validation in one lane."""

    check_quality()
    validate_schemas()


def _write_timings(path: Path, jobs: int, results: list[dict[str, Any]]) -> None:
    configuration = (ROOT / "pyproject.toml").read_bytes()
    (path / "timings.json").write_text(
        json.dumps(
            {
                "commit_sha": head_sha(),
                "configuration_hash": hashlib.sha256(configuration).hexdigest(),
                "requested_jobs": jobs,
                "resolved_jobs": worker_count(jobs),
                "tasks": results,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def check_all(jobs: int) -> None:
    path = evidence_dir()
    reset_evidence(path)
    check_secrets(path)
    tasks = (
        Task("quality", check_quality_and_schemas),
        Task("tests", partial(check_tests, path)),
        Task("package", partial(check_package, path, jobs=1)),
        Task("smoke", partial(check_smoke, path, jobs=1)),
    )
    try:
        timings = run_tasks(tasks, jobs=jobs)
    except TaskGroupError as error:
        _write_timings(path, jobs, error.results)
        raise
    _write_timings(path, jobs, timings)
    check_secrets(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument(
        "scope", choices=("quality", "structure", "tests", "smoke", "package", "all")
    )
    check_parser.add_argument(
        "--jobs",
        type=int,
        default=int(os.environ.get("GATE_JOBS", "0")),
        help="bounded parallel workers; zero selects up to four automatically",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    worker_count(args.jobs)
    path = evidence_dir()
    if args.scope in {"tests", "smoke", "package"}:
        path.mkdir(parents=True, exist_ok=True)
    checks: dict[str, Callable[[], object]] = {
        "quality": check_quality,
        "structure": check_structure,
        "tests": lambda: check_tests(path),
        "smoke": lambda: check_smoke(path, jobs=args.jobs),
        "package": lambda: check_package(path, jobs=args.jobs),
        "all": lambda: check_all(args.jobs),
    }
    checks[args.scope]()


if __name__ == "__main__":
    main()
