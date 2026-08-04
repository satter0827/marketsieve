from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts.release_gate import validate_inputs
from scripts.review_gate import SCHEMA_VERSION, render_summary, validate


def test_release_inputs_require_pep440_version_and_complete_commit() -> None:
    validate_inputs("0.1.0.dev0", "a" * 40)

    with pytest.raises(ValueError, match="version"):
        validate_inputs("v0.1", "a" * 40)
    with pytest.raises(ValueError, match="commit"):
        validate_inputs("0.1.0", "abc")


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
