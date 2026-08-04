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
        "timeout_seconds = 15\n",
        encoding="utf-8",
    )

    profile = Configuration.resolve(path).source_profile("japan")

    assert profile.daily_bars_plugin == "jquants"
    assert profile.currency == "JPY"
    assert profile.timezone == "Asia/Tokyo"
    assert profile.settings == {"timeout_seconds": "15"}


def test_configuration_does_not_guess_missing_profile(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="not configured"):
        Configuration(None).source_profile("missing")

    path = tmp_path / "invalid.toml"
    path.write_text("[source_profiles.japan]\ndaily_bars = 3\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"daily_bars\.plugin"):
        Configuration(path).source_profile("japan")


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
