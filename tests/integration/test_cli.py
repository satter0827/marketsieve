from __future__ import annotations

import importlib
import json
from typing import Any

import pytest
from click import Group
from click.testing import CliRunner

from marketsieve import __version__
from marketsieve_cli.application.acquisition_errors import MarketSnapshotRunCancelled
from marketsieve_cli.contracts import COMMAND_CAPABILITIES
from marketsieve_cli.interfaces.cli import main


def _command_paths(group: Group, prefix: tuple[str, ...] = ()) -> set[str]:
    paths: set[str] = set()
    for name, command in group.commands.items():
        path = (*prefix, name)
        if isinstance(command, Group):
            paths.update(_command_paths(command, path))
        else:
            paths.add(" ".join(path))
    return paths


def test_public_cli_is_small_and_explicit() -> None:
    runner = CliRunner()
    landing = runner.invoke(main, [])
    version = runner.invoke(main, ["--version"])
    capabilities = runner.invoke(main, ["capabilities", "--output", "json"])

    assert landing.exit_code == 0
    assert "market build --all" in landing.stdout
    assert version.output == f"marketsieve, version {__version__}\n"
    document = json.loads(capabilities.stdout)
    assert document["schema"] == "capabilities-result/v13"
    assert set(main.commands) == {
        "market",
        "research",
        "operations",
        "doctor",
        "capabilities",
    }
    assert _command_paths(main) == {item.name for item in COMMAND_CAPABILITIES}
    assert {item["name"] for item in document["commands"]} == _command_paths(main)
    preview = {item["name"]: item for item in document["commands"]}["market preview"]
    assert preview["result"] == {"mode": "loopback_server", "schema": None}
    assert preview["effects"]["loopback_server"] is True
    build = {item["name"]: item for item in document["commands"]}["market build"]
    assert build["result"] == {"mode": "document", "schema": "market-snapshot/v9"}
    assert build["effects"]["external_network"] is True
    for removed in (
        "preview",
        "artifacts",
        "run",
        "portfolio",
        "watchlist",
        "daily",
        "weekly",
        "source",
        "snapshot",
    ):
        assert runner.invoke(main, [removed]).exit_code == 2


def test_market_build_requires_explicit_scope_evidence_and_history() -> None:
    runner = CliRunner()
    missing_scope = runner.invoke(
        main, ["market", "build", "--evidence", "price", "--history-days", "1095"]
    )
    missing_evidence = runner.invoke(main, ["market", "build", "--all"])
    benchmark_without_price = runner.invoke(
        main,
        [
            "market",
            "build",
            "--all",
            "--evidence",
            "benchmarks",
            "--history-days",
            "1095",
        ],
    )

    assert missing_scope.exit_code == 1
    assert "select exactly one scope" in missing_scope.output
    assert missing_evidence.exit_code == 1
    assert "evidence" in missing_evidence.output
    assert benchmark_without_price.exit_code == 1
    assert "requires price evidence" in benchmark_without_price.output


def test_market_build_cancel_returns_130_and_exact_resume_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")

    def cancel(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise MarketSnapshotRunCancelled("0123456789abcdef")

    monkeypatch.setattr(cli_module, "build_market_snapshot", cancel)
    result = CliRunner().invoke(
        main,
        [
            "market",
            "build",
            "--all",
            "--evidence",
            "price",
            "--history-days",
            "365",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 130
    assert result.stdout == ""
    assert "marketsieve market build --resume 0123456789abcdef" in result.stderr


def test_saved_data_commands_require_snapshot_identity() -> None:
    runner = CliRunner()
    assert runner.invoke(main, ["market", "show"]).exit_code == 2
    assert runner.invoke(main, ["market", "security", "XNAS:MSFT"]).exit_code == 2
    assert runner.invoke(main, ["market", "query"]).exit_code == 2
    assert runner.invoke(main, ["research", "build", "XNAS:MSFT"]).exit_code == 2


def test_market_query_maps_repeatable_cli_classifications_to_canonical_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli_module = importlib.import_module("marketsieve_cli.interfaces.cli.main")
    captured: dict[str, Any] = {}

    def query(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["request"] = args[1]
        return {
            "schema": "market-snapshot-query-result/v2",
            "snapshot_id": "a" * 64,
            "matched_count": 0,
            "fields": [],
            "rows": [],
        }

    monkeypatch.setattr(cli_module, "query_market_snapshot", query)

    result = CliRunner().invoke(
        main,
        [
            "market",
            "query",
            "--snapshot",
            "latest",
            "--market",
            "jp",
            "--index",
            "nikkei225",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert captured["request"].filters == {"market": ("jp",), "index": ("nikkei225",)}
