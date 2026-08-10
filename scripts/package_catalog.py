"""Load and validate the authoritative public-package catalog."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from scripts.parallel import Task, run_tasks

ROOT = Path(__file__).parents[1]
VALID_ROLES = {"sdk", "extension-api", "cli", "adapter"}


@dataclass(frozen=True, slots=True)
class PackageSpec:
    """One independently built public distribution."""

    distribution: str
    path: Path
    module: str
    role: str

    @property
    def pyproject(self) -> Path:
        return self.path / "pyproject.toml"

    @property
    def artifact_stem(self) -> str:
        return re.sub(r"[-_.]+", "_", self.distribution).lower()

    @property
    def project_version(self) -> str:
        project = tomllib.loads(self.pyproject.read_text(encoding="utf-8"))["project"]
        return str(project["version"])

    @property
    def project_dependencies(self) -> tuple[str, ...]:
        project = tomllib.loads(self.pyproject.read_text(encoding="utf-8"))["project"]
        dependencies = project.get("dependencies", ())
        optional = project.get("optional-dependencies", {})
        return tuple(dependencies) + tuple(
            dependency for group in optional.values() for dependency in group
        )

    def wheel(self, dist_dir: Path) -> Path:
        return _one_artifact(dist_dir, f"{self.artifact_stem}-*.whl")

    def sdist(self, dist_dir: Path) -> Path:
        return _one_artifact(dist_dir, f"{self.artifact_stem}-*.tar.gz")


def _one_artifact(dist_dir: Path, pattern: str) -> Path:
    matches = tuple(dist_dir.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one artifact matching {pattern}, found {len(matches)}")
    return matches[0]


def suite_requirement(name: str, version: str) -> str:
    """Return the exact requirement for one co-released MarketSieve distribution."""

    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:rc[1-9][0-9]*)?", version) is None:
        raise RuntimeError(f"public package version must use X.Y.Z or X.Y.ZrcN: {version}")
    return f"{name}=={version}"


def load_package_catalog(root: Path = ROOT) -> tuple[PackageSpec, ...]:
    """Return the validated catalog declared in the workspace pyproject."""

    workspace = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    raw_items: Any = workspace.get("tool", {}).get("marketsieve", {}).get("public-packages")
    if not isinstance(raw_items, list) or not raw_items:
        raise RuntimeError("pyproject.toml must declare tool.marketsieve.public-packages")
    specs: list[PackageSpec] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise RuntimeError("public package entries must be tables")
        fields = {name: raw.get(name) for name in ("distribution", "path", "module", "role")}
        if not all(isinstance(value, str) and value for value in fields.values()):
            raise RuntimeError(
                "public package entries require distribution, path, module, and role"
            )
        role = str(fields["role"])
        if role not in VALID_ROLES:
            raise RuntimeError(f"unsupported public package role: {role}")
        relative_path = Path(str(fields["path"]))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError("public package paths must stay inside the workspace")
        spec = PackageSpec(
            distribution=str(fields["distribution"]),
            path=root / relative_path,
            module=str(fields["module"]),
            role=role,
        )
        if not spec.pyproject.is_file():
            raise RuntimeError(f"public package project is missing: {relative_path}")
        project = tomllib.loads(spec.pyproject.read_text(encoding="utf-8"))["project"]
        if project["name"] != spec.distribution:
            raise RuntimeError(f"catalog name does not match {relative_path}/pyproject.toml")
        if not (spec.path / "src" / spec.module / "__init__.py").is_file():
            raise RuntimeError(f"catalog module is missing: {spec.module}")
        specs.append(spec)
    for attribute in ("distribution", "path", "module"):
        catalog_values = [getattr(spec, attribute) for spec in specs]
        if len(catalog_values) != len(set(catalog_values)):
            raise RuntimeError(f"public package {attribute} values must be unique")
    for required_role in ("sdk", "extension-api", "cli"):
        if sum(spec.role == required_role for spec in specs) != 1:
            raise RuntimeError(f"public package catalog requires exactly one {required_role}")
    distributions = {spec.distribution: spec for spec in specs}
    for spec in specs:
        for requirement in spec.project_dependencies:
            name = re.split(r"[<>=!~ ;\[]", requirement, maxsplit=1)[0]
            dependency = distributions.get(name)
            if dependency is None:
                continue
            expected = suite_requirement(name, spec.project_version)
            if requirement != expected:
                raise RuntimeError(f"{spec.distribution} must depend on {name} through {expected}")
    return tuple(specs)


def build_all(dist_dir: Path, *, jobs: int = 0) -> None:
    """Build every catalog distribution into one directory."""

    dist_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_package_catalog()
    with tempfile.TemporaryDirectory(prefix="marketsieve-build-") as temporary:
        temporary_root = Path(temporary)
        outputs = {spec.distribution: temporary_root / spec.artifact_stem for spec in catalog}
        for output in outputs.values():
            output.mkdir()
        run_tasks(
            [
                Task(
                    f"build:{spec.distribution}",
                    partial(
                        subprocess.run,
                        (
                            "uv",
                            "build",
                            "--package",
                            spec.distribution,
                            "--out-dir",
                            str(outputs[spec.distribution]),
                        ),
                        cwd=ROOT,
                        check=True,
                    ),
                )
                for spec in catalog
            ],
            jobs=jobs,
        )
        for spec in catalog:
            for artifact in sorted(outputs[spec.distribution].iterdir()):
                shutil.copy2(artifact, dist_dir / artifact.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--out-dir", type=Path, required=True)
    build_parser.add_argument("--jobs", type=int, default=0)
    subparsers.add_parser("list")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build":
        build_all(args.out_dir, jobs=args.jobs)
        return
    for spec in load_package_catalog():
        print(spec.distribution)


if __name__ == "__main__":
    main()
