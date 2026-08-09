from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import scripts.package_catalog as package_catalog
from scripts.package_catalog import PackageSpec, build_all, compatible_range, load_package_catalog


def test_workspace_catalog_has_unique_buildable_public_packages() -> None:
    catalog = load_package_catalog()

    assert {spec.role for spec in catalog} >= {
        "sdk",
        "extension-api",
        "cli",
        "adapter",
    }
    assert len({spec.distribution for spec in catalog}) == len(catalog)
    assert all(spec.pyproject.is_file() for spec in catalog)
    assert all(spec.project_version == "1.0.0rc2" for spec in catalog)


def test_workspace_dependencies_allow_external_minor_compatible_plugins() -> None:
    catalog = load_package_catalog()
    public_names = {spec.distribution for spec in catalog}

    for spec in catalog:
        expected_range = compatible_range(spec.project_version)
        for requirement in spec.project_dependencies:
            if any(requirement.startswith(name) for name in public_names):
                assert requirement.endswith(expected_range)


def test_release_candidate_dependencies_accept_the_same_candidate_line() -> None:
    assert compatible_range("1.0.0rc2") == ">=1.0.0rc2,<1.1"


def test_publish_workflow_reuses_one_verified_main_artifact() -> None:
    workflow = (package_catalog.ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pypa/gh-action-pypi-publish" not in workflow
    assert "id-token: write" not in workflow
    assert "run-id: ${{ inputs.ci_run_id }}" in workflow
    assert "python3 -m scripts.release_gate verify" in workflow
    assert "gh release create" in workflow and "--draft" in workflow
    assert 'gh release edit "$TAG" --draft=false' in workflow
    assert "uv build" not in workflow


def test_package_spec_resolves_normalized_artifact_names(tmp_path: Path) -> None:
    package = tmp_path / "package"
    spec = PackageSpec("Example.Source", package, "example_source", "adapter")
    wheel = tmp_path / "example_source-1.2.3-py3-none-any.whl"
    sdist = tmp_path / "example_source-1.2.3.tar.gz"
    wheel.touch()
    sdist.touch()

    assert spec.artifact_stem == "example_source"
    assert spec.wheel(tmp_path) == wheel
    assert spec.sdist(tmp_path) == sdist


def test_package_spec_rejects_ambiguous_artifacts(tmp_path: Path) -> None:
    spec = PackageSpec("example", tmp_path, "example", "adapter")

    with pytest.raises(RuntimeError, match="expected one artifact"):
        spec.wheel(tmp_path)


def test_build_all_uses_each_catalog_distribution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalog = (
        PackageSpec("example-one", tmp_path / "one", "example_one", "sdk"),
        PackageSpec("example-two", tmp_path / "two", "example_two", "cli"),
    )
    commands: list[tuple[tuple[str, ...], Path, bool]] = []

    def record(command: tuple[str, ...], *, cwd: Path, check: bool) -> None:
        commands.append((command, cwd, check))

    monkeypatch.setattr(package_catalog, "load_package_catalog", lambda: catalog)
    monkeypatch.setattr(subprocess, "run", record)

    output = tmp_path / "dist"
    build_all(output)

    assert output.is_dir()
    assert [command[0][3] for command in commands] == ["example-one", "example-two"]
    assert all(command[1:] == (package_catalog.ROOT, True) for command in commands)
