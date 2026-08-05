"""Deterministic technical indicators with an explicit numeric policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from fractions import Fraction
from itertools import pairwise

from marketsieve._time import as_utc
from marketsieve.data.daily import DailyBar

PRECISION = 34
ROUNDING = ROUND_HALF_EVEN
NUMERIC_POLICY = "decimal34-round-half-even-canonical-v1"
CONTEXT = Context(prec=PRECISION, rounding=ROUNDING)


class IndicatorName(StrEnum):
    """Implemented indicator catalog."""

    SMA = "sma"
    EMA = "ema"
    RSI = "rsi"
    MACD = "macd"
    ATR = "atr"
    PERIOD_RETURN = "period_return"
    MAX_DRAWDOWN = "maximum_drawdown"


class IndicatorStatus(StrEnum):
    """Whether an indicator produced a value."""

    OK = "ok"
    INSUFFICIENT_HISTORY = "insufficient_history"


DEFINITIONS = {
    IndicatorName.SMA: "sma.close.fraction-mean.output-decimal34.v1",
    IndicatorName.EMA: "ema.close.sma-seed.alpha-2-over-n-plus-1.decimal34.v1",
    IndicatorName.RSI: "rsi.close.wilder-sma-seed.flat-50.decimal34.v1",
    IndicatorName.MACD: "macd.close.ema-sma-seed.signal-ema.decimal34.v1",
    IndicatorName.ATR: "atr.ohlc.previous-close.wilder-sma-seed.decimal34.v1",
    IndicatorName.PERIOD_RETURN: "period-return.close.simple-decimal34.v1",
    IndicatorName.MAX_DRAWDOWN: "maximum-drawdown.close.peak-relative-decimal34.v1",
}


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """Indicator identity and integer parameters."""

    name: IndicatorName
    parameters: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, IndicatorName):
            raise TypeError("indicator name must be IndicatorName")
        names = tuple(name for name, _ in self.parameters)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("indicator parameters must be unique and sorted by name")
        if any(
            not name or not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for name, value in self.parameters
        ):
            raise ValueError("indicator parameters must be positive integers")

    @classmethod
    def create(cls, name: IndicatorName | str, **parameters: int) -> IndicatorSpec:
        """Create a canonical parameter ordering."""

        return cls(IndicatorName(name), tuple(sorted(parameters.items())))

    def parameter(self, name: str) -> int:
        try:
            return dict(self.parameters)[name]
        except KeyError as error:
            raise ValueError(f"indicator requires parameter {name}") from error


@dataclass(frozen=True, slots=True)
class IndicatorResult:
    """Generic deterministic indicator result."""

    name: IndicatorName
    definition_version: str
    parameters: tuple[tuple[str, int], ...]
    status: IndicatorStatus
    as_of: datetime | None
    values: tuple[tuple[str, str], ...]
    observation_count: int
    numeric_policy: str
    evidence_id: str

    def __post_init__(self) -> None:
        IndicatorSpec(self.name, self.parameters)
        if not self.definition_version:
            raise ValueError("indicator definition version must not be empty")
        if not isinstance(self.status, IndicatorStatus):
            raise TypeError("indicator status must be IndicatorStatus")
        if self.as_of is not None and (self.as_of.tzinfo is None or self.as_of.utcoffset() is None):
            raise ValueError("indicator as_of must include a UTC offset")
        value_names = tuple(name for name, _ in self.values)
        if len(value_names) != len(set(value_names)) or any(not name for name in value_names):
            raise ValueError("indicator value names must be unique and non-empty")
        if self.status is IndicatorStatus.INSUFFICIENT_HISTORY and self.values:
            raise ValueError("insufficient-history result must not include values")
        if self.status is IndicatorStatus.OK and not self.values:
            raise ValueError("successful indicator result requires values")
        if any(canonical_decimal(Decimal(value)) != value for _, value in self.values):
            raise ValueError("indicator values must be canonical decimal strings")
        if self.observation_count < 0:
            raise ValueError("indicator observation count must be non-negative")
        if self.numeric_policy != NUMERIC_POLICY:
            raise ValueError("indicator numeric policy is unsupported")
        if len(self.evidence_id) != 64 or any(
            character not in "0123456789abcdef" for character in self.evidence_id
        ):
            raise ValueError("indicator evidence ID must be a lowercase SHA-256 digest")


def canonical_decimal(value: Decimal) -> str:
    """Render a finite Decimal without exponent notation or redundant zeros."""

    if not value.is_finite():
        raise ValueError("indicator output must be finite")
    if value == 0:
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _validate_bars(bars: tuple[DailyBar, ...]) -> None:
    dates = tuple(bar.trading_date for bar in bars)
    if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
        raise ValueError("indicator input bars must have unique ascending dates")


def _exact_mean(values: tuple[Decimal, ...]) -> Decimal:
    exact = sum((Fraction(value) for value in values), start=Fraction()) / len(values)
    with localcontext(CONTEXT):
        return Decimal(exact.numerator) / Decimal(exact.denominator)


def _ema(values: tuple[Decimal, ...], period: int) -> tuple[Decimal, ...]:
    if len(values) < period:
        return ()
    with localcontext(CONTEXT):
        alpha = Decimal(2) / Decimal(period + 1)
        current = sum(values[:period], start=Decimal(0)) / Decimal(period)
        output = [current]
        for value in values[period:]:
            current = (value - current) * alpha + current
            output.append(current)
        return tuple(output)


def _wilder(values: tuple[Decimal, ...], period: int) -> Decimal:
    with localcontext(CONTEXT):
        current = sum(values[:period], start=Decimal(0)) / Decimal(period)
        for value in values[period:]:
            current = (current * Decimal(period - 1) + value) / Decimal(period)
        return current


def _required_parameters(spec: IndicatorSpec, names: tuple[str, ...]) -> tuple[int, ...]:
    if tuple(name for name, _ in spec.parameters) != tuple(sorted(names)):
        expected = ", ".join(names)
        raise ValueError(f"{spec.name.value} parameters must be exactly: {expected}")
    return tuple(spec.parameter(name) for name in names)


def _calculate_values(
    spec: IndicatorSpec, bars: tuple[DailyBar, ...]
) -> tuple[IndicatorStatus, tuple[tuple[str, Decimal], ...]]:
    closes = tuple(bar.close for bar in bars)
    if spec.name is IndicatorName.MACD:
        fast, signal, slow = _required_parameters(
            spec, ("fast_period", "signal_period", "slow_period")
        )
        if fast >= slow:
            raise ValueError("macd fast_period must be less than slow_period")
        required = slow + signal - 1
        if len(closes) < required:
            return IndicatorStatus.INSUFFICIENT_HISTORY, ()
        fast_values = _ema(closes, fast)
        slow_values = _ema(closes, slow)
        aligned_fast = fast_values[slow - fast :]
        with localcontext(CONTEXT):
            macd_values = tuple(
                fast_value - slow_value
                for fast_value, slow_value in zip(aligned_fast, slow_values, strict=True)
            )
            signal_value = _ema(macd_values, signal)[-1]
            macd_value = macd_values[-1]
            return IndicatorStatus.OK, (
                ("macd", macd_value),
                ("signal", signal_value),
                ("histogram", macd_value - signal_value),
            )

    (period,) = _required_parameters(spec, ("period",))
    if spec.name is IndicatorName.SMA:
        if len(closes) < period:
            return IndicatorStatus.INSUFFICIENT_HISTORY, ()
        return IndicatorStatus.OK, (("sma", _exact_mean(closes[-period:])),)
    if spec.name is IndicatorName.EMA:
        values = _ema(closes, period)
        return (
            (IndicatorStatus.OK, (("ema", values[-1]),))
            if values
            else (IndicatorStatus.INSUFFICIENT_HISTORY, ())
        )
    if spec.name is IndicatorName.RSI:
        if len(closes) < period + 1:
            return IndicatorStatus.INSUFFICIENT_HISTORY, ()
        with localcontext(CONTEXT):
            changes = tuple(current - previous for previous, current in pairwise(closes))
            gains = tuple(max(change, Decimal(0)) for change in changes)
            losses = tuple(max(-change, Decimal(0)) for change in changes)
            average_gain = _wilder(gains, period)
            average_loss = _wilder(losses, period)
            if average_gain == 0 and average_loss == 0:
                value = Decimal(50)
            elif average_loss == 0:
                value = Decimal(100)
            else:
                value = Decimal(100) - Decimal(100) / (Decimal(1) + average_gain / average_loss)
            return IndicatorStatus.OK, (("rsi", value),)
    if spec.name is IndicatorName.ATR:
        if len(bars) < period:
            return IndicatorStatus.INSUFFICIENT_HISTORY, ()
        with localcontext(CONTEXT):
            true_ranges = []
            for index, bar in enumerate(bars):
                candidates = [bar.high - bar.low]
                if index:
                    previous_close = bars[index - 1].close
                    candidates.extend(
                        (abs(bar.high - previous_close), abs(bar.low - previous_close))
                    )
                true_ranges.append(max(candidates))
            return IndicatorStatus.OK, (("atr", _wilder(tuple(true_ranges), period)),)
    if spec.name is IndicatorName.PERIOD_RETURN:
        if len(closes) < period + 1:
            return IndicatorStatus.INSUFFICIENT_HISTORY, ()
        with localcontext(CONTEXT):
            value = closes[-1] / closes[-(period + 1)] - Decimal(1)
            return IndicatorStatus.OK, (("return", value),)
    if spec.name is IndicatorName.MAX_DRAWDOWN:
        if len(closes) < period:
            return IndicatorStatus.INSUFFICIENT_HISTORY, ()
        with localcontext(CONTEXT):
            peak = closes[-period]
            drawdown = Decimal(0)
            for close in closes[-period:]:
                peak = max(peak, close)
                drawdown = min(drawdown, close / peak - Decimal(1))
            return IndicatorStatus.OK, (("maximum_drawdown", drawdown),)
    raise ValueError(f"unsupported indicator: {spec.name}")


def calculate(spec: IndicatorSpec, bars: tuple[DailyBar, ...]) -> IndicatorResult:
    """Calculate one indicator without using ambient Decimal context."""

    _validate_bars(bars)
    status, decimal_values = _calculate_values(spec, bars)
    values = tuple((name, canonical_decimal(value)) for name, value in decimal_values)
    as_of = bars[-1].available_at if bars else None
    payload = {
        "name": spec.name.value,
        "definition_version": DEFINITIONS[spec.name],
        "parameters": dict(spec.parameters),
        "status": status.value,
        "as_of": as_utc(as_of).isoformat() if as_of is not None else None,
        "values": dict(values),
        "observation_count": len(bars),
        "numeric_policy": NUMERIC_POLICY,
        "bars": [
            {
                "date": bar.trading_date.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": bar.volume,
                "adjustment": bar.adjustment.value,
                "available_at": as_utc(bar.available_at).isoformat(),
                "provenance": (
                    bar.provenance.source,
                    bar.provenance.dataset,
                    bar.provenance.version,
                ),
            }
            for bar in bars
        ],
    }
    evidence_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return IndicatorResult(
        spec.name,
        DEFINITIONS[spec.name],
        spec.parameters,
        status,
        as_of,
        values,
        len(bars),
        NUMERIC_POLICY,
        evidence_id,
    )
