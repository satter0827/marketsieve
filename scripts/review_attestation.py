"""Publish a commit-bound status after semantic review succeeds."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from scripts.github_repository import repository_name
from scripts.review_gate import validate

ROOT = Path(__file__).parents[1]
COMMIT = re.compile(r"^[0-9a-f]{40}$")
STATUS_CONTEXT = "Semantic Review"


def capture(*command: str, input_text: str | None = None) -> str:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        input=input_text,
    ).stdout.strip()


def attest(reviewed_sha: str) -> None:
    if COMMIT.fullmatch(reviewed_sha) is None:
        raise RuntimeError("reviewed SHA must be a full lowercase commit ID")
    head = capture("git", "rev-parse", "HEAD")
    if reviewed_sha != head:
        raise RuntimeError("reviewed SHA does not match HEAD")
    if capture("git", "status", "--porcelain"):
        raise RuntimeError("working tree must be clean before review attestation")
    validate(ROOT / ".marketsieve" / "artifacts" / "review" / reviewed_sha)

    repository = repository_name(capture("git", "remote", "get-url", "origin"))
    payload = json.dumps(
        {
            "state": "success",
            "context": STATUS_CONTEXT,
            "description": "Semantic review and local evidence passed for this commit",
        }
    )
    capture(
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repository}/statuses/{reviewed_sha}",
        "--input",
        "-",
        input_text=payload,
    )
    print(f"Published {STATUS_CONTEXT} for {reviewed_sha}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    attest_parser = subparsers.add_parser("attest")
    attest_parser.add_argument("--reviewed-sha", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    attest(args.reviewed_sha)


if __name__ == "__main__":
    main()
