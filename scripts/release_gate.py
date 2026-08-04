"""Build once and verify one release candidate across supported Python versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNTIME_WHEELHOUSE = ROOT / ".marketsieve" / "cache" / "runtime-wheelhouse"
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
CHANGELOG_HEADING = re.compile(r"^## \[([^]]+)] - (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
PACKAGE_PROJECTS = (
    ROOT / "packages" / "core" / "pyproject.toml",
    ROOT / "packages" / "extension-api" / "pyproject.toml",
    ROOT / "packages" / "cli" / "pyproject.toml",
    ROOT / "packages" / "source-csv" / "pyproject.toml",
    ROOT / "packages" / "source-jquants" / "pyproject.toml",
    ROOT / "packages" / "source-alphavantage" / "pyproject.toml",
)
PUBLIC_PACKAGES = (
    "marketsieve",
    "marketsieve-extension-api",
    "marketsieve-cli",
    "marketsieve-source-csv",
    "marketsieve-source-jquants",
    "marketsieve-source-alphavantage",
)


def run(command: Sequence[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def capture(command: Sequence[str], *, cwd: Path = ROOT) -> str:
    return subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def validate_inputs(version: str, commit: str) -> None:
    if VERSION.fullmatch(version) is None:
        raise ValueError("release version must use stable X.Y.Z form")
    if COMMIT.fullmatch(commit) is None:
        raise ValueError("commit must be a complete lowercase Git SHA")


def validate_source_release(version: str) -> None:
    versions = {
        path.parent.name: tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
        for path in PACKAGE_PROJECTS
    }
    if set(versions.values()) != {version}:
        raise RuntimeError(f"workspace package versions do not match {version}: {versions}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = {match.group(1) for match in CHANGELOG_HEADING.finditer(changelog)}
    if version not in released:
        raise RuntimeError(f"CHANGELOG does not contain a dated {version} release")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distributions(dist_dir: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    wheels = tuple(sorted(dist_dir.glob("marketsieve*.whl")))
    sdists = tuple(sorted(dist_dir.glob("marketsieve*.tar.gz")))
    if len(wheels) != 6 or len(sdists) != 6:
        raise RuntimeError("release directory must contain six project wheels and six sdists")
    return wheels, sdists


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


def verify_contents(wheels: tuple[Path, ...], sdists: tuple[Path, ...]) -> None:
    violations: list[str] = []
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
        forbidden = ["/tests/", "/schemas/", ".marketsieve", "__pycache__"]
        if wheel.name.startswith("marketsieve-"):
            forbidden.extend(
                (
                    "marketsieve_cli/",
                    "marketsieve_extension_api/",
                    "marketsieve_source_csv/",
                    "marketsieve_source_jquants/",
                    "marketsieve_source_alphavantage/",
                )
            )
        violations.extend(name for name in names if any(item in name for item in forbidden))
    for sdist in sdists:
        with tarfile.open(sdist) as archive:
            names = archive.getnames()
        sdist_forbidden = ("/tests/", "/schemas/", ".marketsieve", "__pycache__")
        violations.extend(name for name in names if any(item in name for item in sdist_forbidden))
    if violations:
        raise RuntimeError(f"release contains private or generated files: {violations}")


def verify_secrets(paths: Sequence[Path]) -> None:
    command = [sys.executable, str(ROOT / "scripts" / "secret_gate.py")]
    for path in paths:
        command.extend(("--path", str(path)))
    run(tuple(command))


def prepare_dist_dir(dist_dir: Path) -> None:
    if dist_dir.exists():
        entries = tuple(dist_dir.iterdir())
        retry_markers = tuple(
            path
            for path in entries
            if path.name == ".gitignore" and path.read_text(encoding="utf-8") == "*"
        )
        if len(retry_markers) != len(entries):
            raise RuntimeError("release directory must be empty")
        for marker in retry_markers:
            marker.unlink()
    dist_dir.mkdir(parents=True, exist_ok=True)


def build(version: str, commit: str, dist_dir: Path) -> None:
    validate_inputs(version, commit)
    validate_source_release(version)
    if capture(("git", "rev-parse", "HEAD")) != commit:
        raise RuntimeError("commit does not match the checked-out HEAD")
    prepare_dist_dir(dist_dir)
    for package in PUBLIC_PACKAGES:
        run(("uv", "build", "--package", package, "--out-dir", str(dist_dir)))
    runtime_wheels = tuple(sorted(RUNTIME_WHEELHOUSE.glob("*.whl")))
    if not runtime_wheels:
        raise RuntimeError("locked runtime wheelhouse is empty; run make sync")
    for runtime_wheel in runtime_wheels:
        shutil.copy2(runtime_wheel, dist_dir / runtime_wheel.name)
    wheels, sdists = distributions(dist_dir)
    run(("uv", "run", "twine", "check", *(str(path) for path in (*wheels, *sdists))))
    if any(metadata_version(wheel) != version for wheel in wheels):
        raise RuntimeError("built wheel versions do not match the requested version")
    verify_contents(wheels, sdists)
    manifest = {
        "version": version,
        "commit": commit,
        "artifacts": [
            {"name": path.name, "sha256": sha256(path), "size": path.stat().st_size}
            for path in sorted(dist_dir.iterdir())
            if path.is_file()
        ],
    }
    (dist_dir / "release.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verify_secrets((*wheels, *sdists, dist_dir / "release.json"))


def python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def verify(version: str, commit: str, dist_dir: Path) -> None:
    validate_inputs(version, commit)
    validate_source_release(version)
    wheels, sdists = distributions(dist_dir)
    manifest = json.loads((dist_dir / "release.json").read_text(encoding="utf-8"))
    if manifest["version"] != version or manifest["commit"] != commit:
        raise RuntimeError("release manifest provenance does not match the request")
    expected = {item["name"]: item["sha256"] for item in manifest["artifacts"]}
    actual = {
        path.name: path
        for path in dist_dir.iterdir()
        if path.is_file() and path.name != "release.json"
    }
    if set(actual) != set(expected):
        raise RuntimeError("release manifest does not cover exactly the release artifacts")
    for path in actual.values():
        if expected.get(path.name) != sha256(path):
            raise RuntimeError(f"release checksum mismatch: {path.name}")
    if any(metadata_version(wheel) != version for wheel in wheels):
        raise RuntimeError("wheel metadata versions do not match the request")
    verify_contents(wheels, sdists)
    verify_secrets((*wheels, *sdists, dist_dir / "release.json"))
    with tempfile.TemporaryDirectory(prefix="marketsieve-release-") as temp_dir:
        venv = Path(temp_dir) / "venv"
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
                str(dist_dir),
                *(str(wheel) for wheel in wheels),
            )
        )
        installed = capture(
            (
                str(isolated),
                "-c",
                "import marketsieve; import marketsieve_cli; import marketsieve_extension_api; "
                "import marketsieve_source_csv; import marketsieve_source_jquants; "
                "import marketsieve_source_alphavantage; "
                "import marketsieve.analysis.indicators; "
                "import marketsieve.data.daily; import marketsieve.domain; "
                "import marketsieve.synthetic.daily; print(marketsieve.__version__)",
            )
        )
        run((str(isolated), "-m", "marketsieve_cli", "doctor", "--output", "json"))
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
