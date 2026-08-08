"""Prepare locked third-party runtime wheels for offline artifact verification."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path

from scripts.parallel import Task, run_tasks

ROOT = Path(__file__).parents[1]
SUPPORTED_PYTHON_VERSIONS = ("3.12", "3.13", "3.14")


def run(command: tuple[str, ...], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def capture(command: tuple[str, ...]) -> str:
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True).stdout


def python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def download_command(
    python: Path, requirement_file: Path, output: Path, target_version: str
) -> tuple[str, ...]:
    return (
        str(python),
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--require-hashes",
        "--python-version",
        target_version,
        "--dest",
        str(output),
        "--requirement",
        str(requirement_file),
    )


def prepare(output: Path) -> None:
    resolved = output.resolve()
    state = (ROOT / ".marketsieve").resolve()
    if state not in resolved.parents:
        raise RuntimeError("runtime wheelhouse must be inside .marketsieve")
    shutil.rmtree(resolved, ignore_errors=True)
    resolved.mkdir(parents=True)
    requirements = capture(
        (
            "uv",
            "export",
            "--locked",
            "--package",
            "marketsieve-cli",
            "--no-dev",
            "--no-emit-workspace",
            "--no-annotate",
            "--no-header",
        )
    )
    with tempfile.TemporaryDirectory(prefix="marketsieve-wheelhouse-") as temp_dir:
        temporary = Path(temp_dir)
        requirement_file = temporary / "requirements.txt"
        requirement_file.write_text(requirements, encoding="utf-8")
        venv = temporary / "venv"
        run((sys.executable, "-m", "venv", str(venv)))
        python = python_in_venv(venv)
        run_tasks(
            [
                Task(
                    f"download:{target_version}",
                    partial(
                        run,
                        download_command(python, requirement_file, resolved, target_version),
                    ),
                )
                for target_version in SUPPORTED_PYTHON_VERSIONS
            ],
            jobs=2,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare",))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.output)


if __name__ == "__main__":
    main()
