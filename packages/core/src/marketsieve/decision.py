"""Deterministic medium-term investment decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable

from marketsieve._time import as_utc
from marketsieve.analysis.indicators import (
    CONTEXT,
    IndicatorName,
    IndicatorResult,
    IndicatorSpec,
    IndicatorStatus,
    calculate,
    canonical_decimal,
)
from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument
from marketsieve.portfolio import Holding, PersonalInvestmentContext, PortfolioSnapshot


class MarketSession(StrEnum):
    JP_CLOSE = "jp_close"
    US_CLOSE = "us_close"
    WEEKLY = "weekly"


class DecisionAction(StrEnum):
    BUY_CANDIDATE = "buy_candidate"
    WAIT_FOR_PULLBACK = "wait_for_pullback"
    WAIT_FOR_EARNINGS = "wait_for_earnings"
    PASS = "pass"
    KEEP = "keep"
    WATCH = "watch"
    REDUCE_REVIEW = "reduce_review"
    SELL_REVIEW = "sell_review"
    INDETERMINATE = "indeterminate"


class DecisionConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceDirection(StrEnum):
    SUPPORTING = "supporting"
    OPPOSING = "opposing"
    LIMITATION = "limitation"


HELD_ACTIONS = {
    DecisionAction.KEEP,
    DecisionAction.WATCH,
    DecisionAction.REDUCE_REVIEW,
    DecisionAction.SELL_REVIEW,
    DecisionAction.INDETERMINATE,
}
UNHELD_ACTIONS = {
    DecisionAction.BUY_CANDIDATE,
    DecisionAction.WAIT_FOR_PULLBACK,
    DecisionAction.WAIT_FOR_EARNINGS,
    DecisionAction.PASS,
    DecisionAction.INDETERMINATE,
}


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """One stable reason contributing to or limiting a decision."""

    code: str
    direction: EvidenceDirection
    value: str | None
    threshold: str | None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", self.code) is None:
            raise ValueError("decision evidence code must be non-empty snake case")
        if not isinstance(self.direction, EvidenceDirection):
            raise TypeError("decision evidence direction must be EvidenceDirection")
        if self.value is not None and not self.value:
            raise ValueError("decision evidence value must be non-empty when present")
        if self.threshold is not None and not self.threshold:
            raise ValueError("decision evidence threshold must be non-empty when present")
        if any(not value for value in self.evidence_ids) or len(set(self.evidence_ids)) != len(
            self.evidence_ids
        ):
            raise ValueError("decision evidence IDs must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """Validated facts available to a policy for one instrument."""

    instrument: Instrument
    as_of: datetime
    bars: tuple[DailyBar, ...]
    personal: PersonalInvestmentContext = field(default_factory=PersonalInvestmentContext)
    holding: Holding | None = None
    position_weight: Decimal | None = None
    next_earnings_date: date | None = None
    revenue_growth: Decimal | None = None
    eps_growth: Decimal | None = None
    free_cash_flow: Decimal | None = None
    valuation: tuple[tuple[str, str], ...] = ()
    input_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("analysis instrument must be Instrument")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("analysis as_of must include a UTC offset")
        dates = tuple(bar.trading_date for bar in self.bars)
        if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("analysis bars must have unique ascending dates")
        if any(as_utc(bar.available_at) > as_utc(self.as_of) for bar in self.bars):
            raise ValueError("analysis bars must be available at as_of")
        if not isinstance(self.personal, PersonalInvestmentContext):
            raise TypeError("analysis personal context must be PersonalInvestmentContext")
        if self.holding is not None and self.holding.instrument != self.instrument:
            raise ValueError("analysis holding must match the instrument")
        if self.position_weight is not None:
            _bounded_decimal(
                self.position_weight,
                "position weight",
                minimum=Decimal(0),
                maximum=Decimal(1),
            )
            if self.holding is None:
                raise ValueError("position weight requires a holding")
        for name, value in (
            ("revenue growth", self.revenue_growth),
            ("EPS growth", self.eps_growth),
            ("free cash flow", self.free_cash_flow),
        ):
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise ValueError(f"{name} must be a finite Decimal when present")
        if self.next_earnings_date is not None and type(self.next_earnings_date) is not date:
            raise TypeError("next earnings date must be datetime.date")
        valuation_names = tuple(name for name, _ in self.valuation)
        if (
            valuation_names != tuple(sorted(valuation_names))
            or len(valuation_names) != len(set(valuation_names))
            or any(not name or not value for name, value in self.valuation)
        ):
            raise ValueError("valuation values must have unique sorted non-empty names")
        if any(not value for value in self.input_evidence_ids) or len(
            set(self.input_evidence_ids)
        ) != len(self.input_evidence_ids):
            raise ValueError("analysis input evidence IDs must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class InstrumentDecision:
    instrument: Instrument
    held: bool
    action: DecisionAction
    confidence: DecisionConfidence
    evidence: tuple[DecisionEvidence, ...]
    next_earnings_date: date | None
    revenue_growth: Decimal | None
    eps_growth: Decimal | None
    free_cash_flow: Decimal | None
    valuation: tuple[tuple[str, str], ...]
    invalidation_conditions: tuple[str, ...]
    next_action: str
    policy_name: str
    policy_version: str
    policy_settings: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("decision instrument must be Instrument")
        if not isinstance(self.held, bool):
            raise TypeError("decision held state must be bool")
        if not isinstance(self.action, DecisionAction):
            raise TypeError("decision action must be DecisionAction")
        if self.action not in (HELD_ACTIONS if self.held else UNHELD_ACTIONS):
            raise ValueError("decision action does not match holding state")
        if not isinstance(self.confidence, DecisionConfidence):
            raise TypeError("decision confidence must be DecisionConfidence")
        if any(not isinstance(item, DecisionEvidence) for item in self.evidence):
            raise TypeError("decision evidence must use DecisionEvidence")
        if self.next_earnings_date is not None and type(self.next_earnings_date) is not date:
            raise TypeError("decision next earnings date must be datetime.date")
        for value in (self.revenue_growth, self.eps_growth, self.free_cash_flow):
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise ValueError("decision financial values must be finite Decimals")
        if not self.next_action or not self.policy_name or not self.policy_version:
            raise ValueError("decision action and policy identity must not be empty")
        if any(not value for value in self.invalidation_conditions):
            raise ValueError("invalidation conditions must not be empty")
        names = tuple(name for name, _ in self.policy_settings)
        if (
            names != tuple(sorted(names))
            or len(names) != len(set(names))
            or any(not name or not value for name, value in self.policy_settings)
        ):
            raise ValueError("policy settings must be unique and sorted")
        valuation_names = tuple(name for name, _ in self.valuation)
        if (
            valuation_names != tuple(sorted(valuation_names))
            or len(valuation_names) != len(set(valuation_names))
            or any(not name or not value for name, value in self.valuation)
        ):
            raise ValueError("decision valuation values must be unique and sorted")


@dataclass(frozen=True, slots=True)
class DecisionReport:
    """Immutable semantic report model; storage and projections live outside the SDK."""

    report_id: str
    schema_version: str
    session: MarketSession
    as_of: datetime
    portfolio: PortfolioSnapshot
    policy_name: str
    policy_version: str
    policy_settings: tuple[tuple[str, str], ...]
    decisions: tuple[InstrumentDecision, ...]
    diagnostics: tuple[str, ...] = ()
    previous_report_id: str | None = None

    def __post_init__(self) -> None:
        if len(self.report_id) != 64 or any(c not in "0123456789abcdef" for c in self.report_id):
            raise ValueError("report ID must be a lowercase SHA-256 digest")
        if self.schema_version != "decision-report/v1":
            raise ValueError("unsupported decision report schema")
        if not isinstance(self.session, MarketSession):
            raise TypeError("report session must be MarketSession")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("report as_of must include a UTC offset")
        if not isinstance(self.portfolio, PortfolioSnapshot):
            raise TypeError("report portfolio must be PortfolioSnapshot")
        if as_utc(self.portfolio.as_of) > as_utc(self.as_of):
            raise ValueError("report must not predate its portfolio snapshot")
        if not self.policy_name or not self.policy_version:
            raise ValueError("report policy identity must not be empty")
        setting_names = tuple(name for name, _ in self.policy_settings)
        if (
            setting_names != tuple(sorted(setting_names))
            or len(setting_names) != len(set(setting_names))
            or any(not name or not value for name, value in self.policy_settings)
        ):
            raise ValueError("report policy settings must be unique and sorted")
        if any(not isinstance(item, InstrumentDecision) for item in self.decisions):
            raise TypeError("report decisions must use InstrumentDecision")
        identities = tuple((item.instrument.mic, item.instrument.symbol) for item in self.decisions)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("report decisions must have unique sorted instruments")
        portfolio_identities = {
            (item.instrument.mic, item.instrument.symbol) for item in self.portfolio.holdings
        } | {(item.instrument.mic, item.instrument.symbol) for item in self.portfolio.watch_items}
        if set(identities) != portfolio_identities:
            raise ValueError("report decisions must match the portfolio instruments")
        if any(
            (item.policy_name, item.policy_version, item.policy_settings)
            != (self.policy_name, self.policy_version, self.policy_settings)
            for item in self.decisions
        ):
            raise ValueError("report decisions must use the report policy")
        if any(not value for value in self.diagnostics) or len(set(self.diagnostics)) != len(
            self.diagnostics
        ):
            raise ValueError("report diagnostics must be non-empty and unique")
        if self.previous_report_id is not None and (
            len(self.previous_report_id) != 64
            or any(c not in "0123456789abcdef" for c in self.previous_report_id)
        ):
            raise ValueError("previous report ID must be a lowercase SHA-256 digest")


@runtime_checkable
class DecisionPolicy(Protocol):
    name: str
    version: str

    @property
    def settings(self) -> tuple[tuple[str, str], ...]: ...

    def evaluate(self, context: AnalysisContext) -> InstrumentDecision: ...


@dataclass(frozen=True, slots=True)
class BalancedMediumTermPolicy:
    """One transparent policy for routine medium-term review."""

    name = "balanced_medium_term"
    version = "1.0.0"
    rsi_overbought: Decimal = Decimal("70")
    rsi_oversold: Decimal = Decimal("30")
    atr_close_warning: Decimal = Decimal("0.04")
    drawdown_warning: Decimal = Decimal("-0.20")
    earnings_wait_days: int = 7

    def __post_init__(self) -> None:
        _bounded_decimal(
            self.rsi_oversold, "RSI oversold", minimum=Decimal(0), maximum=Decimal(100)
        )
        _bounded_decimal(
            self.rsi_overbought, "RSI overbought", minimum=Decimal(0), maximum=Decimal(100)
        )
        if self.rsi_oversold >= self.rsi_overbought:
            raise ValueError("RSI oversold must be below overbought")
        _bounded_decimal(
            self.atr_close_warning,
            "ATR warning",
            minimum=Decimal(0),
            maximum=Decimal(1),
        )
        _bounded_decimal(
            self.drawdown_warning,
            "drawdown warning",
            minimum=Decimal(-1),
            maximum=Decimal(0),
        )
        if not isinstance(self.earnings_wait_days, int) or isinstance(
            self.earnings_wait_days, bool
        ):
            raise TypeError("earnings wait days must be an integer")
        if self.earnings_wait_days < 0:
            raise ValueError("earnings wait days must be non-negative")

    @property
    def settings(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (
                    ("atr_close_warning", canonical_decimal(self.atr_close_warning)),
                    ("drawdown_warning", canonical_decimal(self.drawdown_warning)),
                    ("earnings_wait_days", str(self.earnings_wait_days)),
                    ("rsi_overbought", canonical_decimal(self.rsi_overbought)),
                    ("rsi_oversold", canonical_decimal(self.rsi_oversold)),
                )
            )
        )

    def evaluate(self, context: AnalysisContext) -> InstrumentDecision:
        results = _indicator_results(context.bars)
        missing = tuple(
            (name, results[name])
            for name in _ESSENTIAL_INDICATORS
            if results[name].status is IndicatorStatus.INSUFFICIENT_HISTORY
        )
        held = context.holding is not None
        if missing:
            evidence = tuple(
                DecisionEvidence(
                    f"missing_{name.value if isinstance(name, IndicatorName) else name}",
                    EvidenceDirection.LIMITATION,
                    str(result.observation_count),
                    "required_history",
                    (result.evidence_id,),
                )
                for name, result in missing
            )
            return self._decision(
                context,
                DecisionAction.INDETERMINATE,
                DecisionConfidence.LOW,
                evidence,
                ("sufficient_price_history",),
                "refresh_price_history",
            )

        values = {name: _values(result) for name, result in results.items()}
        close = context.bars[-1].close
        sma20 = values[IndicatorName.SMA]["sma"]
        sma60 = values[_SMA60]["sma"]
        rsi = values[IndicatorName.RSI]["rsi"]
        histogram = values[IndicatorName.MACD]["histogram"]
        atr = values[IndicatorName.ATR]["atr"]
        period_return = values[IndicatorName.PERIOD_RETURN]["return"]
        drawdown_result = results[IndicatorName.MAX_DRAWDOWN]
        drawdown = (
            values[IndicatorName.MAX_DRAWDOWN]["maximum_drawdown"]
            if drawdown_result.status is IndicatorStatus.OK
            else None
        )
        with localcontext(CONTEXT):
            atr_ratio = atr / close
        bullish = close > sma20 > sma60 and histogram > 0 and period_return > 0
        bearish = close < sma20 < sma60 and histogram < 0 and period_return < 0
        overbought = rsi >= self.rsi_overbought
        oversold = rsi <= self.rsi_oversold
        high_volatility = atr_ratio >= self.atr_close_warning
        deep_drawdown = drawdown is not None and drawdown <= self.drawdown_warning
        negatives = sum(
            value is not None and value < 0
            for value in (context.revenue_growth, context.eps_growth, context.free_cash_flow)
        )
        financial_deterioration = negatives >= 2
        concentrated = (
            context.position_weight is not None
            and context.position_weight > context.personal.maximum_position_weight
        )
        earnings_wait = _earnings_wait(context, self.earnings_wait_days)
        evidence = _decision_evidence(
            context,
            results,
            bullish_trend=bullish,
            bearish_trend=bearish,
            positive_20d_return=period_return > 0,
            negative_20d_return=period_return < 0,
            overbought=overbought,
            oversold=oversold,
            high_volatility=high_volatility,
            deep_drawdown=deep_drawdown,
            financial_deterioration=financial_deterioration,
            concentrated=concentrated,
            earnings_wait=earnings_wait,
            atr_ratio=atr_ratio,
            drawdown=drawdown,
            rsi_overbought_threshold=self.rsi_overbought,
            rsi_oversold_threshold=self.rsi_oversold,
            atr_warning_threshold=self.atr_close_warning,
            drawdown_warning_threshold=self.drawdown_warning,
            concentration_threshold=context.personal.maximum_position_weight,
            earnings_wait_threshold=self.earnings_wait_days,
        )
        confidence = _confidence(context, drawdown_result)
        if held:
            if financial_deterioration and bearish:
                action, next_action = DecisionAction.SELL_REVIEW, "review_exit_conditions"
            elif financial_deterioration or concentrated or (bearish and high_volatility):
                action, next_action = DecisionAction.REDUCE_REVIEW, "review_position_size"
            elif bearish or high_volatility or deep_drawdown or overbought:
                action, next_action = DecisionAction.WATCH, "review_risk_next_close"
            else:
                action, next_action = DecisionAction.KEEP, "hold_and_review_next_close"
        elif earnings_wait:
            action, next_action = DecisionAction.WAIT_FOR_EARNINGS, "review_after_earnings"
        elif financial_deterioration or bearish or high_volatility or deep_drawdown:
            action, next_action = DecisionAction.PASS, "keep_off_watchlist"
        elif bullish and not overbought:
            action, next_action = DecisionAction.BUY_CANDIDATE, "define_entry_and_invalidation"
        elif (close > sma60 and (close < sma20 or overbought)) or oversold:
            action, next_action = DecisionAction.WAIT_FOR_PULLBACK, "review_after_price_reset"
        else:
            action, next_action = DecisionAction.PASS, "wait_for_stronger_evidence"
        return self._decision(
            context,
            action,
            confidence,
            evidence,
            ("trend_change", "earnings_update", "financial_update"),
            next_action,
        )

    def _decision(
        self,
        context: AnalysisContext,
        action: DecisionAction,
        confidence: DecisionConfidence,
        evidence: tuple[DecisionEvidence, ...],
        invalidation_conditions: tuple[str, ...],
        next_action: str,
    ) -> InstrumentDecision:
        settings = dict(self.settings)
        settings["maximum_position_weight"] = canonical_decimal(
            context.personal.maximum_position_weight
        )
        return InstrumentDecision(
            context.instrument,
            context.holding is not None,
            action,
            confidence,
            evidence,
            context.next_earnings_date,
            context.revenue_growth,
            context.eps_growth,
            context.free_cash_flow,
            context.valuation,
            invalidation_conditions,
            next_action,
            self.name,
            self.version,
            tuple(sorted(settings.items())),
        )


_SMA60 = "sma_60"
_ESSENTIAL_INDICATORS: tuple[IndicatorName | str, ...] = (
    IndicatorName.SMA,
    _SMA60,
    IndicatorName.RSI,
    IndicatorName.MACD,
    IndicatorName.ATR,
    IndicatorName.PERIOD_RETURN,
)


def _indicator_results(bars: tuple[DailyBar, ...]) -> dict[IndicatorName | str, IndicatorResult]:
    return {
        IndicatorName.SMA: calculate(IndicatorSpec.create(IndicatorName.SMA, period=20), bars),
        _SMA60: calculate(IndicatorSpec.create(IndicatorName.SMA, period=60), bars),
        IndicatorName.RSI: calculate(IndicatorSpec.create(IndicatorName.RSI, period=14), bars),
        IndicatorName.MACD: calculate(
            IndicatorSpec.create(
                IndicatorName.MACD, fast_period=12, slow_period=26, signal_period=9
            ),
            bars,
        ),
        IndicatorName.ATR: calculate(IndicatorSpec.create(IndicatorName.ATR, period=14), bars),
        IndicatorName.PERIOD_RETURN: calculate(
            IndicatorSpec.create(IndicatorName.PERIOD_RETURN, period=20), bars
        ),
        IndicatorName.MAX_DRAWDOWN: calculate(
            IndicatorSpec.create(IndicatorName.MAX_DRAWDOWN, period=252), bars
        ),
    }


def _values(result: IndicatorResult) -> dict[str, Decimal]:
    return {name: Decimal(value) for name, value in result.values}


def _earnings_wait(context: AnalysisContext, days: int) -> bool:
    if context.next_earnings_date is None:
        return False
    local_date = context.as_of.astimezone(context.instrument.exchange_timezone).date()
    remaining = (context.next_earnings_date - local_date).days
    return 0 <= remaining <= days


def _confidence(context: AnalysisContext, drawdown: IndicatorResult) -> DecisionConfidence:
    fundamental_count = sum(
        value is not None
        for value in (context.revenue_growth, context.eps_growth, context.free_cash_flow)
    )
    if drawdown.status is IndicatorStatus.OK and fundamental_count == 3:
        return DecisionConfidence.HIGH
    if drawdown.status is IndicatorStatus.OK or fundamental_count >= 2:
        return DecisionConfidence.MEDIUM
    return DecisionConfidence.LOW


def _decision_evidence(
    context: AnalysisContext,
    results: dict[IndicatorName | str, IndicatorResult],
    **signals: object,
) -> tuple[DecisionEvidence, ...]:
    evidence: list[DecisionEvidence] = []
    code_directions = (
        ("bullish_trend", EvidenceDirection.SUPPORTING),
        ("bearish_trend", EvidenceDirection.OPPOSING),
        ("positive_20d_return", EvidenceDirection.SUPPORTING),
        ("negative_20d_return", EvidenceDirection.OPPOSING),
        ("overbought", EvidenceDirection.OPPOSING),
        ("oversold", EvidenceDirection.SUPPORTING),
        ("high_volatility", EvidenceDirection.OPPOSING),
        ("deep_drawdown", EvidenceDirection.OPPOSING),
        ("financial_deterioration", EvidenceDirection.OPPOSING),
        ("concentrated", EvidenceDirection.OPPOSING),
        ("earnings_wait", EvidenceDirection.LIMITATION),
    )
    technical_ids = tuple(
        result.evidence_id for result in results.values() if result.status is IndicatorStatus.OK
    )
    thresholds = {
        "overbought": canonical_decimal(cast(Decimal, signals["rsi_overbought_threshold"])),
        "oversold": canonical_decimal(cast(Decimal, signals["rsi_oversold_threshold"])),
        "high_volatility": canonical_decimal(cast(Decimal, signals["atr_warning_threshold"])),
        "deep_drawdown": canonical_decimal(cast(Decimal, signals["drawdown_warning_threshold"])),
        "financial_deterioration": "2_of_3_negative",
        "concentrated": canonical_decimal(cast(Decimal, signals["concentration_threshold"])),
        "earnings_wait": str(signals["earnings_wait_threshold"]),
    }
    for code, direction in code_directions:
        if signals[code] is True:
            ids = (
                context.input_evidence_ids
                if code in {"financial_deterioration", "concentrated", "earnings_wait"}
                else technical_ids
            )
            evidence.append(DecisionEvidence(code, direction, None, thresholds.get(code), ids))
    atr_ratio = signals["atr_ratio"]
    evidence.append(
        DecisionEvidence(
            "atr_close_ratio",
            EvidenceDirection.OPPOSING
            if signals["high_volatility"] is True
            else EvidenceDirection.SUPPORTING,
            canonical_decimal(atr_ratio) if isinstance(atr_ratio, Decimal) else None,
            None,
            (results[IndicatorName.ATR].evidence_id,),
        )
    )
    drawdown = signals["drawdown"]
    if isinstance(drawdown, Decimal):
        evidence.append(
            DecisionEvidence(
                "maximum_drawdown",
                EvidenceDirection.OPPOSING
                if signals["deep_drawdown"] is True
                else EvidenceDirection.SUPPORTING,
                canonical_decimal(drawdown),
                None,
                (results[IndicatorName.MAX_DRAWDOWN].evidence_id,),
            )
        )
    else:
        evidence.append(
            DecisionEvidence(
                "missing_maximum_drawdown",
                EvidenceDirection.LIMITATION,
                str(results[IndicatorName.MAX_DRAWDOWN].observation_count),
                "252",
                (results[IndicatorName.MAX_DRAWDOWN].evidence_id,),
            )
        )
    return tuple(evidence)


def _bounded_decimal(value: Decimal, name: str, *, minimum: Decimal, maximum: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must use decimal.Decimal")
    if not value.is_finite() or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
