from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from marketsieve import EconomicObservation, EconomicSeries


def observation() -> EconomicObservation:
    return EconomicObservation(
        date(2026, 7, 1),
        Decimal("4.25"),
        date(2026, 7, 1),
        date(9999, 12, 31),
    )


def test_economic_series_preserves_revision_validity_and_missing_dates() -> None:
    series = EconomicSeries(
        "DGS10",
        date(2026, 7, 31),
        (observation(),),
        (date(2026, 7, 2),),
    )

    assert series.observations[0].value == Decimal("4.25")
    assert series.missing_observation_dates == (date(2026, 7, 2),)


def test_economic_observation_validation() -> None:
    with pytest.raises(TypeError, match="dates must use"):
        replace(observation(), observation_date="2026-07-01")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite Decimal"):
        replace(observation(), value=Decimal("NaN"))
    with pytest.raises(ValueError, match="start must not exceed"):
        replace(
            observation(),
            realtime_start=date(2026, 8, 1),
            realtime_end=date(2026, 7, 1),
        )


def test_economic_series_rejects_ambiguous_or_time_inconsistent_content() -> None:
    value = observation()
    with pytest.raises(ValueError, match="series ID"):
        EconomicSeries("bad series", date(2026, 7, 31), (value,))
    with pytest.raises(ValueError, match="unique ascending"):
        EconomicSeries("DGS10", date(2026, 7, 31), (value, value))
    with pytest.raises(ValueError, match="also be missing"):
        EconomicSeries("DGS10", date(2026, 7, 31), (value,), (value.observation_date,))
    with pytest.raises(ValueError, match="knowledge date"):
        EconomicSeries("DGS10", date(2026, 6, 30), (value,))
    with pytest.raises(ValueError, match="must contain"):
        EconomicSeries("DGS10", date(2026, 7, 31), ())
    with pytest.raises(TypeError, match="missing economic observation dates"):
        EconomicSeries(
            "DGS10",
            date(2026, 7, 31),
            (),
            ("2026-07-01",),  # type: ignore[arg-type]
        )
