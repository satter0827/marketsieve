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


def test_market_configuration_has_complete_zero_key_defaults(tmp_path: Path) -> None:
    defaults = Configuration(None).market_configuration()

    assert defaults.indices == ("dow30", "nasdaq100", "nikkei225", "sp500", "topix500")
    assert defaults.history_days == 1095
    assert defaults.batch_size == 50
    assert defaults.profile_workers == 2
    assert defaults.timeout_seconds == 30
    assert defaults.max_retries == 3
    assert defaults.retry_base_seconds == 2
    assert str(defaults.minimum_overall_price_coverage) == "0.95"
    assert str(defaults.minimum_index_price_coverage) == "0.90"

    path = tmp_path / "market.toml"
    path.write_text(
        "[market]\n"
        'indices = ["sp500", "dow30"]\n'
        "history_days = 400\n"
        "batch_size = 1\n"
        "profile_workers = 1\n"
        "timeout_seconds = 1\n"
        "max_retries = 1\n"
        "retry_base_seconds = 0\n"
        "minimum_overall_price_coverage = 0\n"
        "minimum_index_price_coverage = 1\n",
        encoding="utf-8",
    )
    configured = Configuration(path).market_configuration()
    assert configured.indices == ("dow30", "sp500")
    assert configured.minimum_overall_price_coverage == 0
    assert configured.minimum_index_price_coverage == 1


@pytest.mark.parametrize(
    ("document", "message"),
    (
        ("market = 1\n", "must be a TOML table"),
        ("[market]\nunknown = 1\n", "unsupported settings"),
        ("[market]\nindices = []\n", "unique non-empty"),
        ('[market]\nindices = ["unknown"]\n', "unique non-empty"),
        ('[market]\nindices = ["sp500", "sp500"]\n', "unique non-empty"),
        ("[market]\nhistory_days = true\n", "history_days must be an integer"),
        ("[market]\nbatch_size = 0\n", "batch_size must be an integer"),
        ("[market]\nprofile_workers = 9\n", "profile_workers must be an integer"),
        ("[market]\ntimeout_seconds = 0\n", "timeout_seconds must be an integer"),
        ("[market]\nmax_retries = 0\n", "max_retries must be an integer"),
        ("[market]\nretry_base_seconds = false\n", "retry_base_seconds must be a number"),
        ("[market]\nretry_base_seconds = 61\n", "retry_base_seconds must be a number"),
        (
            '[market]\nminimum_overall_price_coverage = "invalid"\n',
            "must be a decimal ratio",
        ),
        ('[market]\nminimum_overall_price_coverage = "NaN"\n', "finite decimal ratio"),
        ("[market]\nminimum_index_price_coverage = 1.1\n", "must be from 0 through 1"),
    ),
)
def test_market_configuration_rejects_invalid_shapes(
    tmp_path: Path, document: str, message: str
) -> None:
    path = tmp_path / "invalid-market.toml"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        Configuration(path).market_configuration()


def test_research_configuration_has_bounded_zero_key_defaults(tmp_path: Path) -> None:
    defaults = Configuration(None).research_configuration()
    assert defaults.history_days == 3653
    assert defaults.minimum_price_observations == 252
    assert defaults.timeout_seconds == 30
    assert defaults.max_retries == 3
    assert defaults.retry_base_seconds == 2

    path = tmp_path / "research.toml"
    path.write_text(
        "[research]\n"
        "history_days = 3653\n"
        "minimum_price_observations = 5000\n"
        "timeout_seconds = 120\n"
        "max_retries = 10\n"
        "retry_base_seconds = 0\n",
        encoding="utf-8",
    )
    configured = Configuration(path).research_configuration()
    assert configured.history_days == 3653
    assert configured.minimum_price_observations == 5000

    path.write_text("[research]\nhistory_days = 364\n", encoding="utf-8")
    with pytest.raises(ValueError, match="365 through 3653"):
        Configuration(path).research_configuration()

    path.write_text("[research]\nhistory_days = 3654\n", encoding="utf-8")
    with pytest.raises(ValueError, match="365 through 3653"):
        Configuration(path).research_configuration()


def test_universe_source_requires_explicit_operation(tmp_path: Path) -> None:
    path = tmp_path / "source.toml"
    path.write_text(
        "[source_profiles.us]\n"
        'currency = "USD"\n'
        'timezone = "America/New_York"\n'
        "[source_profiles.us.instrument_universe]\n"
        'plugin = "sec"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="operation is required"):
        Configuration(path).source_profile("us")

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
