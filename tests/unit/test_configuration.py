from __future__ import annotations

from pathlib import Path

import pytest

from marketsieve_cli.adapters.config import Configuration


def test_explicit_configuration_resolves_one_exact_profile(tmp_path: Path) -> None:
    path = tmp_path / "custom.toml"
    path.write_text(
        "[source_profiles.japan]\n"
        'currency = "JPY"\n'
        'timezone = "Asia/Tokyo"\n'
        "[source_profiles.japan.daily_bars]\n"
        'plugin = "jquants"\n'
        "[source_profiles.japan.daily_bars.settings]\n"
        "timeout_seconds = 15\n"
        "[source_profiles.japan.financials]\n"
        'plugin = "jquants"\n'
        "[source_profiles.japan.events]\n"
        'plugin = "jquants"\n'
        "[source_profiles.japan.events.settings]\n"
        'event_types = "earnings,dividend"\n',
        encoding="utf-8",
    )

    profile = Configuration.resolve(path).source_profile("japan")

    assert profile.daily_bars_plugin == "jquants"
    assert profile.currency == "JPY"
    assert profile.timezone == "Asia/Tokyo"
    assert profile.settings == {"timeout_seconds": "15"}
    assert profile.binding("financials").plugin == "jquants"
    assert profile.binding("events").settings == {"event_types": "earnings,dividend"}
    with pytest.raises(LookupError, match="does not configure"):
        profile.binding("news")


def test_configuration_does_not_guess_missing_profile(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="not configured"):
        Configuration(None).source_profile("missing")

    path = tmp_path / "invalid.toml"
    path.write_text(
        '[source_profiles.japan]\ncurrency = "JPY"\ntimezone = "Asia/Tokyo"\ndaily_bars = 3\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"daily_bars\.plugin"):
        Configuration(path).source_profile("japan")


def test_configuration_allows_a_fact_only_profile(tmp_path: Path) -> None:
    path = tmp_path / "facts.toml"
    path.write_text(
        "[source_profiles.facts]\n"
        'currency = "JPY"\n'
        'timezone = "Asia/Tokyo"\n'
        "[source_profiles.facts.financials]\n"
        'plugin = "jquants"\n',
        encoding="utf-8",
    )

    profile = Configuration(path).source_profile("facts")

    assert profile.binding("financials").plugin == "jquants"
    with pytest.raises(LookupError, match="daily_bars"):
        profile.binding("daily_bars")


def test_agent_provider_configuration_is_non_secret_and_explicit(tmp_path: Path) -> None:
    path = tmp_path / "agent.toml"
    path.write_text(
        "[agent.providers.lmstudio]\n"
        'model = "local-model"\n'
        'endpoint = "http://127.0.0.1:1234/v1"\n'
        "[agent.providers.openai]\n"
        'model = "cloud-model"\n',
        encoding="utf-8",
    )

    configuration = Configuration(path)

    assert configuration.agent_provider("lmstudio").endpoint == "http://127.0.0.1:1234/v1"
    assert configuration.agent_provider("openai").model == "cloud-model"
    with pytest.raises(LookupError, match="not configured"):
        configuration.agent_provider("google")


def test_agent_provider_rejects_secret_or_unknown_configuration(tmp_path: Path) -> None:
    path = tmp_path / "agent-invalid.toml"
    path.write_text(
        '[agent.providers.openai]\nmodel = "cloud-model"\nunexpected = "forbidden"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported settings"):
        Configuration(path).agent_provider("openai")


def test_daily_routine_configuration_is_explicit_and_bounded(tmp_path: Path) -> None:
    path = tmp_path / "routine.toml"
    path.write_text(
        '[routines.jp]\nsource_profile = "japan"\nlookback_days = 500\n'
        '[routines.us]\nsource_profile = "united-states"\n',
        encoding="utf-8",
    )
    configuration = Configuration(path)

    assert configuration.daily_profile("jp") == ("japan", 500, 1500)
    assert configuration.daily_profile("us") == ("united-states", 400, 1500)

    invalid = tmp_path / "invalid-routine.toml"
    invalid.write_text('[routines.jp]\nsource_profile = "japan"\nlookback_days = 59\n')
    with pytest.raises(ValueError, match="60 through 2000"):
        Configuration(invalid).daily_profile("jp")

    invalid.write_text('[routines.jp]\nsource_profile = "japan"\nfinancial_lookback_days = 364\n')
    with pytest.raises(ValueError, match="365 through 4000"):
        Configuration(invalid).daily_profile("jp")


def test_daily_routine_configuration_never_guesses_a_profile() -> None:
    with pytest.raises(LookupError, match="not configured"):
        Configuration(None).daily_profile("jp")


def test_weekly_routine_age_has_a_low_burden_default_and_bounds(tmp_path: Path) -> None:
    assert Configuration(None).weekly_max_age_days() == 7

    path = tmp_path / "weekly.toml"
    path.write_text("[routines.weekly]\nmax_age_days = 5\n", encoding="utf-8")
    assert Configuration(path).weekly_max_age_days() == 5

    path.write_text("[routines.weekly]\nmax_age_days = 15\n", encoding="utf-8")
    with pytest.raises(ValueError, match="1 through 14"):
        Configuration(path).weekly_max_age_days()

    path.write_text("routines = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="routines configuration"):
        Configuration(path).weekly_max_age_days()

    path.write_text('routines.weekly = "invalid"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="TOML table"):
        Configuration(path).weekly_max_age_days()

    path.write_text('[routines.weekly]\nunknown = "invalid"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported settings"):
        Configuration(path).weekly_max_age_days()


def test_explicit_configuration_rejects_missing_invalid_and_secret_like_shapes(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.toml"
    missing_configuration = Configuration.resolve(missing)
    with pytest.raises(ValueError, match="does not exist"):
        missing_configuration.source_profile("japan")

    invalid = tmp_path / "invalid-syntax.toml"
    invalid.write_text("[broken", encoding="utf-8")
    configuration = Configuration(invalid)
    with pytest.raises(ValueError, match="could not be read"):
        configuration.source_profile("japan")

    incomplete = tmp_path / "incomplete.toml"
    incomplete.write_text(
        '[source_profiles.japan.daily_bars]\nplugin = "jquants"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="currency and timezone"):
        Configuration(incomplete).source_profile("japan")

    invalid_settings = tmp_path / "invalid-settings.toml"
    invalid_settings.write_text(
        "[source_profiles.japan]\n"
        'currency = "JPY"\n'
        'timezone = "Asia/Tokyo"\n'
        "[source_profiles.japan.daily_bars]\n"
        'plugin = "jquants"\n'
        "settings = { nested = { value = 1 } }\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="scalar values"):
        Configuration(invalid_settings).source_profile("japan")
