"""Create and validate machine-readable review evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from scripts.secret_gate import scan_patch_text, scan_paths

ROOT = Path(__file__).parents[1]
STATE_ROOT = ROOT / ".marketsieve"
SCHEMA_VERSION = "2.1.0"
SCHEMA_PATH = ROOT / "schemas/review-report/v2/schema.json"


def capture(*command: str) -> str:
    return subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True, errors="replace"
    ).stdout.strip()


def resolve_commit(value: str) -> str:
    resolved = capture("git", "rev-parse", value)
    if len(resolved) != 40:
        raise RuntimeError(f"not a complete Git commit: {value}")
    return resolved


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_name() -> str:
    remote = capture("git", "remote", "get-url", "origin")
    suffix = remote.removesuffix(".git")
    if suffix.startswith("https://github.com/"):
        return suffix.removeprefix("https://github.com/")
    if suffix.startswith("git@github.com:"):
        return suffix.removeprefix("git@github.com:")
    return suffix


def changed_files(base: str, head: str) -> list[dict[str, Any]]:
    statuses = {}
    for line in capture("git", "diff", "--no-renames", "--name-status", base, head).splitlines():
        if line:
            status, path = line.split("\t", 1)
            statuses[path] = status
    counts = {}
    for line in capture("git", "diff", "--no-renames", "--numstat", base, head).splitlines():
        if line:
            added, deleted, path = line.split("\t", 2)
            counts[path] = (
                None if added == "-" else int(added),
                None if deleted == "-" else int(deleted),
            )
    return [
        {
            "path": path,
            "status": status,
            "added_lines": counts.get(path, (None, None))[0],
            "deleted_lines": counts.get(path, (None, None))[1],
        }
        for path, status in sorted(statuses.items())
    ]


def tool_version(*command: str) -> str:
    return capture(*command).splitlines()[0]


def render_summary(report: dict[str, Any]) -> str:
    failures = [item for item in report["checks"] if item["status"] != "passed"]
    findings = report["findings"]
    cli_analysis = report.get("cli", {}).get("analysis", {})
    cli_report = report.get("cli", {}).get("report", {})
    cli_result = cli_analysis or cli_report
    section_statuses = cli_result.get("section_statuses", {})
    cli_lines = [f"- {name}: status={status}" for name, status in sorted(section_statuses.items())]
    if cli_analysis.get("analysis_id"):
        cli_lines.append(f"- analysis={cli_analysis['analysis_id']}")
    elif cli_report.get("report_id"):
        cli_lines.append(f"- report={cli_report['report_id']}")
    lines = [
        "# Review Summary",
        "",
        "## Conclusion",
        "",
        "Ready for human review." if not failures else "Automated checks failed.",
        "",
        "## Change Scope",
        "",
        f"- Base: `{report['base_sha']}`",
        f"- Head: `{report['head_sha']}`",
        f"- Changed files: {len(report['changes'])}",
        "",
        "## Failures",
        "",
        "None." if not failures else "\n".join(f"- {item['name']}" for item in failures),
        "",
        "## Key Metrics",
        "",
        f"- Tests: {report['metrics']['tests']}",
        f"- Branch coverage: {report['metrics']['branch_coverage']:.2f}%",
        "",
        "## Structure and Schema Changes",
        "",
        "See `review.json` and `changes.patch` for machine-readable details.",
        "",
        "## CLI Verification",
        "",
        "\n".join(cli_lines) if cli_lines else "See `evidence/smoke.json`.",
        "",
        "## Decisions Required",
        "",
        "None." if not findings else "\n".join(f"- {item['message']}" for item in findings),
        "",
    ]
    return "\n".join(lines)


def load_metrics(evidence: Path) -> tuple[int, float]:
    junit_root = ET.parse(evidence / "junit.xml").getroot()
    suite = junit_root if junit_root.tag == "testsuite" else junit_root.find("testsuite")
    if suite is None:
        raise RuntimeError("JUnit evidence has no testsuite")
    tests = int(suite.attrib["tests"])
    coverage = json.loads((evidence / "coverage.json").read_text(encoding="utf-8"))
    return tests, float(coverage["totals"]["percent_covered"])


def redact_patch(path: Path) -> None:
    findings = scan_patch_text(str(path), path.read_text(encoding="utf-8"))
    if any(finding.line <= 0 for finding in findings):
        raise RuntimeError("review patch contains content that cannot be safely redacted")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    redacted_lines = {finding.line for finding in findings}
    for finding in findings:
        if finding.kind != "private_key":
            continue
        end_line = next(
            (
                index
                for index in range(finding.line - 1, len(lines))
                if (
                    lines[index][1:] if lines[index].startswith(("+", "-", " ")) else lines[index]
                ).find("-----END ")
                >= 0
                and "PRIVATE KEY-----" in lines[index]
            ),
            None,
        )
        if end_line is None:
            raise RuntimeError("review patch contains an unterminated private-key block")
        redacted_lines.update(range(finding.line, end_line + 2))
    for line_number in redacted_lines:
        original = lines[line_number - 1]
        prefix = original[0] if original.startswith(("+", "-", " ")) else ""
        newline = "\n" if original.endswith("\n") else ""
        lines[line_number - 1] = f"{prefix}[REDACTED CREDENTIAL]{newline}"
    path.write_text("".join(lines), encoding="utf-8")


def ensure_secret_free(paths: list[Path]) -> None:
    if scan_paths(paths):
        raise RuntimeError("review bundle contains credential-like or unscannable content")


def create(base_value: str, head_value: str, evidence: Path, output: Path) -> None:
    base = resolve_commit(base_value)
    head = resolve_commit(head_value)
    if not evidence.is_dir():
        raise RuntimeError(f"missing develop evidence: {evidence}")
    resolved = output.resolve()
    if STATE_ROOT.resolve() not in resolved.parents:
        raise RuntimeError("review output must be inside .marketsieve")
    shutil.rmtree(resolved, ignore_errors=True)
    evidence_output = resolved / "evidence"
    evidence_output.mkdir(parents=True)
    for name in ("junit.xml", "coverage.json", "package.json", "smoke.json"):
        shutil.copy2(evidence / name, evidence_output / name)
    shutil.copy2(evidence / "logs.jsonl", resolved / "logs.jsonl")

    patch = capture("git", "diff", "--no-color", "--no-ext-diff", "--unified=3", base, head)
    patch_path = resolved / "changes.patch"
    patch_path.write_text(patch + ("\n" if patch else ""), encoding="utf-8")
    redact_patch(patch_path)

    tests, branch_coverage = load_metrics(evidence_output)
    smoke = json.loads((evidence_output / "smoke.json").read_text(encoding="utf-8"))
    media_types = {
        "changes.patch": "text/x-diff",
        "evidence/junit.xml": "application/xml",
        "evidence/coverage.json": "application/json",
        "evidence/package.json": "application/json",
        "evidence/smoke.json": "application/json",
        "logs.jsonl": "application/x-ndjson",
    }
    artifacts = [
        {"path": name, "media_type": media_type, "sha256": sha256(resolved / name)}
        for name, media_type in sorted(media_types.items())
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository_name(),
        "base_sha": base,
        "head_sha": head,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "tools": {
                "uv": tool_version("uv", "--version"),
                "ruff": tool_version("uv", "run", "ruff", "--version"),
                "mypy": tool_version("uv", "run", "mypy", "--version"),
                "pytest": tool_version("uv", "run", "pytest", "--version"),
            },
        },
        "changes": changed_files(base, head),
        "checks": [{"name": "Develop Gate", "status": "passed", "evidence": "evidence/"}],
        "metrics": {"tests": tests, "branch_coverage": branch_coverage},
        "cli": smoke,
        "artifacts": artifacts,
        "findings": [],
    }
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    (resolved / "review.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (resolved / "summary.md").write_text(render_summary(report), encoding="utf-8")
    files = sorted(path for path in resolved.rglob("*") if path.is_file())
    ensure_secret_free(files)
    checksums = "".join(f"{sha256(path)}  {path.relative_to(resolved)}\n" for path in files)
    (resolved / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    validate(resolved)


def validate(bundle: Path) -> None:
    bundle = bundle.resolve()
    report = json.loads((bundle / "review.json").read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    if resolve_commit(report["base_sha"]) != report["base_sha"]:
        raise RuntimeError("base_sha is not an available commit")
    if resolve_commit(report["head_sha"]) != report["head_sha"]:
        raise RuntimeError("head_sha is not an available commit")
    if bundle.name != report["head_sha"]:
        raise RuntimeError("bundle directory does not match head_sha")
    expected_summary = render_summary(report)
    if (bundle / "summary.md").read_text(encoding="utf-8") != expected_summary:
        raise RuntimeError("summary.md is not the generated projection of review.json")
    checksum_lines = (bundle / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksummed: set[str] = set()
    for line in checksum_lines:
        expected, name = line.split("  ", 1)
        path = safe_bundle_path(bundle, name)
        checksummed.add(name)
        if sha256(path) != expected:
            raise RuntimeError(f"checksum mismatch: {name}")
    expected_files = {
        str(path.relative_to(bundle))
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if checksummed != expected_files:
        raise RuntimeError("SHA256SUMS does not cover exactly the bundle files")
    ensure_secret_free(
        sorted(path for path in bundle.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    )
    for artifact in report["artifacts"]:
        artifact_path = safe_bundle_path(bundle, artifact["path"])
        if sha256(artifact_path) != artifact["sha256"]:
            raise RuntimeError(f"artifact checksum mismatch: {artifact['path']}")
    for check in report["checks"]:
        safe_bundle_path(bundle, check["evidence"], allow_directory=True)
    for finding in report["findings"]:
        safe_bundle_path(bundle, finding["evidence"])


def safe_bundle_path(bundle: Path, name: str, *, allow_directory: bool = False) -> Path:
    path = (bundle / name).resolve()
    if bundle not in path.parents:
        raise RuntimeError(f"bundle reference escapes its root: {name}")
    exists = path.is_dir() if allow_directory else path.is_file()
    if not exists:
        raise RuntimeError(f"missing bundle reference: {name}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--base-sha", default="origin/develop")
    create_parser.add_argument("--head-sha", default="HEAD")
    create_parser.add_argument("--evidence-dir", type=Path, required=True)
    create_parser.add_argument("--output-dir", type=Path, required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("bundle", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "create":
        create(args.base_sha, args.head_sha, args.evidence_dir, args.output_dir)
    else:
        validate(args.bundle)


if __name__ == "__main__":
    main()
