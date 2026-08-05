"""Provider-independent economic series observations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

SERIES_ID = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class EconomicObservation:
    """One value and the real-time interval in which that revision is valid."""

    observation_date: date
    value: Decimal
    realtime_start: date
    realtime_end: date

    def __post_init__(self) -> None:
        if any(
            type(value) is not date
            for value in (self.observation_date, self.realtime_start, self.realtime_end)
        ):
            raise TypeError("economic observation dates must use datetime.date")
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValueError("economic observation value must be a finite Decimal")
        if self.realtime_start > self.realtime_end:
            raise ValueError("economic observation real-time start must not exceed end")


@dataclass(frozen=True, slots=True)
class EconomicSeries:
    """Values for one series as known on one explicit knowledge date."""

    series_id: str
    knowledge_date: date
    observations: tuple[EconomicObservation, ...]
    missing_observation_dates: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.series_id, str) or SERIES_ID.fullmatch(self.series_id) is None:
            raise ValueError(
                "economic series ID must use letters, digits, dot, underscore, or hyphen"
            )
        if type(self.knowledge_date) is not date:
            raise TypeError("economic series knowledge date must use datetime.date")
        if any(not isinstance(value, EconomicObservation) for value in self.observations):
            raise TypeError("economic series observations must use EconomicObservation")
        if any(type(value) is not date for value in self.missing_observation_dates):
            raise TypeError("missing economic observation dates must use datetime.date")
        dates = tuple(value.observation_date for value in self.observations)
        if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("economic observations must have unique ascending dates")
        if self.missing_observation_dates != tuple(sorted(self.missing_observation_dates)) or len(
            self.missing_observation_dates
        ) != len(set(self.missing_observation_dates)):
            raise ValueError("missing economic observation dates must be unique and ascending")
        if set(dates) & set(self.missing_observation_dates):
            raise ValueError("economic observation dates cannot also be missing")
        if any(
            not value.realtime_start <= self.knowledge_date <= value.realtime_end
            for value in self.observations
        ):
            raise ValueError("economic observations must be valid on the series knowledge date")
        if not self.observations and not self.missing_observation_dates:
            raise ValueError("economic series must contain an observation or explicit missing date")
