"""Build once and verify one release candidate across supported Python versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).parents[1]
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:\.dev[0-9]+)?$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def run(command: Sequence[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def capture(command: Sequence[str], *, cwd: Path = ROOT) -> str:
    return subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def validate_inputs(version: str, commit: str) -> None:
    if VERSION.fullmatch(version) is None:
        raise ValueError("version must use PEP 440 X.Y.Z or X.Y.Z.devN form")
    if COMMIT.fullmatch(commit) is None:
        raise ValueError("commit must be a complete lowercase Git SHA")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distributions(dist_dir: Path) -> tuple[Path, Path]:
    wheels = tuple(dist_dir.glob("*.whl"))
    sdists = tuple(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError("release directory must contain one wheel and one sdist")
    return wheels[0], sdists[0]


def metadata_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
    return next(
        line.removeprefix("Version: ")
        for line in metadata.splitlines()
        if line.startswith("Version: ")
    )


def verify_contents(wheel: Path, sdist: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    with tarfile.open(sdist) as archive:
        sdist_names = archive.getnames()
    forbidden = ("marketsieve_app", "/tests/", "/schemas/", ".marketsieve", "__pycache__")
    violations = [
        name
        for name in (*wheel_names, *sdist_names)
        if any(fragment in name for fragment in forbidden)
    ]
    if violations:
        raise RuntimeError(f"release contains private or generated files: {violations}")


def build(version: str, commit: str, dist_dir: Path) -> None:
    validate_inputs(version, commit)
    if capture(("git", "rev-parse", "HEAD")) != commit:
        raise RuntimeError("commit does not match the checked-out HEAD")
    if dist_dir.exists() and any(dist_dir.iterdir()):
        raise RuntimeError("release directory must be empty")
    dist_dir.mkdir(parents=True, exist_ok=True)
    run(("uv", "build", "--package", "marketsieve", "--out-dir", str(dist_dir)))
    wheel, sdist = distributions(dist_dir)
    run(("uv", "run", "twine", "check", str(wheel), str(sdist)))
    if metadata_version(wheel) != version:
        raise RuntimeError("built wheel version does not match the requested version")
    verify_contents(wheel, sdist)
    manifest = {
        "version": version,
        "commit": commit,
        "artifacts": [
            {"name": path.name, "sha256": sha256(path), "size": path.stat().st_size}
            for path in (wheel, sdist)
        ],
    }
    (dist_dir / "release.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def verify(version: str, commit: str, dist_dir: Path) -> None:
    validate_inputs(version, commit)
    wheel, sdist = distributions(dist_dir)
    manifest = json.loads((dist_dir / "release.json").read_text(encoding="utf-8"))
    if manifest["version"] != version or manifest["commit"] != commit:
        raise RuntimeError("release manifest provenance does not match the request")
    expected = {item["name"]: item["sha256"] for item in manifest["artifacts"]}
    for path in (wheel, sdist):
        if expected.get(path.name) != sha256(path):
            raise RuntimeError(f"release checksum mismatch: {path.name}")
    if metadata_version(wheel) != version:
        raise RuntimeError("wheel metadata version does not match the request")
    verify_contents(wheel, sdist)
    with tempfile.TemporaryDirectory(prefix="marketsieve-release-") as temp_dir:
        venv = Path(temp_dir) / "venv"
        run((sys.executable, "-m", "venv", str(venv)))
        isolated = python_in_venv(venv)
        run((str(isolated), "-m", "pip", "install", "--no-deps", str(wheel)))
        installed = capture(
            (
                str(isolated),
                "-c",
                "import marketsieve; import marketsieve.analysis.sma20; "
                "import marketsieve.data.daily; import marketsieve.domain; "
                "import marketsieve.synthetic.daily; print(marketsieve.__version__)",
            )
        )
    if installed != version:
        raise RuntimeError("isolated installation version does not match the request")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("--version", required=True)
        child.add_argument("--commit", required=True)
        child.add_argument("--dist-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build":
        build(args.version, args.commit, args.dist_dir)
    else:
        verify(args.version, args.commit, args.dist_dir)


if __name__ == "__main__":
    main()
