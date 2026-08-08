from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from marketsieve_cli.adapters.config import Settings


def test_settings_are_operational_and_have_stable_defaults() -> None:
    value = Settings.resolve(None)
    runtime = value.runtime()

    assert runtime.yfinance.batch_size == 50
    assert runtime.market_quality.minimum_overall_price_coverage == Decimal("0.95")
    assert len(value.effective_hash()) == 64


def test_settings_reject_analysis_inputs_and_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text('[market]\nindices = ["sp500"]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported tables"):
        Settings.resolve(path).runtime()


def test_settings_validate_ranges(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[yfinance]\nbatch_size = 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="batch_size"):
        Settings.resolve(path).runtime()
