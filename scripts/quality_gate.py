"""Deterministic local and CI quality checks for the MarketSieve foundation."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).parents[1]


def run(command: Sequence[str], *, cwd: Path = ROOT) -> None:
    """Run a command and fail immediately when it is unsuccessful."""

    subprocess.run(command, cwd=cwd, check=True)


def check_quality() -> None:
    run(("uv", "run", "ruff", "format", "--check", "."))
    run(("uv", "run", "ruff", "check", "."))
    run(("uv", "run", "mypy"))
    if (ROOT / ".git").exists():
        run(("git", "diff", "--check"))


def check_tests() -> None:
    run(("uv", "run", "pytest"))
    run(("uv", "run", "marketsieve", "--version"))
    run(("uv", "run", "marketsieve", "doctor"))


def python_in_venv(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def verify_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    required_suffixes = {
        "marketsieve/__init__.py",
        "marketsieve/py.typed",
    }
    for suffix in required_suffixes:
        if not any(name.endswith(suffix) for name in names):
            raise RuntimeError(f"wheel is missing {suffix}")

    if not any(".dist-info/licenses/" in name and name.endswith("LICENSE") for name in names):
        raise RuntimeError("wheel is missing its license file")

    forbidden_fragments = ("marketsieve_app/", "/tests/", "__pycache__", ".pyc")
    violations = sorted(
        name for name in names if any(fragment in name for fragment in forbidden_fragments)
    )
    if violations:
        raise RuntimeError(f"wheel contains private or generated files: {violations}")


def verify_sdist(sdist: Path) -> None:
    with tarfile.open(sdist) as archive:
        names = archive.getnames()

    forbidden_fragments = ("marketsieve_app", "/tests/", "__pycache__", ".pyc")
    violations = sorted(
        name for name in names if any(fragment in name for fragment in forbidden_fragments)
    )
    if violations:
        raise RuntimeError(f"sdist contains private or generated files: {violations}")


def check_package() -> None:
    with tempfile.TemporaryDirectory(prefix="marketsieve-package-") as temp_dir:
        temporary = Path(temp_dir)
        dist = temporary / "dist"
        run(("uv", "build", "--package", "marketsieve", "--out-dir", str(dist)))

        wheels = tuple(dist.glob("*.whl"))
        sdists = tuple(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError("the public build must produce one wheel and one sdist")

        run(("uv", "run", "twine", "check", str(wheels[0]), str(sdists[0])))
        verify_wheel(wheels[0])
        verify_sdist(sdists[0])

        venv = temporary / "venv"
        run((sys.executable, "-m", "venv", str(venv)))
        isolated_python = python_in_venv(venv)
        run((str(isolated_python), "-m", "pip", "install", "--no-deps", str(wheels[0])))
        run(
            (
                str(isolated_python),
                "-c",
                "import marketsieve; print(marketsieve.__version__)",
            )
        )


def check_all() -> None:
    check_quality()
    check_tests()
    check_package()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("scope", choices=("quality", "tests", "package", "all"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    checks = {
        "quality": check_quality,
        "tests": check_tests,
        "package": check_package,
        "all": check_all,
    }
    checks[args.scope]()


if __name__ == "__main__":
    main()
