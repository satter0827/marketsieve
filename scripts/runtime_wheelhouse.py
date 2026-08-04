"""Prepare locked third-party runtime wheels for offline artifact verification."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]


def run(command: tuple[str, ...], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def capture(command: tuple[str, ...]) -> str:
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True).stdout


def python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


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
            "--no-hashes",
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
        run(
            (
                str(python_in_venv(venv)),
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--only-binary=:all:",
                "--dest",
                str(resolved),
                "--requirement",
                str(requirement_file),
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare",))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.output)


if __name__ == "__main__":
    main()
