from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import develop_gate, governance_gate, release_gate, review_gate, runtime_wheelhouse
from scripts.package_catalog import PackageSpec


def _wheel(path: Path, *, name: str = "example", version: str = "0.15.0") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{name}/__init__.py", "")
        archive.writestr(f"{name}/py.typed", "")
        archive.writestr(
            f"{name}-{version}.dist-info/METADATA",
            f"Name: {name.replace('_', '-')}\nVersion: {version}\n",
        )
    return path


def _sdist(path: Path, *, name: str = "example", version: str = "0.15.0") -> Path:
    source = path.parent / "README.md"
    source.write_text("example\n", encoding="utf-8")
    with tarfile.open(path, "w:gz") as archive:
        archive.add(source, arcname=f"{name}-{version}/README.md")
    return path


def _spec(root: Path) -> PackageSpec:
    root.mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "marketsieve-example"\nversion = "0.15.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    return PackageSpec("marketsieve-example", root, "example", "cli")


def test_develop_gate_process_boundaries_and_evidence_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[tuple[str, ...], Path, bool]] = []

    def fake_run(command: Any, *, cwd: Path, check: bool, **kwargs: Any) -> Any:
        calls.append((tuple(command), cwd, check))
        return subprocess.CompletedProcess(command, 0, stdout="sha\n", stderr="")

    monkeypatch.setattr("scripts.develop_gate.subprocess.run", fake_run)
    develop_gate.run(("tool", "check"), cwd=tmp_path)
    result = develop_gate.capture(("tool", "show"), cwd=tmp_path)
    assert result.stdout == "sha\n"
    assert calls == [(("tool", "check"), tmp_path, True), (("tool", "show"), tmp_path, True)]

    state = tmp_path / ".marketsieve"
    monkeypatch.setattr(develop_gate, "STATE_ROOT", state)
    monkeypatch.setenv("EVIDENCE_DIR", str(state / "artifacts" / "custom"))
    target = develop_gate.evidence_dir()
    develop_gate.reset_evidence(target)
    assert target.is_dir()
    with pytest.raises(RuntimeError, match="inside"):
        develop_gate.reset_evidence(tmp_path / "outside")


def test_develop_gate_quality_structure_and_schema_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(develop_gate, "ROOT", tmp_path)
    monkeypatch.setattr(develop_gate, "STATE_ROOT", tmp_path / ".marketsieve")
    monkeypatch.setattr(develop_gate, "run", lambda command, **_: calls.append(tuple(command)))
    develop_gate.check_quality()
    develop_gate.check_structure()
    assert calls[0][:4] == ("uv", "run", "ruff", "format")
    assert calls[-1] == ("uv", "run", "pytest", "tests/structure")

    schema_dir = tmp_path / "schemas" / "example" / "v1"
    schema_dir.mkdir(parents=True)
    (schema_dir / "schema.json").write_text(
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}),
        encoding="utf-8",
    )
    develop_gate.validate_schemas()
    (schema_dir / "schema.json").unlink()
    with pytest.raises(RuntimeError, match="at least one"):
        develop_gate.validate_schemas()


def test_develop_gate_coverage_shape_zero_and_failures() -> None:
    document: dict[str, object] = {
        "totals": {
            "covered_lines": 0,
            "num_statements": 0,
            "covered_branches": 0,
            "num_branches": 0,
        },
        "files": {
            "x/application/market.py": {"summary": {"covered_lines": 8, "num_statements": 10}}
        },
    }
    metrics = develop_gate.coverage_metrics(document)
    assert metrics["statement_percent"] == 100.0
    assert metrics["branch_percent"] == 100.0
    develop_gate.validate_coverage(metrics)
    with pytest.raises(ValueError, match="invalid shape"):
        develop_gate.coverage_metrics({"totals": [], "files": {}})
    with pytest.raises(ValueError, match="entry"):
        develop_gate.coverage_metrics({"totals": document["totals"], "files": {1: {}}})
    with pytest.raises(ValueError, match="summary"):
        develop_gate.coverage_metrics(
            {"totals": document["totals"], "files": {"x/develop_gate.py": {}}}
        )
    with pytest.raises(ValueError, match="critical"):
        develop_gate.validate_coverage(
            {"statement_percent": 100.0, "branch_percent": 100.0, "critical": []}
        )


def test_develop_gate_archive_checks_and_hash(tmp_path: Path) -> None:
    spec = _spec(tmp_path / "package")
    wheel = _wheel(tmp_path / "example-0.15.0-py3-none-any.whl")
    sdist = _sdist(tmp_path / "example-0.15.0.tar.gz")
    assert develop_gate.verify_catalog_wheel(spec, wheel, (spec,))
    assert develop_gate.verify_catalog_sdist(sdist)
    assert develop_gate.sha256(wheel) == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert develop_gate.python_in_venv(tmp_path).name in {"python", "python.exe"}

    bad = tmp_path / "bad.whl"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("other/__init__.py", "")
    with pytest.raises(RuntimeError, match="missing required"):
        develop_gate.verify_catalog_wheel(spec, bad, (spec,))


def test_runtime_wheelhouse_prepare_is_scoped_and_runs_all_versions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = tmp_path / ".marketsieve"
    output = state / "cache" / "wheels"
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(runtime_wheelhouse, "ROOT", tmp_path)
    monkeypatch.setattr(runtime_wheelhouse, "capture", lambda _: "locked==1 --hash=sha256:abc\n")
    monkeypatch.setattr(runtime_wheelhouse, "run", lambda command, **_: commands.append(command))
    runtime_wheelhouse.prepare(output)
    assert output.is_dir()
    assert len([command for command in commands if "download" in command]) == len(
        runtime_wheelhouse.SUPPORTED_PYTHON_VERSIONS
    )
    with pytest.raises(RuntimeError, match="inside"):
        runtime_wheelhouse.prepare(tmp_path / "outside")


def test_governance_reads_compares_and_reports_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rules = tmp_path / "rules"
    rules.mkdir()
    policy = {
        "name": "develop",
        "target": "branch",
        "enforcement": "active",
        "conditions": {},
        "rules": [],
        "bypass_actors": [],
    }
    (rules / "develop.json").write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(governance_gate, "RULESETS", rules)
    assert governance_gate.checked_in_rulesets() == {"develop": policy}

    responses = iter([json.dumps([{"id": 1}]), json.dumps({"id": 1, **policy})])
    monkeypatch.setattr(governance_gate, "capture", lambda *args: next(responses))
    assert governance_gate.active_rulesets("owner/repo") == {"develop": policy}

    monkeypatch.setattr(governance_gate, "repository_name", lambda _: "owner/repo")
    monkeypatch.setattr(governance_gate, "capture", lambda *args: "origin")
    monkeypatch.setattr(governance_gate, "checked_in_rulesets", lambda: {"develop": policy})
    monkeypatch.setattr(governance_gate, "active_rulesets", lambda _: {"develop": policy})
    governance_gate.verify()
    assert "match" in capsys.readouterr().out
    monkeypatch.setattr(governance_gate, "active_rulesets", lambda _: {"main": policy})
    with pytest.raises(RuntimeError, match=r"missing=.*develop.*extra=.*main"):
        governance_gate.verify()


def test_release_asset_helpers_and_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    spec = _spec(tmp_path / "package")
    wheel = _wheel(dist / "marketsieve_example-0.15.0-py3-none-any.whl")
    sdist = _sdist(dist / "marketsieve_example-0.15.0.tar.gz")
    monkeypatch.setattr(release_gate, "load_package_catalog", lambda: (spec,))
    assert release_gate.distributions(dist) == ((wheel,), (sdist,))
    assert release_gate.metadata_version(wheel) == "0.15.0"
    assert release_gate.wheel_requirement(wheel) == "example==0.15.0"
    release_gate.verify_contents(dist)
    release_gate.write_wheelhouse_assets(dist, "0.15.0")
    release_gate.verify_wheelhouse_assets(dist, "0.15.0")
    assert {path.name for path in release_gate.release_assets(dist)} >= {
        "constraints.txt",
        "VERIFY.md",
        "SHA256SUMS",
    }
    (dist / "constraints.txt").write_text("wrong==1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="constraints"):
        release_gate.verify_wheelhouse_assets(dist, "0.15.0")


def test_release_directory_and_runtime_wheel_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    release_gate.prepare_dist_dir(dist)
    assert dist.is_dir()
    (dist / "unexpected").touch()
    with pytest.raises(RuntimeError, match="must be empty"):
        release_gate.prepare_dist_dir(dist)
    (dist / "unexpected").unlink()
    (dist / ".gitignore").write_text("*", encoding="utf-8")
    release_gate.prepare_dist_dir(dist)

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    locked = runtime / "dependency.whl"
    locked.write_bytes(b"same")
    (dist / locked.name).write_bytes(b"same")
    monkeypatch.setattr(release_gate, "RUNTIME_WHEELHOUSE", runtime)
    release_gate.verify_runtime_wheels(dist)
    (dist / locked.name).write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="locked"):
        release_gate.verify_runtime_wheels(dist)


def test_release_source_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(distribution="example", project_version="0.14.0")
    monkeypatch.setattr(release_gate, "load_package_catalog", lambda: (spec,))
    with pytest.raises(RuntimeError, match="versions"):
        release_gate.validate_source_release("0.15.0")


def test_review_metrics_resolution_and_delta_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "junit.xml").write_text(
        '<testsuites><testsuite tests="7"/></testsuites>', encoding="utf-8"
    )
    (evidence / "coverage.json").write_text(
        json.dumps({"totals": {"num_branches": 4, "covered_branches": 3}}), encoding="utf-8"
    )
    assert review_gate.load_metrics(evidence) == (7, 75.0)
    (evidence / "coverage.json").write_text(
        json.dumps({"totals": {"num_branches": 0, "covered_branches": 0}}), encoding="utf-8"
    )
    assert review_gate.load_metrics(evidence) == (7, 100.0)
    (evidence / "junit.xml").write_text("<testsuites/>", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no testsuite"):
        review_gate.load_metrics(evidence)

    monkeypatch.setattr(review_gate, "resolve_commit", lambda value: value * 40)
    returns: Iterator[subprocess.CompletedProcess[Any]] = iter(
        [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0)]
    )
    monkeypatch.setattr("scripts.review_gate.subprocess.run", lambda *args, **kwargs: next(returns))
    assert review_gate.review_base("b", "h", "r") == "r" * 40
    returns = iter([subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)])
    monkeypatch.setattr("scripts.review_gate.subprocess.run", lambda *args, **kwargs: next(returns))
    assert review_gate.review_base("b", "h", "r") == "b"
    assert review_gate.review_base("b", "h", None) == "b"


def test_review_paths_and_failure_summary(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    file = root / "value.txt"
    file.write_text("value", encoding="utf-8")
    directory = root / "evidence"
    directory.mkdir()
    assert review_gate.safe_bundle_path(root, "value.txt") == file
    assert review_gate.safe_bundle_path(root, "evidence", allow_directory=True) == directory
    with pytest.raises(RuntimeError, match="escapes"):
        review_gate.safe_bundle_path(root, "../escape")
    with pytest.raises(RuntimeError, match="missing"):
        review_gate.safe_bundle_path(root, "missing")

    report: dict[str, Any] = {
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "changes": [],
        "checks": [{"name": "Tests", "status": "failed"}],
        "metrics": {"tests": 1, "branch_coverage": 50.0},
        "findings": [{"message": "Review failure"}],
        "cli": {"market_help": {"exit_code": 2}},
    }
    summary = review_gate.render_summary(report)
    assert "Automated checks failed" in summary
    assert "Review failure" in summary


def test_review_redaction_and_secret_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch = tmp_path / "patch"
    patch.write_text("safe\n", encoding="utf-8")
    monkeypatch.setattr(review_gate, "scan_patch_text", lambda *_: [SimpleNamespace(line=0)])
    with pytest.raises(RuntimeError, match="cannot be safely"):
        review_gate.redact_patch(patch)
    monkeypatch.setattr(
        review_gate,
        "scan_patch_text",
        lambda *_: [SimpleNamespace(line=1, kind="private_key")],
    )
    with pytest.raises(RuntimeError, match="unterminated"):
        review_gate.redact_patch(patch)
    monkeypatch.setattr(review_gate, "scan_paths", lambda _: ["secret"])
    with pytest.raises(RuntimeError, match="credential"):
        review_gate.ensure_secret_free([patch])


def test_develop_gate_smoke_and_package_workflows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    evidence = root / ".marketsieve" / "evidence"
    evidence.mkdir(parents=True)
    for name in ("doctor-result/v1", "capabilities-result/v8", "log-record/v1"):
        directory = root / "schemas" / name
        directory.mkdir(parents=True)
        (directory / "schema.json").write_text(
            json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema"}),
            encoding="utf-8",
        )
    monkeypatch.setattr(develop_gate, "ROOT", root)

    def smoke_capture(command: Any, **_: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, stdout="0.15.0\n", stderr="")
        if "doctor" in command:
            return subprocess.CompletedProcess(
                command, 0, stdout='{"schema":"doctor-result/v1"}\n', stderr='{"level":"INFO"}\n'
            )
        if "capabilities" in command:
            return subprocess.CompletedProcess(
                command, 0, stdout='{"schema":"capabilities-result/v8"}\n', stderr=""
            )
        return subprocess.CompletedProcess(command, 0, stdout="help\n", stderr="")

    monkeypatch.setattr(develop_gate, "capture", smoke_capture)
    develop_gate.check_smoke(evidence)
    assert json.loads((evidence / "smoke.json").read_text())["version"]["exit_code"] == 0

    spec = _spec(tmp_path / "package")
    monkeypatch.setattr(develop_gate, "load_package_catalog", lambda: (spec,))
    monkeypatch.setattr(develop_gate, "EXTERNAL_PLUGIN_EXAMPLES", ())
    monkeypatch.setattr(develop_gate, "verify_isolated_target", lambda *args, **kwargs: None)
    commands: list[tuple[str, ...]] = []

    def package_run(command: Any, **_: Any) -> None:
        command = tuple(command)
        commands.append(command)
        if command[:2] == ("uv", "build"):
            dist = Path(command[-1])
            _wheel(dist / "marketsieve_example-0.15.0-py3-none-any.whl")
            _sdist(dist / "marketsieve_example-0.15.0.tar.gz")

    monkeypatch.setattr(develop_gate, "run", package_run)
    monkeypatch.setattr(
        develop_gate,
        "capture",
        lambda command, **_: subprocess.CompletedProcess(command, 0, stdout="0.15.0\n", stderr=""),
    )
    package_evidence = root / ".marketsieve" / "package-evidence"
    package_evidence.mkdir()
    develop_gate.check_package(package_evidence)
    package = json.loads((package_evidence / "package.json").read_text())
    assert package["version"] == "0.15.0"
    assert len(package["artifacts"]) == 2
    assert any(command[:2] == ("uv", "build") for command in commands)


def test_release_build_verify_and_export_workflow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "CHANGELOG.md").write_text("## [0.15.0] - 2026-08-08\n", encoding="utf-8")
    spec = _spec(tmp_path / "package")
    runtime = root / ".marketsieve" / "cache" / "runtime-wheelhouse"
    runtime.mkdir(parents=True)
    _wheel(runtime / "dependency-1.0-py3-none-any.whl", name="dependency", version="1.0")
    monkeypatch.setattr(release_gate, "ROOT", root)
    monkeypatch.setattr(release_gate, "RUNTIME_WHEELHOUSE", runtime)
    monkeypatch.setattr(release_gate, "load_package_catalog", lambda: (spec,))
    monkeypatch.setattr(release_gate, "verify_secrets", lambda _: None)
    commit = "a" * 40

    def fake_run(command: Any, **_: Any) -> None:
        command = tuple(command)
        if command[:2] == ("uv", "build"):
            dist = Path(command[-1])
            _wheel(dist / "marketsieve_example-0.15.0-py3-none-any.whl")
            _sdist(dist / "marketsieve_example-0.15.0.tar.gz")

    def fake_capture(command: Any, **_: Any) -> str:
        return commit if tuple(command) == ("git", "rev-parse", "HEAD") else "0.15.0"

    monkeypatch.setattr(release_gate, "run", fake_run)
    monkeypatch.setattr(release_gate, "capture", fake_capture)
    dist = tmp_path / "release"
    release_gate.build("0.15.0", commit, dist)
    assert (dist / "release.json").is_file()
    release_gate.verify("0.15.0", commit, dist)
    output = tmp_path / "pypi"
    release_gate.export_pypi("0.15.0", commit, dist, output)
    assert {path.suffix for path in output.iterdir()} == {".whl", ".gz"}

    manifest = json.loads((dist / "release.json").read_text())
    manifest["commit"] = "b" * 40
    (dist / "release.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="provenance"):
        release_gate.verify("0.15.0", commit, dist)


def test_review_create_builds_and_validates_a_single_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = tmp_path / "develop"
    evidence.mkdir()
    (evidence / "junit.xml").write_text('<testsuite tests="3"/>', encoding="utf-8")
    (evidence / "coverage.json").write_text(
        json.dumps({"totals": {"num_branches": 2, "covered_branches": 2}}), encoding="utf-8"
    )
    for name in ("coverage-metadata.json", "package.json"):
        (evidence / name).write_text("{}\n", encoding="utf-8")
    (evidence / "smoke.json").write_text(
        json.dumps(
            {
                "version": {},
                "doctor": {},
                "module_doctor": {},
                "capabilities": {},
                "market_help": {"exit_code": 0},
                "research_help": {"exit_code": 0},
            }
        ),
        encoding="utf-8",
    )
    (evidence / "logs.jsonl").write_text("", encoding="utf-8")
    base, head = "a" * 40, "b" * 40
    state = tmp_path / ".marketsieve"
    output = state / "reviews" / head
    monkeypatch.setattr(review_gate, "STATE_ROOT", state)
    monkeypatch.setattr(review_gate, "ensure_secret_free", lambda _: None)
    monkeypatch.setattr(review_gate, "resolve_commit", lambda value: value)
    monkeypatch.setattr(review_gate, "repository_name", lambda: "owner/repo")
    monkeypatch.setattr(review_gate, "changed_files", lambda *_: [])
    monkeypatch.setattr(review_gate, "tool_version", lambda *_: "tool 1")

    def fake_capture(*command: str) -> str:
        assert command[:2] == ("git", "diff")
        return "diff --git a/a b/a\n"

    monkeypatch.setattr(review_gate, "capture", fake_capture)
    review_gate.create(base, head, evidence, output)
    assert (output / "review.json").is_file()
    review_gate.validate(output)
