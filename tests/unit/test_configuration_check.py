from pathlib import Path

import pytest
from scripts.configuration_check import daily_source_diagnostics, validate_daily_configuration

ROOT = Path(__file__).resolve().parents[2]


def test_example_configuration_supports_the_numbered_daily_workflow() -> None:
    validate_daily_configuration(ROOT / "marketsieve.example.toml")


def test_daily_source_diagnostics_preserve_configured_provider_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    diagnostics = daily_source_diagnostics(ROOT / "marketsieve.example.toml")

    assert diagnostics["jp"].code == "missing_credential"
    assert "JQUANTS_API_KEY" in diagnostics["jp"].message
    assert diagnostics["us"].code == "missing_credential"
    assert "ALPHAVANTAGE_API_KEY" in diagnostics["us"].message


def test_daily_configuration_requires_both_routine_profiles(tmp_path: Path) -> None:
    config = tmp_path / "incomplete.toml"
    document = (ROOT / "marketsieve.example.toml").read_text(encoding="utf-8")
    config.write_text(document.replace("[routines.us]", "[disabled.us]"), encoding="utf-8")

    with pytest.raises(LookupError, match="daily routine 'us'"):
        validate_daily_configuration(config)


def test_daily_configuration_rejects_a_profile_assigned_to_the_wrong_market(
    tmp_path: Path,
) -> None:
    config = tmp_path / "swapped.toml"
    document = (ROOT / "marketsieve.example.toml").read_text(encoding="utf-8")
    config.write_text(
        document.replace(
            '[routines.jp]\nsource_profile = "japan"',
            '[routines.jp]\nsource_profile = "us"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires JPY and Asia/Tokyo"):
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


def test_daily_configuration_rejects_provider_settings_before_network_use(
    tmp_path: Path,
) -> None:
    config = tmp_path / "invalid-provider-settings.toml"
    document = (ROOT / "marketsieve.example.toml").read_text(encoding="utf-8")
    config.write_text(document.replace('plan = "free"', 'plan = "bogus"'), encoding="utf-8")

    with pytest.raises(ValueError, match="plan must be free or premium"):
        validate_daily_configuration(config)


def test_daily_configuration_validates_configured_event_sources(tmp_path: Path) -> None:
    config = tmp_path / "invalid-events.toml"
    document = (ROOT / "marketsieve.example.toml").read_text(encoding="utf-8")
    config.write_text(
        document.replace('event_types = "earnings,dividend,split"', 'event_types = "bogus"'),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="event_types must select"):
        validate_daily_configuration(config)


def test_daily_configuration_rejects_malformed_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "invalid\nvalue")

    with pytest.raises(ValueError, match="invalid URL characters"):
        validate_daily_configuration(ROOT / "marketsieve.example.toml")
