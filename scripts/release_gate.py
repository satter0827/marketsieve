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
import zipfile
from collections.abc import Sequence
from functools import partial
from pathlib import Path

from scripts.package_catalog import load_package_catalog
from scripts.parallel import Task, run_tasks

ROOT = Path(__file__).parents[1]
RUNTIME_WHEELHOUSE = ROOT / ".marketsieve" / "cache" / "runtime-wheelhouse"
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
CHANGELOG_HEADING = re.compile(r"^## \[([^]]+)] - (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
GENERATED_ASSETS = ("constraints.txt", "VERIFY.md", "SHA256SUMS", "release.json")


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
    versions = {spec.distribution: spec.project_version for spec in load_package_catalog()}
    if set(versions.values()) != {version}:
        raise RuntimeError(f"workspace package versions do not match {version}: {versions}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = {match.group(1) for match in CHANGELOG_HEADING.finditer(changelog)}
    if version not in released:
        raise RuntimeError(f"CHANGELOG does not contain a dated {version} release")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distributions(dist_dir: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    expected = len(load_package_catalog())
    wheels = tuple(sorted(dist_dir.glob("marketsieve*.whl")))
    sdists = tuple(sorted(dist_dir.glob("marketsieve*.tar.gz")))
    if len(wheels) != expected or len(sdists) != expected:
        raise RuntimeError("release directory must contain one wheel and sdist per catalog entry")
    return wheels, sdists


def release_assets(dist_dir: Path, *, include_manifest: bool = True) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in dist_dir.iterdir()
            if path.is_file()
            and path.name != ".gitignore"
            and (include_manifest or path.name != "release.json")
        )
    )


def verify_runtime_wheels(dist_dir: Path) -> None:
    expected = {path.name: sha256(path) for path in RUNTIME_WHEELHOUSE.glob("*.whl")}
    actual = {
        path.name: sha256(path)
        for path in dist_dir.glob("*.whl")
        if not path.name.startswith("marketsieve")
    }
    if actual != expected:
        raise RuntimeError("third-party wheels do not match the locked runtime wheelhouse")


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


def wheel_requirement(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
    fields = {
        key: value
        for line in metadata.splitlines()
        if ": " in line
        for key, value in (line.split(": ", maxsplit=1),)
        if key in {"Name", "Version"}
    }
    return f"{fields['Name']}=={fields['Version']}"


def write_wheelhouse_assets(dist_dir: Path, version: str) -> None:
    wheel_paths = tuple(sorted(dist_dir.glob("*.whl")))
    constraints = "\n".join(sorted(wheel_requirement(path) for path in wheel_paths)) + "\n"
    constraints_path = dist_dir / "constraints.txt"
    constraints_path.write_text(constraints, encoding="utf-8")
    instructions_path = dist_dir / "VERIFY.md"
    instructions_path.write_text(
        "# MarketSieve wheelhouse\n\n"
        "Extract this archive, then install without an index:\n\n"
        "```shell\n"
        "python -m pip install --no-index --find-links ./marketsieve-wheelhouse "
        '"marketsieve-cli"\n'
        "```\n\n"
        "Verify downloaded release assets against `release.json` before installation.\n",
        encoding="utf-8",
    )
    archive_path = dist_dir / f"marketsieve-wheelhouse-{version}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (*wheel_paths, constraints_path, instructions_path):
            archive.write(path, f"marketsieve-wheelhouse/{path.name}")
    checksum_paths = tuple(
        sorted(
            path
            for path in release_assets(dist_dir, include_manifest=False)
            if path.name != "SHA256SUMS"
        )
    )
    (dist_dir / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_paths),
        encoding="utf-8",
    )


def verify_wheelhouse_assets(dist_dir: Path, version: str) -> None:
    constraints = dist_dir / "constraints.txt"
    instructions = dist_dir / "VERIFY.md"
    archive_path = dist_dir / f"marketsieve-wheelhouse-{version}.zip"
    checksums = dist_dir / "SHA256SUMS"
    if not all(path.is_file() for path in (constraints, instructions, archive_path, checksums)):
        raise RuntimeError("release wheelhouse assets are incomplete")
    expected_requirements = {wheel_requirement(path) for path in dist_dir.glob("*.whl")}
    if set(constraints.read_text(encoding="utf-8").splitlines()) != expected_requirements:
        raise RuntimeError("release constraints do not match wheel metadata")
    expected_checksums = {
        path.name: sha256(path)
        for path in release_assets(dist_dir, include_manifest=False)
        if path.name != "SHA256SUMS"
    }
    actual_checksums = {
        name: digest
        for line in checksums.read_text(encoding="utf-8").splitlines()
        for digest, name in (line.split("  ", maxsplit=1),)
    }
    if actual_checksums != expected_checksums:
        raise RuntimeError("SHA256SUMS does not cover the release assets")
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    expected_names = {f"marketsieve-wheelhouse/{path.name}" for path in dist_dir.glob("*.whl")} | {
        "marketsieve-wheelhouse/constraints.txt",
        "marketsieve-wheelhouse/VERIFY.md",
    }
    if names != expected_names:
        raise RuntimeError("wheelhouse ZIP contents do not match release wheels")


def verify_contents(dist_dir: Path) -> None:
    catalog = load_package_catalog()
    violations: list[str] = []
    for spec in catalog:
        wheel = spec.wheel(dist_dir)
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
        required = [f"{spec.module}/__init__.py"]
        if spec.role == "sdk":
            required.append(f"{spec.module}/py.typed")
        if any(not any(name.endswith(item) for name in names) for item in required):
            violations.append(f"{wheel.name}: missing public module files")
        forbidden = ["/tests/", "/schemas/", ".marketsieve", "__pycache__"]
        forbidden.extend(
            f"{other.module}/" for other in catalog if other.distribution != spec.distribution
        )
        violations.extend(name for name in names if any(item in name for item in forbidden))
    for spec in catalog:
        sdist = spec.sdist(dist_dir)
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
    catalog = load_package_catalog()
    with tempfile.TemporaryDirectory(prefix="marketsieve-release-build-") as temporary:
        build_root = Path(temporary)
        outputs = {spec.distribution: build_root / spec.artifact_stem for spec in catalog}
        for output in outputs.values():
            output.mkdir()
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
                            str(outputs[spec.distribution]),
                        ),
                    ),
                )
                for spec in catalog
            ],
            jobs=4,
        )
        for spec in catalog:
            for artifact in sorted(outputs[spec.distribution].iterdir()):
                shutil.copy2(artifact, dist_dir / artifact.name)
    runtime_wheels = tuple(sorted(RUNTIME_WHEELHOUSE.glob("*.whl")))
    if not runtime_wheels:
        raise RuntimeError("locked runtime wheelhouse is empty; run make sync")
    for runtime_wheel in runtime_wheels:
        shutil.copy2(runtime_wheel, dist_dir / runtime_wheel.name)
    verify_runtime_wheels(dist_dir)
    wheels, sdists = distributions(dist_dir)
    run(("uv", "run", "twine", "check", *(str(path) for path in (*wheels, *sdists))))
    if any(metadata_version(wheel) != version for wheel in wheels):
        raise RuntimeError("built wheel versions do not match the requested version")
    verify_contents(dist_dir)
    write_wheelhouse_assets(dist_dir, version)
    manifest = {
        "version": version,
        "commit": commit,
        "artifacts": [
            {"name": path.name, "sha256": sha256(path), "size": path.stat().st_size}
            for path in release_assets(dist_dir, include_manifest=False)
        ],
    }
    (dist_dir / "release.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verify_secrets((*wheels, *sdists, *(dist_dir / name for name in GENERATED_ASSETS)))


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
    actual = {path.name: path for path in release_assets(dist_dir, include_manifest=False)}
    if set(actual) != set(expected):
        raise RuntimeError("release manifest does not cover exactly the release artifacts")
    for path in actual.values():
        if expected.get(path.name) != sha256(path):
            raise RuntimeError(f"release checksum mismatch: {path.name}")
    if any(metadata_version(wheel) != version for wheel in wheels):
        raise RuntimeError("wheel metadata versions do not match the request")
    verify_contents(dist_dir)
    verify_wheelhouse_assets(dist_dir, version)
    verify_secrets((*wheels, *sdists, *(dist_dir / name for name in GENERATED_ASSETS)))
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
        catalog = load_package_catalog()
        imports = "; ".join(f"import {spec.module}" for spec in catalog)
        installed = capture(
            (
                str(isolated),
                "-c",
                imports + "; import marketsieve.analysis.indicators; "
                "import marketsieve.data.daily; import marketsieve.domain; "
                "import marketsieve.synthetic.daily; print(marketsieve.__version__)",
            )
        )
        cli_module = next(spec.module for spec in catalog if spec.role == "cli")
        run((str(isolated), "-m", cli_module, "doctor", "--output", "json"))
    if installed != version:
        raise RuntimeError("isolated installation version does not match the request")


def export_pypi(version: str, commit: str, dist_dir: Path, output_dir: Path) -> None:
    """Stage only repository-owned distributions from one verified release artifact."""

    verify(version, commit, dist_dir)
    if output_dir.exists() and tuple(output_dir.iterdir()):
        raise RuntimeError("PyPI staging directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    wheels, sdists = distributions(dist_dir)
    for path in (*wheels, *sdists):
        shutil.copy2(path, output_dir / path.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify", "export-pypi"):
        child = subparsers.add_parser(command)
        child.add_argument("--version", required=True)
        child.add_argument("--commit", required=True)
        child.add_argument("--dist-dir", required=True, type=Path)
        if command == "export-pypi":
            child.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build":
        build(args.version, args.commit, args.dist_dir)
    elif args.command == "verify":
        verify(args.version, args.commit, args.dist_dir)
    else:
        export_pypi(args.version, args.commit, args.dist_dir, args.output_dir)


if __name__ == "__main__":
    main()
