"""Explainable close-versus-SMA20 state-change analysis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from marketsieve._time import as_utc
from marketsieve.analysis.indicators import IndicatorName, IndicatorSpec, IndicatorStatus, calculate
from marketsieve.data.daily import DailyBar, DailyBarSeries

PERIOD = 20
DEFINITION = "arithmetic_mean_of_latest_20_closes"


class AnalysisStatus(StrEnum):
    """Whether the indicator can be evaluated."""

    OK = "ok"
    INSUFFICIENT_HISTORY = "insufficient_history"


class SmaState(StrEnum):
    """The closing price position relative to the SMA."""

    ABOVE = "above"
    BELOW = "below"
    EQUAL = "equal"


@dataclass(frozen=True, slots=True)
class Sma20Result:
    """A deterministic analysis result with stable evidence identity."""

    status: AnalysisStatus
    observation_count: int
    excluded_after_as_of: int
    current_date: date | None
    current_close: Decimal | None
    current_sma: Decimal | None
    current_state: SmaState | None
    previous_state: SmaState | None
    transition: str | None
    evidence_id: str
    period: int = PERIOD
    definition: str = DEFINITION


def state(close: Decimal, average: Decimal) -> SmaState:
    if close > average:
        return SmaState.ABOVE
    if close < average:
        return SmaState.BELOW
    return SmaState.EQUAL


def average(bars: tuple[DailyBar, ...]) -> Decimal:
    result = calculate(IndicatorSpec.create(IndicatorName.SMA, period=PERIOD), bars)
    if result.status is not IndicatorStatus.OK:
        raise ValueError("SMA20 average requires 20 observations")
    return Decimal(dict(result.values)["sma"])


def evidence_payload(series: DailyBarSeries) -> dict[str, Any]:
    return {
        "period": PERIOD,
        "definition": DEFINITION,
        "instrument": {
            "symbol": series.request.instrument.symbol,
            "mic": series.request.instrument.mic,
            "currency": series.request.instrument.currency,
            "timezone": series.request.instrument.exchange_timezone.key,
            "type": series.request.instrument.instrument_type.value,
        },
        "request": {
            "start": series.request.start.isoformat(),
            "end": series.request.end.isoformat(),
            "as_of": as_utc(series.as_of).isoformat(),
            "adjustment": series.request.adjustment.value,
        },
        "excluded_after_as_of": series.excluded_after_as_of,
        "bars": [
            {
                "date": bar.trading_date.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": bar.volume,
                "available_at": as_utc(bar.available_at).isoformat(),
                "provenance": {
                    "source": bar.provenance.source,
                    "dataset": bar.provenance.dataset,
                    "version": bar.provenance.version,
                },
            }
            for bar in series.bars
        ],
    }


def evidence_id(series: DailyBarSeries) -> str:
    encoded = json.dumps(
        evidence_payload(series), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def analyze(series: DailyBarSeries) -> Sma20Result:
    """Evaluate current state and, when possible, the previous-to-current transition."""

    count = len(series.bars)
    identifier = evidence_id(series)
    if count < PERIOD:
        return Sma20Result(
            status=AnalysisStatus.INSUFFICIENT_HISTORY,
            observation_count=count,
            excluded_after_as_of=series.excluded_after_as_of,
            current_date=None,
            current_close=None,
            current_sma=None,
            current_state=None,
            previous_state=None,
            transition=None,
            evidence_id=identifier,
        )
    current_window = series.bars[-PERIOD:]
    current_average = average(current_window)
    current_state = state(series.bars[-1].close, current_average)
    previous_state = None
    transition = None
    if count > PERIOD:
        previous_window = series.bars[-(PERIOD + 1) : -1]
        previous_state = state(series.bars[-2].close, average(previous_window))
        if previous_state != current_state:
            transition = f"{previous_state.value}_to_{current_state.value}"
    return Sma20Result(
        status=AnalysisStatus.OK,
        observation_count=count,
        excluded_after_as_of=series.excluded_after_as_of,
        current_date=series.bars[-1].trading_date,
        current_close=series.bars[-1].close,
        current_sma=current_average,
        current_state=current_state,
        previous_state=previous_state,
        transition=transition,
        evidence_id=identifier,
    )
