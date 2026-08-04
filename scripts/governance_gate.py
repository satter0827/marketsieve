"""Verify checked-in branch rules against active GitHub rulesets."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.github_repository import repository_name

ROOT = Path(__file__).parents[1]
RULESETS = ROOT / ".github" / "rulesets"
COMPARABLE_FIELDS = ("name", "target", "enforcement", "conditions", "rules", "bypass_actors")


def capture(*command: str) -> str:
    return subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def normalized_ruleset(document: dict[str, Any]) -> dict[str, Any]:
    return {field: copy.deepcopy(document[field]) for field in COMPARABLE_FIELDS}


def checked_in_rulesets() -> dict[str, dict[str, Any]]:
    documents = (json.loads(path.read_text(encoding="utf-8")) for path in RULESETS.glob("*.json"))
    return {document["name"]: normalized_ruleset(document) for document in documents}


def active_rulesets(repository: str) -> dict[str, dict[str, Any]]:
    summaries = json.loads(capture("gh", "api", f"repos/{repository}/rulesets"))
    documents = (
        json.loads(capture("gh", "api", f"repos/{repository}/rulesets/{item['id']}"))
        for item in summaries
    )
    return {document["name"]: normalized_ruleset(document) for document in documents}


def verify() -> None:
    repository = repository_name(capture("git", "remote", "get-url", "origin"))
    expected = checked_in_rulesets()
    actual = active_rulesets(repository)
    if actual != expected:
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        changed = sorted(
            name for name in expected.keys() & actual.keys() if expected[name] != actual[name]
        )
        raise RuntimeError(
            "active GitHub rulesets differ from checked-in policy: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    print(f"GitHub rulesets match checked-in policy for {repository}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify",))
    return parser.parse_args()


def main() -> None:
    parse_args()
    verify()


if __name__ == "__main__":
    main()
