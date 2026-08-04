"""Reject credentials from tracked files, diffs, and generated evidence."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parents[1]
MAX_TEXT_BYTES = 5 * 1024 * 1024
SENSITIVE_NAMES = re.compile(r"(?:^|/)(?:\.env(?:\..+)?|credentials?|secrets?)(?:$|/)")
PERMITTED_NAMES = {".env.example"}
PLACEHOLDERS = {"", "example", "placeholder", "replace-me", "set-me"}


def _joined(*parts: str) -> str:
    return "".join(parts)


PATTERNS = (
    ("private_key", re.compile(_joined("-----BEGIN ", "(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"))),
    ("openai_key", re.compile(_joined(r"\bsk-", r"[A-Za-z0-9_-]{20,}\b"))),
    ("google_key", re.compile(_joined(r"\bAIza", r"[A-Za-z0-9_-]{30,}\b"))),
    ("github_token", re.compile(_joined(r"\b(?:ghp_|github_pat_)", r"[A-Za-z0-9_]{20,}\b"))),
    ("aws_access_key", re.compile(_joined(r"\bAKIA", r"[A-Z0-9]{16}\b"))),
    ("slack_token", re.compile(_joined(r"\bxox[baprs]-", r"[A-Za-z0-9-]{20,}\b"))),
    (
        "bearer_token",
        re.compile(_joined(r"(?i)authorization\s*[:=]\s*bearer\s+", r"[^\s\"']{12,}")),
    ),
)
ASSIGNMENT = re.compile(
    r"(?i)^\s*([A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|PASSWORD))"
    r"\s*=\s*([^#\s]+)\s*$"
)


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    kind: str


def _capture(command: Sequence[str]) -> bytes:
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True).stdout


def _tracked_paths() -> tuple[Path, ...]:
    values = _capture(("git", "ls-files", "-z")).split(b"\0")
    return tuple(ROOT / value.decode() for value in values if value)


def _artifact_paths(roots: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(
        path
        for root in roots
        if root.exists()
        for path in (root.rglob("*") if root.is_dir() else (root,))
        if path.is_file()
    )


def _read_text(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if len(payload) > MAX_TEXT_BYTES or b"\0" in payload:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _scan_text(label: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        assignment = ASSIGNMENT.match(line)
        if assignment and assignment.group(2).strip("\"'").lower() not in PLACEHOLDERS:
            findings.append(Finding(label, line_number, "credential_assignment"))
        for kind, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(Finding(label, line_number, kind))
    return findings


def _scan_added_lines(label: str, patch: bytes) -> list[Finding]:
    additions = "\n".join(
        line[1:]
        for line in patch.decode("utf-8", errors="replace").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    return _scan_text(label, additions)


def scan_paths(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in dict.fromkeys(paths):
        try:
            label = str(path.relative_to(ROOT))
        except ValueError:
            label = str(path)
        if path.name not in PERMITTED_NAMES and SENSITIVE_NAMES.search(label):
            findings.append(Finding(label, 0, "sensitive_path"))
        text = _read_text(path)
        if text is not None:
            findings.extend(_scan_text(label, text))
    return findings


def scan_diff(base: str) -> list[Finding]:
    patch = _capture(("git", "diff", "--no-ext-diff", "--unified=0", base, "--"))
    return _scan_added_lines(f"git-diff:{base}", patch)


def scan_history(base: str) -> list[Finding]:
    commits = _capture(("git", "rev-list", "--reverse", f"{base}..HEAD")).splitlines()
    findings: list[Finding] = []
    for commit in commits:
        sha = commit.decode("ascii")
        patch = _capture(
            (
                "git",
                "diff-tree",
                "--root",
                "-m",
                "-p",
                "--no-commit-id",
                "--unified=0",
                sha,
                "--",
            )
        )
        findings.extend(_scan_added_lines(f"git-commit:{sha}", patch))
    return findings


def check(paths: tuple[Path, ...], base: str | None) -> None:
    findings = scan_paths((*_tracked_paths(), *_artifact_paths(paths)))
    if base is not None:
        findings.extend(scan_diff(base))
        findings.extend(scan_history(base))
    unique = sorted(set(findings), key=lambda item: (item.path, item.line, item.kind))
    if unique:
        for finding in unique:
            location = f"{finding.path}:{finding.line}" if finding.line else finding.path
            print(f"secret finding: {location} [{finding.kind}]")
        raise SystemExit(1)
    print("Secret scan passed without exposing file contents.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", default=[], type=Path)
    parser.add_argument("--base")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    check(tuple(args.path), args.base)


if __name__ == "__main__":
    main()
