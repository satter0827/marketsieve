from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import scripts.review_gate as review_gate
from scripts.github_repository import repository_name
from scripts.governance_gate import normalized_ruleset
from scripts.release_gate import validate_inputs
from scripts.review_gate import SCHEMA_VERSION, render_summary, validate


def test_release_inputs_require_pep440_version_and_complete_commit() -> None:
    validate_inputs("0.1.0.dev0", "a" * 40)

    with pytest.raises(ValueError, match="version"):
        validate_inputs("v0.1", "a" * 40)
    with pytest.raises(ValueError, match="commit"):
        validate_inputs("0.1.0", "abc")


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
            "report": {
                "exit_code": 0,
                "schema_valid": True,
                "reproducible": True,
                "reports": [
                    {
                        "market": "jp",
                        "latest": {"status": "ok"},
                        "transitions": [],
                        "report_id": "a" * 64,
                    }
                ],
            },
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
