from pathlib import Path

import pytest
from scripts.configuration_check import validate_daily_configuration

ROOT = Path(__file__).resolve().parents[2]


def test_example_configuration_supports_the_numbered_daily_workflow() -> None:
    validate_daily_configuration(ROOT / "marketsieve.example.toml")


def test_daily_configuration_requires_both_routine_profiles(tmp_path: Path) -> None:
    config = tmp_path / "incomplete.toml"
    document = (ROOT / "marketsieve.example.toml").read_text(encoding="utf-8")
    config.write_text(document.replace("[routines.us]", "[disabled.us]"), encoding="utf-8")

    with pytest.raises(LookupError, match="daily routine 'us'"):
        validate_daily_configuration(config)


def test_daily_configuration_does_not_require_optional_screening(tmp_path: Path) -> None:
    config = tmp_path / "without-screening.toml"
    document = (ROOT / "marketsieve.example.toml").read_text(encoding="utf-8")
    config.write_text(document.split("\n[screening.jp]", maxsplit=1)[0] + "\n", encoding="utf-8")

    validate_daily_configuration(config)


def test_daily_configuration_requires_an_installed_daily_bar_fetcher(tmp_path: Path) -> None:
    config = tmp_path / "unknown-fetcher.toml"
    document = (ROOT / "marketsieve.example.toml").read_text(encoding="utf-8")
    config.write_text(
        document.replace('plugin = "jquants"', 'plugin = "not-installed"', 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not-installed"):
        validate_daily_configuration(config)
