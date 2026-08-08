from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import scripts.release_gate as release_gate
import scripts.review_gate as review_gate
from scripts.github_repository import repository_name
from scripts.governance_gate import normalized_ruleset
from scripts.release_gate import validate_inputs, validate_source_release
from scripts.review_gate import SCHEMA_VERSION, render_summary, validate
from scripts.runtime_wheelhouse import SUPPORTED_PYTHON_VERSIONS, download_command


def test_release_inputs_require_pep440_version_and_complete_commit() -> None:
    validate_inputs("0.15.1", "a" * 40)
    validate_source_release("0.15.1")

    with pytest.raises(ValueError, match="version"):
        validate_inputs("v0.1", "a" * 40)
    with pytest.raises(ValueError, match="stable"):
        validate_inputs("0.1.0.dev0", "a" * 40)
    with pytest.raises(ValueError, match="commit"):
        validate_inputs("0.1.0", "abc")


def test_release_artifacts_are_secret_scanned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(release_gate, "run", commands.append)

    paths = (tmp_path / "sdk.whl", tmp_path / "release.json")
    release_gate.verify_secrets(paths)

    assert commands == [
        (
            sys.executable,
            str(release_gate.ROOT / "scripts" / "secret_gate.py"),
            "--path",
            str(paths[0]),
            "--path",
            str(paths[1]),
        )
    ]


def test_pypi_export_contains_only_public_wheels_and_sdists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    public_wheel = release / "marketsieve-0.7.0-py3-none-any.whl"
    public_sdist = release / "marketsieve-0.7.0.tar.gz"
    runtime_wheel = release / "tzdata-2026.1-py2.py3-none-any.whl"
    for path in (public_wheel, public_sdist, runtime_wheel):
        path.write_bytes(path.name.encode())
    monkeypatch.setattr(release_gate, "verify", lambda *_: None)
    monkeypatch.setattr(release_gate, "distributions", lambda _: ((public_wheel,), (public_sdist,)))

    output = tmp_path / "pypi"
    release_gate.export_pypi("0.7.0", "a" * 40, release, output)

    assert {path.name for path in output.iterdir()} == {
        public_wheel.name,
        public_sdist.name,
    }


def test_pypi_export_refuses_a_nonempty_staging_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(release_gate, "verify", lambda *_: None)
    output = tmp_path / "pypi"
    output.mkdir()
    (output / "unexpected").touch()

    with pytest.raises(RuntimeError, match="must be empty"):
        release_gate.export_pypi("0.7.0", "a" * 40, tmp_path / "release", output)


def test_runtime_wheelhouse_downloads_every_supported_python_version(tmp_path: Path) -> None:
    assert SUPPORTED_PYTHON_VERSIONS == ("3.12", "3.13", "3.14")
    command = download_command(
        tmp_path / "python", tmp_path / "requirements.txt", tmp_path / "wheels", "3.12"
    )

    assert command[0] == str(tmp_path / "python")
    assert command[command.index("--python-version") + 1] == "3.12"
    assert "--only-binary=:all:" in command
    assert "--require-hashes" in command


def test_governance_ruleset_comparison_ignores_github_metadata() -> None:
    policy = {
        "id": 123,
        "name": "develop-quality",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/develop"], "exclude": []}},
        "rules": [{"type": "deletion"}],
        "bypass_actors": [],
        "current_user_can_bypass": "never",
    }

    assert normalized_ruleset(policy) == {
        "name": "develop-quality",
        "target": "branch",
        "enforcement": "active",
        "conditions": policy["conditions"],
        "rules": policy["rules"],
        "bypass_actors": [],
    }
    assert repository_name("https://github.com/satter0827/marketsieve.git") == (
        "satter0827/marketsieve"
    )
    assert repository_name("git@github.com:satter0827/marketsieve.git") == (
        "satter0827/marketsieve"
    )


def test_governance_ruleset_comparison_preserves_integration_bindings() -> None:
    policy = {
        "name": "develop-quality",
        "target": "branch",
        "enforcement": "active",
        "conditions": {},
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "Develop Gate", "integration_id": 15368}]
                },
            }
        ],
        "bypass_actors": [],
    }

    assert normalized_ruleset(policy)["rules"] == policy["rules"]


def test_review_summary_is_a_stable_human_projection() -> None:
    report: dict[str, Any] = {
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "changes": [{"path": "example.py"}],
        "checks": [{"name": "Develop Gate", "status": "passed"}],
        "metrics": {"tests": 12, "branch_coverage": 95.5},
        "findings": [],
    }

    summary = render_summary(report)

    assert summary.startswith("# Review Summary\n")
    assert "Ready for human review." in summary
    assert "- Tests: 12" in summary
    assert "- Branch coverage: 95.50%" in summary
    assert summary.endswith("None.\n")


def test_review_changes_normalize_renames_as_delete_and_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_capture(*command: str) -> str:
        assert "--no-renames" in command
        if "--name-status" in command:
            return "D\told.py\nA\tnew.py"
        if "--numstat" in command:
            return "0\t3\told.py\n4\t0\tnew.py"
        raise AssertionError(command)

    monkeypatch.setattr(review_gate, "capture", fake_capture)

    assert review_gate.changed_files("base", "head") == [
        {"path": "new.py", "status": "A", "added_lines": 4, "deleted_lines": 0},
        {"path": "old.py", "status": "D", "added_lines": 0, "deleted_lines": 3},
    ]


def test_review_capture_replaces_non_utf8_diff_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: tuple[str, ...], **options: Any) -> subprocess.CompletedProcess[str]:
        assert command == ("git", "diff")
        assert options["text"] is True
        assert options["errors"] == "replace"
        return subprocess.CompletedProcess(command, 0, stdout="safe�\n", stderr="")

    monkeypatch.setattr("scripts.review_gate.subprocess.run", fake_run)

    assert review_gate.capture("git", "diff") == "safe�"


def test_review_patch_redacts_removed_credentials(tmp_path: Path) -> None:
    value = "sk-" + "A" * 24
    patch = tmp_path / "changes.patch"
    patch.write_text(f"-OPENAI_API_KEY={value}\n+safe\n", encoding="utf-8")

    review_gate.redact_patch(patch)

    assert patch.read_text(encoding="utf-8") == "-[REDACTED CREDENTIAL]\n+safe\n"


def test_review_patch_redacts_generic_added_assignment(tmp_path: Path) -> None:
    key = "JQUANTS_" + "API_KEY"
    patch = tmp_path / "changes.patch"
    patch.write_text(f"+{key}=opaque-production-credential\n", encoding="utf-8")

    review_gate.redact_patch(patch)

    assert patch.read_text(encoding="utf-8") == "+[REDACTED CREDENTIAL]\n"


def test_review_patch_redacts_complete_private_key_block(tmp_path: Path) -> None:
    patch = tmp_path / "changes.patch"
    header = "-----BEGIN " + "PRIVATE KEY-----"
    footer = "-----END " + "PRIVATE KEY-----"
    patch.write_text(f"-{header}\n-private-material\n-{footer}\n+safe\n", encoding="utf-8")

    review_gate.redact_patch(patch)

    assert patch.read_text(encoding="utf-8") == (
        "-[REDACTED CREDENTIAL]\n-[REDACTED CREDENTIAL]\n-[REDACTED CREDENTIAL]\n+safe\n"
    )


def test_review_patch_redacts_escaped_private_key_on_one_line(tmp_path: Path) -> None:
    patch = tmp_path / "changes.patch"
    header = "-----BEGIN " + "PRIVATE KEY-----"
    footer = "-----END " + "PRIVATE KEY-----"
    patch.write_text(f'-KEY="{header}\\nmaterial\\n{footer}"\n+safe\n', encoding="utf-8")

    review_gate.redact_patch(patch)

    assert patch.read_text(encoding="utf-8") == "-[REDACTED CREDENTIAL]\n+safe\n"


def create_review_bundle(tmp_path: Path) -> Path:
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"), check=True, capture_output=True, text=True
    ).stdout.strip()
    bundle = tmp_path / head
    evidence = bundle / "evidence"
    evidence.mkdir(parents=True)
    patch = bundle / "changes.patch"
    patch.write_text("diff evidence\n", encoding="utf-8")
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "repository": "satter0827/marketsieve",
        "base_sha": head,
        "head_sha": head,
        "environment": {"python": "3.13", "platform": "test", "tools": {}},
        "changes": [],
        "checks": [{"name": "Develop Gate", "status": "passed", "evidence": "evidence/"}],
        "metrics": {"tests": 1, "branch_coverage": 100.0},
        "cli": {
            "version": {},
            "doctor": {},
            "module_doctor": {},
            "capabilities": {},
            "market_help": {"exit_code": 0},
            "research_help": {"exit_code": 0},
        },
        "artifacts": [
            {
                "path": "changes.patch",
                "media_type": "text/x-diff",
                "sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
            }
        ],
        "findings": [],
    }
    (bundle / "review.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (bundle / "summary.md").write_text(render_summary(report), encoding="utf-8")
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    (bundle / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(bundle)}\n"
            for path in files
        ),
        encoding="utf-8",
    )
    return bundle


def test_review_validation_rejects_summary_and_checksum_tampering(tmp_path: Path) -> None:
    bundle = create_review_bundle(tmp_path / "checksum")
    validate(bundle)

    (bundle / "summary.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"summary\.md"):
        validate(bundle)

    bundle = create_review_bundle(tmp_path)
    (bundle / "changes.patch").write_text("changed\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        validate(bundle)
