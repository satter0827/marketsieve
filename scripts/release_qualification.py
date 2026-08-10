"""Qualify one published release candidate and guard stable promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from datetime import date
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import exchange_calendars  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator

from marketsieve_cli.adapters.artifacts import ArtifactInventory
from marketsieve_cli.adapters.market_snapshots import MarketSnapshotStore
from marketsieve_cli.adapters.operations import OperationRunStore
from marketsieve_cli.adapters.preview import ObjectPreviewServer
from marketsieve_cli.adapters.research import ResearchStore
from marketsieve_cli.market_catalog import MARKET_INDEX_GROUPS
from scripts.package_catalog import load_package_catalog
from scripts.release_gate import verify as verify_release

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "scripts/schemas/release-qualification-v1.json"
STANDARD_EVIDENCE = ("benchmarks", "company", "financials", "price")
PROMOTION_FILES = {
    "CHANGELOG.md",
    "docs/roadmap.md",
    "packages/cli/pyproject.toml",
    "packages/core/pyproject.toml",
    "packages/extension-api/pyproject.toml",
    "packages/source-yfinance/pyproject.toml",
    "uv.lock",
}


def capture(*command: str) -> str:
    return subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_consecutive_sessions(market: str, dates: tuple[str, ...]) -> None:
    """Require exactly three consecutive sessions for one exchange."""

    if len(dates) != 3 or dates != tuple(sorted(set(dates))):
        raise ValueError(f"{market} qualification requires three unique ordered sessions")
    calendar_name = "XTKS" if market == "jp" else "XNYS"
    calendar = exchange_calendars.get_calendar(calendar_name)
    sessions = tuple(
        value.date().isoformat() for value in calendar.sessions_in_range(dates[0], dates[-1])
    )
    if sessions != dates:
        raise ValueError(f"{market} snapshots are not three consecutive exchange sessions")


def validate_snapshot(document: dict[str, Any], *, market: str, version: str) -> str:
    """Validate one full close-capture Snapshot and return its evidence date."""

    inputs = document.get("request", {}).get("inputs", {})
    producer = document.get("request", {}).get("producer", {})
    if document.get("schema") != "market-snapshot/v9":
        raise ValueError("qualification Snapshot must use market-snapshot/v9")
    if tuple(inputs.get("indices", ())) != MARKET_INDEX_GROUPS[market]:
        raise ValueError(f"{market} Snapshot does not use the standard index scope")
    if tuple(inputs.get("evidence", ())) != STANDARD_EVIDENCE:
        raise ValueError(f"{market} Snapshot does not use the standard evidence scope")
    if inputs.get("mode") != "current" or inputs.get("session") != "close":
        raise ValueError("qualification Snapshot must be an actual current close capture")
    if producer.get("version") != version:
        raise ValueError("qualification Snapshot producer does not match the release candidate")
    if document.get("price_coverage_gate_passed") is not True:
        raise ValueError("qualification Snapshot did not pass its price coverage gate")
    markets = document.get("market", {}).get("markets", {})
    evidence_date = markets.get(market, {}).get("latest_price_date")
    if not isinstance(evidence_date, str):
        raise ValueError("qualification Snapshot has no market evidence date")
    date.fromisoformat(evidence_date)
    return evidence_date


def validate_recovery(cancelled: dict[str, Any], resumed: dict[str, Any]) -> None:
    """Validate exact Market cancellation and recovery evidence."""

    if cancelled.get("status") != "cancelled" or cancelled.get("exit_code") != 130:
        raise ValueError("Market interruption must be recorded as cancelled with exit code 130")
    if cancelled.get("command") not in {"market build", "market capture"}:
        raise ValueError("cancelled operation is not a Market acquisition")
    resume_id = cancelled.get("resume_run_id")
    if not isinstance(resume_id, str) or not re.fullmatch(r"[0-9a-f]{16}", resume_id):
        raise ValueError("cancelled Market operation has no exact resume ID")
    if resumed.get("status") != "completed" or resumed.get("exit_code") != 0:
        raise ValueError("resumed Market operation did not complete")
    if resumed.get("command") != "market build":
        raise ValueError("resumed operation is not an exact Market resume")
    if cancelled.get("input_fingerprint") != resumed.get("input_fingerprint"):
        raise ValueError("resumed Market operation changed the input fingerprint")
    if not resumed.get("published_object_ids"):
        raise ValueError("resumed Market operation published no Snapshot")


def preview_object(path: Path) -> None:
    """Read every registered object file through the restricted server."""

    server = ObjectPreviewServer(path)
    url = server.start()
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        routes = ("manifest.json", *manifest["artifacts"])
        origin = url.rsplit("/", maxsplit=1)[0]
        for route in routes:
            with urlopen(f"{origin}/{route}", timeout=5) as response:
                body = response.read()
                if response.status != 200 or (route == "explorer.html" and not body):
                    raise ValueError(f"Explorer preview could not read registered file: {route}")
    finally:
        server.close()


def render_summary(report: dict[str, Any]) -> str:
    lines = [
        "# MarketSieve Release Qualification",
        "",
        f"- Status: {report['status']}",
        f"- Version: {report['version']}",
        f"- Commit: `{report['commit']}`",
        f"- Tag: `{report['tag']}`",
        "",
        "## Evidence",
        "",
        f"- JP close Snapshots: {', '.join(report['snapshots']['jp'])}",
        f"- US close Snapshots: {', '.join(report['snapshots']['us'])}",
        f"- Research Packs: {', '.join(report['research'])}",
        f"- Operation runs: {', '.join(report['operations'].values())}",
        "",
    ]
    return "\n".join(lines)


def qualify(args: argparse.Namespace) -> dict[str, Any]:
    """Validate explicit published-RC operational evidence and write its report."""

    if capture("git", "rev-list", "-n", "1", args.tag) != args.commit:
        raise ValueError("release tag does not identify the qualification commit")
    verify_release(args.version, args.commit, args.release_dir)
    manifest = json.loads((args.release_dir / "release.json").read_text(encoding="utf-8"))
    if manifest.get("version") != args.version or manifest.get("commit") != args.commit:
        raise ValueError("release manifest does not match qualification provenance")

    snapshots = MarketSnapshotStore(args.state_root / "market-snapshots")
    research = ResearchStore(args.state_root / "research")
    operations = OperationRunStore(args.state_root)
    snapshot_ids = {"jp": tuple(args.jp_snapshot), "us": tuple(args.us_snapshot)}
    for market, object_ids in snapshot_ids.items():
        dates = []
        for object_id in object_ids:
            document = snapshots.show(object_id)
            dates.append(validate_snapshot(document, market=market, version=args.version))
        validate_consecutive_sessions(market, tuple(dates))

    research_ids = (args.jp_research, args.us_research)
    expected_snapshots = (snapshot_ids["jp"][-1], snapshot_ids["us"][-1])
    for research_id, snapshot_id in zip(research_ids, expected_snapshots, strict=True):
        document = research.show(research_id)
        if document.get("snapshot_id") != snapshot_id:
            raise ValueError("Research Pack does not use the final qualified Snapshot")
        if document.get("price_coverage_gate_passed") is not True:
            raise ValueError("Research Pack did not pass its price coverage gate")
        preview_object(args.state_root / "research/objects" / research_id)

    cancelled_market = operations.show(args.cancelled_market_run)
    resumed_market = operations.show(args.resumed_market_run)
    validate_recovery(cancelled_market, resumed_market)
    cancelled_research = operations.show(args.cancelled_research_run)
    if (
        cancelled_research.get("command") != "research build"
        or cancelled_research.get("status") != "cancelled"
        or cancelled_research.get("exit_code") != 130
        or not cancelled_research.get("published_object_ids")
    ):
        raise ValueError("cancelled Research operation retained no published Pack")
    for object_id in cancelled_research["published_object_ids"]:
        research.show(object_id)

    preview_object(args.state_root / "market-snapshots/objects" / snapshot_ids["jp"][-1])
    preview_object(args.state_root / "market-snapshots/objects" / snapshot_ids["us"][-1])
    inventory = ArtifactInventory(
        args.state_root,
        validators={
            "snapshot": MarketSnapshotStore._verify_object,
            "research": ResearchStore._verify,
        },
    ).doctor()
    if any(inventory["counts"].get(name) for name in ("corrupt", "orphan")):
        raise ValueError("qualified state contains unhealthy evidence objects")

    report = {
        "schema": "release-qualification/v1",
        "status": "ready",
        "version": args.version,
        "commit": args.commit,
        "tag": args.tag,
        "release_manifest_sha256": sha256(args.release_dir / "release.json"),
        "snapshots": {name: list(values) for name, values in snapshot_ids.items()},
        "research": list(research_ids),
        "operations": {
            "cancelled_market": args.cancelled_market_run,
            "resumed_market": args.resumed_market_run,
            "cancelled_research": args.cancelled_research_run,
        },
    }
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "qualification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "summary.md").write_text(render_summary(report), encoding="utf-8")
    return report


def normalized_pyproject(value: str) -> str:
    value = re.sub(r'^version = "[^"]+"$', 'version = "VERSION"', value, flags=re.MULTILINE)
    value = re.sub(
        r'"(marketsieve(?:-extension-api|-source-yfinance)?)==[^"]+"',
        r'"\1==VERSION"',
        value,
    )
    return re.sub(
        r'"Development Status :: [45] - (?:Beta|Production/Stable)"',
        '"Development Status :: STATUS"',
        value,
    )


def normalized_lock(value: str) -> dict[str, Any]:
    """Normalize only co-released workspace versions in a uv lock document."""

    document = tomllib.loads(value)
    suite = {spec.distribution for spec in load_package_catalog()}
    for package in document.get("package", []):
        if package.get("name") in suite:
            package["version"] = "VERSION"
    return document


def guard_promotion(rc_tag: str, candidate: str) -> dict[str, Any]:
    """Require a metadata-only diff from the qualified RC to stable."""

    capture("git", "merge-base", "--is-ancestor", rc_tag, candidate)
    changed = set(capture("git", "diff", "--name-only", rc_tag, candidate).splitlines())
    if changed - PROMOTION_FILES:
        raise ValueError(
            f"stable promotion changes frozen files: {sorted(changed - PROMOTION_FILES)}"
        )
    for path in sorted(name for name in changed if name.endswith("pyproject.toml")):
        before = capture("git", "show", f"{rc_tag}:{path}")
        after = capture("git", "show", f"{candidate}:{path}")
        if normalized_pyproject(before) != normalized_pyproject(after):
            raise ValueError(f"stable promotion changes non-release package metadata: {path}")
    if "uv.lock" in changed:
        before = capture("git", "show", f"{rc_tag}:uv.lock")
        after = capture("git", "show", f"{candidate}:uv.lock")
        if normalized_lock(before) != normalized_lock(after):
            raise ValueError("stable promotion changes locked third-party dependencies")
    versions = {spec.project_version for spec in load_package_catalog()}
    if candidate == "HEAD" and versions != {"1.0.0"}:
        raise ValueError("stable promotion packages must all use version 1.0.0")
    return {
        "schema": "release-promotion/v1",
        "rc_tag": rc_tag,
        "candidate": candidate,
        "files": sorted(changed),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    qualify_parser = commands.add_parser("qualify")
    qualify_parser.add_argument("--version", required=True)
    qualify_parser.add_argument("--commit", required=True)
    qualify_parser.add_argument("--tag", required=True)
    qualify_parser.add_argument("--release-dir", required=True, type=Path)
    qualify_parser.add_argument("--state-root", required=True, type=Path)
    qualify_parser.add_argument("--jp-snapshot", required=True, action="append")
    qualify_parser.add_argument("--us-snapshot", required=True, action="append")
    qualify_parser.add_argument("--jp-research", required=True)
    qualify_parser.add_argument("--us-research", required=True)
    qualify_parser.add_argument("--cancelled-market-run", required=True)
    qualify_parser.add_argument("--resumed-market-run", required=True)
    qualify_parser.add_argument("--cancelled-research-run", required=True)
    qualify_parser.add_argument("--output-dir", required=True, type=Path)
    promotion = commands.add_parser("guard-promotion")
    promotion.add_argument("--rc-tag", required=True)
    promotion.add_argument("--candidate", default="HEAD")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "qualify":
        print(json.dumps(qualify(args), sort_keys=True))
    else:
        print(json.dumps(guard_promotion(args.rc_tag, args.candidate), sort_keys=True))


if __name__ == "__main__":
    main()
