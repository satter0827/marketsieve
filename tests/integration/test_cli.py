from click.testing import CliRunner

from marketsieve import __version__
from marketsieve_app.interfaces.cli import main


def test_version_reports_sdk_version() -> None:
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"marketsieve, version {__version__}\n"


def test_doctor_reports_ready() -> None:
    result = CliRunner().invoke(main, ["doctor"])

    assert result.exit_code == 0
    assert "[ok] MarketSieve SDK" in result.output
    assert result.output.endswith("Status: ready\n")
