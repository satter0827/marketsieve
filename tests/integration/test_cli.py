from __future__ import annotations

import json

from click.testing import CliRunner

from marketsieve import __version__
from marketsieve_cli.interfaces.cli import main


def test_public_cli_is_small_and_explicit() -> None:
    runner = CliRunner()
    landing = runner.invoke(main, [])
    version = runner.invoke(main, ["--version"])
    capabilities = runner.invoke(main, ["capabilities", "--output", "json"])

    assert landing.exit_code == 0
    assert "market build --all" in landing.stdout
    assert version.output == f"marketsieve, version {__version__}\n"
    document = json.loads(capabilities.stdout)
    assert document["schema"] == "capabilities-result/v5"
    assert {item["name"].split()[0] for item in document["commands"]} == {
        "market",
        "research",
        "doctor",
        "capabilities",
    }
    for removed in ("portfolio", "watchlist", "daily", "weekly", "source", "snapshot"):
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


def test_saved_data_commands_require_snapshot_identity() -> None:
    runner = CliRunner()
    assert runner.invoke(main, ["market", "show"]).exit_code == 2
    assert runner.invoke(main, ["market", "security", "XNAS:MSFT"]).exit_code == 2
    assert runner.invoke(main, ["market", "query"]).exit_code == 2
    assert runner.invoke(main, ["research", "build", "XNAS:MSFT"]).exit_code == 2
