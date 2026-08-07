"""Pure cross-sectional equity matrix calculations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from marketsieve.analysis.indicators import (
    CONTEXT,
    IndicatorName,
    IndicatorSpec,
    IndicatorStatus,
    calculate,
    canonical_decimal,
)
from marketsieve.data.daily import DailyBar
from marketsieve.domain import Instrument

INDEX_BENCHMARKS = {
    "dow30": "^DJI",
    "nasdaq100": "^NDX",
    "nikkei225": "^N225",
    "sp500": "^GSPC",
    "topix500": "1308.T",
}
PERIODS = (1, 5, 20, 60, 120, 252)
RELATIVE_PERIODS = (20, 60, 120, 252)


@dataclass(frozen=True, slots=True)
class MatrixField:
    """Definition of one stable matrix column."""

    name: str
    group: str
    data_type: str
    unit: str | None
    source: str
    definition: str
    formula: str | None
    period: str | None
    definition_version: str = "market-matrix-fields/v2"


@dataclass(frozen=True, slots=True)
class MatrixSecurity:
    """Provider-neutral input for one matrix row."""

    instrument: Instrument
    provider_symbol: str
    memberships: tuple[str, ...]
    retrieved_at: datetime
    bars: tuple[DailyBar, ...]
    profile: tuple[tuple[str, str], ...]
    financials: tuple[tuple[str, str], ...]
    evidence_id: str
    missing: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        names = tuple(name for name, _ in self.missing)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("security missing overrides must be unique and sorted")
        known = {field.name for field in field_definitions()}
        if set(names) - known or any(not reason for _, reason in self.missing):
            raise ValueError("security missing overrides must use known fields and reasons")


@dataclass(frozen=True, slots=True)
class MatrixRow:
    """One complete row with an explicit reason for every absent value."""

    security: MatrixSecurity
    values: tuple[tuple[str, str], ...]
    missing: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        names = tuple(name for name, _ in self.values)
        missing_names = tuple(name for name, _ in self.missing)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("matrix values must be unique and sorted")
        if missing_names != tuple(sorted(missing_names)) or len(missing_names) != len(
            set(missing_names)
        ):
            raise ValueError("matrix missing reasons must be unique and sorted")
        expected = {field.name for field in field_definitions()}
        if set(names) | set(missing_names) != expected or set(names) & set(missing_names):
            raise ValueError("matrix row must cover every field exactly once")


def _field(
    name: str,
    group: str,
    *,
    data_type: str = "decimal",
    unit: str | None = None,
    source: str = "marketsieve",
    definition: str,
    formula: str | None = None,
    period: str | None = None,
) -> MatrixField:
    return MatrixField(name, group, data_type, unit, source, definition, formula, period)


def field_definitions() -> tuple[MatrixField, ...]:
    """Return the complete stable v1 field catalog."""

    fields = [
        _field(
            "name",
            "identity",
            data_type="string",
            source="yfinance",
            definition="Provider short or long company name.",
        ),
        _field(
            "exchange",
            "identity",
            data_type="string",
            source="yfinance",
            definition="Provider exchange name.",
        ),
        _field(
            "country",
            "identity",
            data_type="string",
            source="yfinance",
            definition="Provider company country.",
        ),
        _field(
            "currency",
            "identity",
            data_type="string",
            source="yfinance",
            definition="Provider quote currency.",
        ),
        _field(
            "financial_currency",
            "identity",
            data_type="string",
            source="yfinance",
            definition="Provider currency used for reported financial statement values.",
        ),
        _field(
            "sector",
            "identity",
            data_type="string",
            source="yfinance",
            definition="Provider sector classification.",
        ),
        _field(
            "industry",
            "identity",
            data_type="string",
            source="yfinance",
            definition="Provider industry classification.",
        ),
        _field(
            "quote_type",
            "identity",
            data_type="string",
            source="yfinance",
            definition="Provider instrument classification.",
        ),
        _field(
            "price_as_of",
            "price",
            data_type="date",
            source="yfinance",
            definition="Trading date of the latest accepted daily bar.",
        ),
        _field(
            "close",
            "price",
            unit="quote_currency",
            source="yfinance",
            definition="Latest adjusted daily close.",
        ),
        _field(
            "previous_close",
            "price",
            unit="quote_currency",
            source="yfinance",
            definition="Previous adjusted close from accepted history.",
        ),
        _field(
            "high_52w",
            "price",
            unit="quote_currency",
            source="yfinance",
            definition="Highest adjusted daily high over the latest 252 observations.",
        ),
        _field(
            "low_52w",
            "price",
            unit="quote_currency",
            source="yfinance",
            definition="Lowest adjusted daily low over the latest 252 observations.",
        ),
        _field(
            "market_cap",
            "size",
            unit="quote_currency",
            source="yfinance",
            definition="Provider current market capitalization.",
        ),
        _field(
            "enterprise_value",
            "size",
            unit="quote_currency",
            source="yfinance",
            definition="Provider current enterprise value.",
        ),
        _field(
            "shares_outstanding",
            "size",
            unit="shares",
            source="yfinance",
            definition="Provider shares outstanding.",
        ),
    ]
    fields.extend(
        _field(
            f"return_{period}d",
            "return",
            unit="ratio",
            definition=f"Simple close return over {period} trading intervals.",
            formula="(close_t / close_t_minus_n) - 1",
            period=f"{period} trading intervals",
        )
        for period in PERIODS
    )
    for period in (20, 50, 200):
        fields.extend(
            (
                _field(
                    f"sma_{period}",
                    "trend",
                    unit="quote_currency",
                    definition=f"Simple moving average of the latest {period} closes.",
                    formula="sum(close) / observation_count",
                    period=f"{period} observations",
                ),
                _field(
                    f"distance_sma_{period}",
                    "trend",
                    unit="ratio",
                    definition=f"Latest close divided by SMA{period}, minus one.",
                    formula="(close / sma) - 1",
                    period=f"{period} observations",
                ),
            )
        )
    for period in (20, 60):
        fields.extend(
            (
                _field(
                    f"ema_{period}",
                    "trend",
                    unit="quote_currency",
                    definition=f"EMA of closes with SMA seed and period {period}.",
                    formula="ema_sma_seed(close, period)",
                    period=f"{period} observations",
                ),
                _field(
                    f"distance_ema_{period}",
                    "trend",
                    unit="ratio",
                    definition=f"Latest close divided by EMA{period}, minus one.",
                    formula="(close / ema) - 1",
                    period=f"{period} observations",
                ),
            )
        )
    fields.extend(
        (
            _field(
                "position_52w",
                "trend",
                unit="ratio",
                definition="Latest close position between 252-observation low and high.",
                formula="(close - low_52w) / (high_52w - low_52w)",
                period="252 observations",
            ),
            _field(
                "rsi_14",
                "momentum",
                unit="index",
                definition="Wilder RSI over 14 periods.",
                formula="wilder_rsi(close_t - close_t_minus_1, 14)",
                period="14 trading intervals",
            ),
            _field(
                "macd",
                "momentum",
                unit="quote_currency",
                definition="EMA12 minus EMA26.",
                formula="ema_sma_seed(close, 12) - ema_sma_seed(close, 26)",
                period="12- and 26-observation EMAs; 34 observations minimum with signal",
            ),
            _field(
                "macd_signal",
                "momentum",
                unit="quote_currency",
                definition="EMA9 of MACD12/26.",
                formula="ema_sma_seed(macd_12_26, 9)",
                period="9 MACD observations; 34 close observations minimum",
            ),
            _field(
                "macd_histogram",
                "momentum",
                unit="quote_currency",
                definition="MACD minus signal.",
                formula="macd_12_26 - macd_signal_9",
                period="12/26/9; 34 close observations minimum",
            ),
            _field(
                "bollinger_middle_20",
                "momentum",
                unit="quote_currency",
                definition="Twenty-observation close mean.",
                formula="mean(close)",
                period="20 observations",
            ),
            _field(
                "bollinger_upper_20",
                "momentum",
                unit="quote_currency",
                definition="Twenty-observation mean plus two sample standard deviations.",
                formula="mean(close) + 2 * sample_std(close)",
                period="20 observations",
            ),
            _field(
                "bollinger_lower_20",
                "momentum",
                unit="quote_currency",
                definition="Twenty-observation mean minus two sample standard deviations.",
                formula="mean(close) - 2 * sample_std(close)",
                period="20 observations",
            ),
            _field(
                "bollinger_z_20",
                "momentum",
                unit="standard_deviation",
                definition=(
                    "Latest close distance from the 20-observation mean in sample "
                    "standard deviations."
                ),
                formula="(close - mean(close)) / sample_std(close)",
                period="20 observations",
            ),
            _field(
                "atr_14",
                "risk",
                unit="quote_currency",
                definition="Wilder average true range over 14 periods.",
                formula=(
                    "wilder_mean(max(high - low, abs(high - previous_close), "
                    "abs(low - previous_close)), 14)"
                ),
                period="14-period Wilder smoothing over available observations",
            ),
            _field(
                "atr_14_ratio",
                "risk",
                unit="ratio",
                definition="ATR14 divided by latest close.",
                formula="atr_14 / close",
                period="14-period ATR and latest close",
            ),
        )
    )
    for period in (20, 60, 252):
        fields.append(
            _field(
                f"volatility_{period}d",
                "risk",
                unit="annualized_ratio",
                definition=(
                    f"Sample standard deviation of daily log returns over {period} intervals, "
                    "annualized by sqrt(252)."
                ),
                formula="sample_std(ln(close_t / close_t_minus_1)) * sqrt(252)",
                period=f"{period} trading intervals",
            )
        )
    for period in (60, 252):
        fields.extend(
            (
                _field(
                    f"downside_deviation_{period}d",
                    "risk",
                    unit="annualized_ratio",
                    definition=(
                        f"Root mean squared negative log return over {period} intervals, "
                        "annualized by sqrt(252)."
                    ),
                    formula="sqrt(mean(min(log_return, 0)^2)) * sqrt(252)",
                    period=f"{period} trading intervals",
                ),
                _field(
                    f"maximum_drawdown_{period}d",
                    "risk",
                    unit="ratio",
                    definition=(
                        f"Worst close decline from a running peak over {period} observations."
                    ),
                    formula="min((close / running_peak_close) - 1)",
                    period=f"{period} observations",
                ),
            )
        )
    fields.extend(
        (
            _field(
                "average_volume_20d",
                "liquidity",
                unit="shares",
                definition="Mean split-adjusted daily volume over 20 observations.",
                formula="mean(split_adjusted_volume)",
                period="20 observations",
            ),
            _field(
                "average_volume_60d",
                "liquidity",
                unit="shares",
                definition="Mean split-adjusted daily volume over 60 observations.",
                formula="mean(split_adjusted_volume)",
                period="60 observations",
            ),
            _field(
                "median_traded_value_20d",
                "liquidity",
                unit="quote_currency",
                definition=(
                    "Median adjusted close times split-adjusted volume over 20 observations."
                ),
                formula="median(adjusted_close * split_adjusted_volume)",
                period="20 observations",
            ),
            _field(
                "volume_turnover_20d",
                "liquidity",
                unit="ratio",
                definition="Average 20-day volume divided by shares outstanding.",
                formula="mean(volume) / shares_outstanding",
                period="20 observations",
            ),
            _field(
                "amihud_illiquidity_20d",
                "liquidity",
                unit="inverse_quote_currency",
                definition="Mean absolute simple return divided by traded value over 20 intervals.",
                formula="mean(abs(simple_return) / (close * volume))",
                period="20 trading intervals",
            ),
            _field(
                "zero_volume_days_20d",
                "liquidity",
                data_type="integer",
                unit="days",
                definition="Count of zero split-adjusted-volume observations in the latest 20.",
                formula="count(split_adjusted_volume == 0)",
                period="20 observations",
            ),
        )
    )
    for index in sorted(INDEX_BENCHMARKS):
        benchmark_label = (
            "TOPIX-linked ETF proxy 1308.T" if index == "topix500" else f"{index} benchmark"
        )
        fields.extend(
            _field(
                f"relative_return_{index}_{period}d",
                "relative",
                unit="ratio",
                definition=(
                    f"Security {period}-day return minus {benchmark_label} return "
                    "on aligned closes."
                ),
                formula="security_simple_return - benchmark_simple_return",
                period=f"{period} common trading intervals",
            )
            for period in RELATIVE_PERIODS
        )
        fields.append(
            _field(
                f"beta_{index}_252d",
                "relative",
                unit="ratio",
                definition=(
                    f"Covariance of aligned security and {benchmark_label} simple daily "
                    "returns divided "
                    "by benchmark variance over 252 intervals."
                ),
                formula="sample_covariance(security_return, benchmark_return) / benchmark_variance",
                period="252 common trading intervals",
            )
        )
    provider_financials = (
        "revenue_ttm",
        "ebitda_ttm",
        "operating_income_ttm",
        "net_income_ttm",
        "operating_cash_flow_ttm",
        "capital_expenditure_ttm",
        "free_cash_flow_ttm",
        "total_assets",
        "total_equity",
        "total_cash",
        "total_debt",
        "revenue_growth",
        "earnings_growth",
        "revenue_cagr_3y",
        "earnings_cagr_3y",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "return_on_equity",
        "return_on_assets",
        "debt_to_equity",
        "current_ratio",
        "quick_ratio",
        "trailing_pe",
        "forward_pe",
        "price_to_book",
        "price_to_sales",
        "enterprise_to_revenue",
        "enterprise_to_ebitda",
        "dividend_yield",
        "payout_ratio",
    )
    monetary_financials = {
        "revenue_ttm",
        "ebitda_ttm",
        "operating_income_ttm",
        "net_income_ttm",
        "operating_cash_flow_ttm",
        "capital_expenditure_ttm",
        "free_cash_flow_ttm",
        "total_assets",
        "total_equity",
        "total_cash",
        "total_debt",
    }
    trailing_financials = {name for name in monetary_financials if name.endswith("_ttm")}
    cagr_financials = {"revenue_cagr_3y", "earnings_cagr_3y"}
    statement_sum_financials = {
        "revenue_ttm",
        "ebitda_ttm",
        "operating_income_ttm",
        "net_income_ttm",
        "operating_cash_flow_ttm",
        "capital_expenditure_ttm",
        "free_cash_flow_ttm",
    }
    statement_latest_financials = {
        "total_assets",
        "total_equity",
        "total_cash",
        "total_debt",
    }
    direct_with_statement_fallback = statement_sum_financials - {"capital_expenditure_ttm"} | {
        "total_cash",
        "total_debt",
    }
    for name in provider_financials:
        financial_period = (
            "trailing twelve months"
            if name in trailing_financials
            else "latest provider fiscal period"
            if name in monetary_financials
            else "three annual intervals"
            if name in cagr_financials
            else "current provider snapshot"
        )
        if name in cagr_financials:
            definition = (
                f"Three-year compound growth derived from four compatible annual "
                f"{name.removesuffix('_cagr_3y').replace('_', ' ')} observations."
            )
            formula = "exp(ln(latest_positive_value / three_year_prior_positive_value) / 3) - 1"
        elif name in statement_sum_financials:
            fallback = "sum(latest_four_compatible_quarterly_values)"
            definition = (
                f"Normalized provider value for {name.replace('_', ' ')}, falling back to the "
                "sum of four compatible quarterly statement values."
                if name in direct_with_statement_fallback
                else "Sum of the latest four compatible provider quarterly statement values."
            )
            formula = f"provider_value if present else {fallback}"
            if name not in direct_with_statement_fallback:
                formula = fallback
        elif name in statement_latest_financials:
            fallback = "latest_compatible_statement_value"
            definition = (
                f"Normalized provider value for {name.replace('_', ' ')}, falling back to the "
                "latest compatible statement value."
                if name in direct_with_statement_fallback
                else "Latest compatible provider statement value."
            )
            formula = f"provider_value if present else {fallback}"
            if name not in direct_with_statement_fallback:
                formula = fallback
        else:
            definition = f"Provider value normalized for {name.replace('_', ' ')}."
            formula = None
        fields.append(
            _field(
                name,
                "financial" if name in monetary_financials else "fundamental",
                unit="financial_currency" if name in monetary_financials else "ratio",
                source="yfinance",
                definition=definition,
                formula=formula,
                period=financial_period,
            )
        )
    fields.extend(
        (
            _field(
                "free_cash_flow_margin",
                "profitability",
                unit="ratio",
                definition="Free cash flow divided by revenue.",
                formula="free_cash_flow_ttm / revenue_ttm",
                period="trailing twelve months",
            ),
            _field(
                "equity_ratio",
                "safety",
                unit="ratio",
                definition="Total equity divided by total assets.",
                formula="total_equity / total_assets",
                period="latest provider period",
            ),
            _field(
                "earnings_yield",
                "valuation",
                unit="ratio",
                definition="Reciprocal of positive trailing P/E.",
                formula="1 / trailing_pe when trailing_pe > 0",
                period="current provider snapshot",
            ),
            _field(
                "free_cash_flow_yield",
                "valuation",
                unit="ratio",
                definition="Free cash flow divided by market capitalization.",
                formula="free_cash_flow_ttm / market_cap",
                period="trailing twelve months over current market cap",
            ),
        )
    )
    return tuple(sorted(fields, key=lambda value: value.name))


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    with localcontext(CONTEXT):
        return +(numerator / denominator)


def _ratio_missing_reason(
    numerator: Decimal | None, denominator: Decimal | None, unavailable: str
) -> str:
    if numerator is not None and denominator == 0:
        return "zero_denominator"
    return unavailable


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext(CONTEXT):
        return +(sum(values, start=Decimal(0)) / Decimal(len(values)))


def _sample_std(values: tuple[Decimal, ...]) -> Decimal | None:
    if len(values) < 2:
        return None
    with localcontext(CONTEXT):
        mean = _mean(values)
        variance = sum(((value - mean) ** 2 for value in values), start=Decimal(0)) / Decimal(
            len(values) - 1
        )
        return +variance.sqrt()


def _log_returns(bars: tuple[DailyBar, ...], period: int) -> tuple[Decimal, ...]:
    if len(bars) < period + 1:
        return ()
    selected = bars[-(period + 1) :]
    with localcontext(CONTEXT):
        return tuple(
            +(selected[index].close / selected[index - 1].close).ln()
            for index in range(1, len(selected))
        )


def _simple_returns(bars: tuple[DailyBar, ...], period: int) -> tuple[Decimal, ...]:
    if len(bars) < period + 1:
        return ()
    selected = bars[-(period + 1) :]
    with localcontext(CONTEXT):
        return tuple(
            +(selected[index].close / selected[index - 1].close - Decimal(1))
            for index in range(1, len(selected))
        )


def _indicator(
    bars: tuple[DailyBar, ...], name: IndicatorName, value_name: str, **parameters: int
) -> Decimal | None:
    result = calculate(IndicatorSpec.create(name, **parameters), bars)
    if result.status is not IndicatorStatus.OK:
        return None
    return Decimal(dict(result.values)[value_name])


def build_matrix_row(
    security: MatrixSecurity, benchmarks: Mapping[str, tuple[DailyBar, ...]]
) -> MatrixRow:
    """Calculate one complete row under the fixed Decimal policy."""

    with localcontext(CONTEXT):
        return _build_matrix_row(security, benchmarks)


def _build_matrix_row(
    security: MatrixSecurity, benchmarks: Mapping[str, tuple[DailyBar, ...]]
) -> MatrixRow:
    """Calculate one complete row without I/O or imputation."""

    values: dict[str, str] = {}
    missing: dict[str, str] = {}
    profile = dict(security.profile)
    financials = dict(security.financials)
    missing_overrides = dict(security.missing)

    def put(name: str, value: object | None, reason: str = "field_absent") -> None:
        if override := missing_overrides.get(name):
            missing[name] = override
        elif value is None:
            missing[name] = missing_overrides.get(name, reason)
        elif isinstance(value, Decimal):
            values[name] = canonical_decimal(value)
        else:
            rendered = str(value)
            if rendered:
                values[name] = rendered
            else:
                missing[name] = missing_overrides.get(name, reason)

    put("name", profile.get("name") or profile.get("long_name"))
    for name in (
        "exchange",
        "country",
        "currency",
        "financial_currency",
        "sector",
        "industry",
        "quote_type",
    ):
        put(name, profile.get(name))
    bars = security.bars
    close = bars[-1].close if bars else None
    put("price_as_of", bars[-1].trading_date.isoformat() if bars else None, "history_empty")
    put("close", close, "history_empty")
    put("previous_close", bars[-2].close if len(bars) >= 2 else None, "insufficient_history")
    selected_52w = bars[-252:] if len(bars) >= 252 else ()
    put(
        "high_52w",
        max((value.high for value in selected_52w), default=None),
        "insufficient_history",
    )
    put("low_52w", min((value.low for value in selected_52w), default=None), "insufficient_history")
    for name in ("market_cap", "enterprise_value", "shares_outstanding"):
        put(name, _decimal(profile.get(name)))

    for period in PERIODS:
        result = _indicator(bars, IndicatorName.PERIOD_RETURN, "return", period=period)
        put(f"return_{period}d", result, "insufficient_history")
    for period in (20, 50, 200):
        average = _indicator(bars, IndicatorName.SMA, "sma", period=period)
        put(f"sma_{period}", average, "insufficient_history")
        distance = _ratio(close, average)
        put(
            f"distance_sma_{period}",
            distance - Decimal(1) if distance is not None else None,
            "insufficient_history",
        )
    for period in (20, 60):
        average = _indicator(bars, IndicatorName.EMA, "ema", period=period)
        put(f"ema_{period}", average, "insufficient_history")
        distance = _ratio(close, average)
        put(
            f"distance_ema_{period}",
            distance - Decimal(1) if distance is not None else None,
            "insufficient_history",
        )
    high_52w = max((value.high for value in selected_52w), default=None)
    low_52w = min((value.low for value in selected_52w), default=None)
    position_numerator = close - low_52w if close is not None and low_52w is not None else None
    position_denominator = (
        high_52w - low_52w if high_52w is not None and low_52w is not None else None
    )
    put(
        "position_52w",
        _ratio(position_numerator, position_denominator),
        _ratio_missing_reason(position_numerator, position_denominator, "insufficient_history"),
    )
    put("rsi_14", _indicator(bars, IndicatorName.RSI, "rsi", period=14), "insufficient_history")
    macd = calculate(
        IndicatorSpec.create(IndicatorName.MACD, fast_period=12, signal_period=9, slow_period=26),
        bars,
    )
    macd_values = dict(macd.values)
    put("macd", _decimal(macd_values.get("macd")), "insufficient_history")
    put("macd_signal", _decimal(macd_values.get("signal")), "insufficient_history")
    put("macd_histogram", _decimal(macd_values.get("histogram")), "insufficient_history")
    closes_20 = tuple(value.close for value in bars[-20:])
    middle = _mean(closes_20) if len(closes_20) == 20 else None
    deviation = _sample_std(closes_20) if len(closes_20) == 20 else None
    put("bollinger_middle_20", middle, "insufficient_history")
    put(
        "bollinger_upper_20",
        middle + deviation * 2 if middle is not None and deviation is not None else None,
        "insufficient_history",
    )
    put(
        "bollinger_lower_20",
        middle - deviation * 2 if middle is not None and deviation is not None else None,
        "insufficient_history",
    )
    bollinger_numerator = close - middle if close is not None and middle is not None else None
    put(
        "bollinger_z_20",
        _ratio(bollinger_numerator, deviation),
        _ratio_missing_reason(bollinger_numerator, deviation, "insufficient_history"),
    )
    atr = _indicator(bars, IndicatorName.ATR, "atr", period=14)
    put("atr_14", atr, "insufficient_history")
    put("atr_14_ratio", _ratio(atr, close), "insufficient_history")

    annualizer = Decimal(252).sqrt()
    for period in (20, 60, 252):
        returns = _log_returns(bars, period)
        deviation = _sample_std(returns)
        put(
            f"volatility_{period}d",
            deviation * annualizer if deviation is not None else None,
            "insufficient_history",
        )
    for period in (60, 252):
        returns = _log_returns(bars, period)
        downside = None
        if returns:
            with localcontext(CONTEXT):
                downside = (
                    +(
                        sum((min(value, Decimal(0)) ** 2 for value in returns), start=Decimal(0))
                        / Decimal(len(returns))
                    ).sqrt()
                    * annualizer
                )
        put(f"downside_deviation_{period}d", downside, "insufficient_history")
        drawdown = _indicator(bars, IndicatorName.MAX_DRAWDOWN, "maximum_drawdown", period=period)
        put(f"maximum_drawdown_{period}d", drawdown, "insufficient_history")

    for period in (20, 60):
        selected = bars[-period:]
        average_volume = (
            _mean(tuple(Decimal(value.volume) for value in selected))
            if len(selected) == period
            else None
        )
        put(f"average_volume_{period}d", average_volume, "insufficient_history")
    selected = bars[-20:]
    traded_values = sorted(value.close * Decimal(value.volume) for value in selected)
    median = None
    if len(traded_values) == 20:
        median = (traded_values[9] + traded_values[10]) / Decimal(2)
    put("median_traded_value_20d", median, "insufficient_history")
    shares = _decimal(profile.get("shares_outstanding"))
    average_volume = _decimal(values.get("average_volume_20d"))
    put(
        "volume_turnover_20d",
        _ratio(average_volume, shares),
        _ratio_missing_reason(
            average_volume,
            shares,
            "field_absent" if shares is None else "insufficient_history",
        ),
    )
    simple = _simple_returns(bars, 20)
    amihud_values: list[Decimal] = []
    if len(simple) == 20:
        for result, bar in zip(simple, bars[-20:], strict=True):
            traded = bar.close * Decimal(bar.volume)
            if traded > 0:
                amihud_values.append(abs(result) / traded)
    has_zero_traded_value = len(simple) == 20 and any(
        bar.close * Decimal(bar.volume) == 0 for bar in bars[-20:]
    )
    put(
        "amihud_illiquidity_20d",
        _mean(tuple(amihud_values)) if len(amihud_values) == 20 else None,
        "zero_denominator" if has_zero_traded_value else "insufficient_history",
    )
    put(
        "zero_volume_days_20d",
        sum(value.volume == 0 for value in selected) if len(selected) == 20 else None,
        "insufficient_history",
    )

    for index in sorted(INDEX_BENCHMARKS):
        if index not in security.memberships:
            for period in RELATIVE_PERIODS:
                put(f"relative_return_{index}_{period}d", None, "not_applicable")
            put(f"beta_{index}_252d", None, "not_applicable")
            continue
        benchmark = benchmarks.get(index, ())
        aligned = _aligned_bars(bars, benchmark)
        for period in RELATIVE_PERIODS:
            left = _indicator(aligned[0], IndicatorName.PERIOD_RETURN, "return", period=period)
            right = _indicator(aligned[1], IndicatorName.PERIOD_RETURN, "return", period=period)
            put(
                f"relative_return_{index}_{period}d",
                left - right if left is not None and right is not None else None,
                "benchmark_unavailable" if not benchmark else "insufficient_history",
            )
        beta, beta_reason = _beta(*aligned, period=252)
        put(
            f"beta_{index}_252d",
            beta,
            "benchmark_unavailable" if not benchmark else beta_reason,
        )

    for name in (
        "revenue_ttm",
        "ebitda_ttm",
        "operating_income_ttm",
        "net_income_ttm",
        "operating_cash_flow_ttm",
        "capital_expenditure_ttm",
        "free_cash_flow_ttm",
        "total_assets",
        "total_equity",
        "total_cash",
        "total_debt",
        "revenue_growth",
        "earnings_growth",
        "revenue_cagr_3y",
        "earnings_cagr_3y",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "return_on_equity",
        "return_on_assets",
        "debt_to_equity",
        "current_ratio",
        "quick_ratio",
        "trailing_pe",
        "forward_pe",
        "price_to_book",
        "price_to_sales",
        "enterprise_to_revenue",
        "enterprise_to_ebitda",
        "dividend_yield",
        "payout_ratio",
    ):
        put(
            name,
            _decimal(financials.get(name)),
            "financials_unavailable" if not financials else "field_absent",
        )
    revenue = _decimal(financials.get("revenue_ttm"))
    free_cash_flow = _decimal(financials.get("free_cash_flow_ttm"))
    total_equity = _decimal(financials.get("total_equity"))
    total_assets = _decimal(financials.get("total_assets"))
    market_cap = _decimal(profile.get("market_cap"))
    trailing_pe = _decimal(financials.get("trailing_pe"))
    put(
        "free_cash_flow_margin",
        _ratio(free_cash_flow, revenue),
        _ratio_missing_reason(free_cash_flow, revenue, "field_absent"),
    )
    put(
        "equity_ratio",
        _ratio(total_equity, total_assets),
        _ratio_missing_reason(total_equity, total_assets, "field_absent"),
    )
    earnings_yield = (
        _ratio(Decimal(1), trailing_pe) if trailing_pe is not None and trailing_pe > 0 else None
    )
    put(
        "earnings_yield",
        earnings_yield,
        "zero_denominator"
        if trailing_pe == 0
        else "not_applicable"
        if trailing_pe is not None and trailing_pe < 0
        else "field_absent",
    )
    quote_currency = profile.get("currency")
    financial_currency = profile.get("financial_currency")
    currencies_match = (
        quote_currency is not None
        and financial_currency is not None
        and quote_currency == financial_currency
    )
    free_cash_flow_yield_reason = (
        "currency_mismatch"
        if quote_currency is not None
        and financial_currency is not None
        and quote_currency != financial_currency
        else _ratio_missing_reason(free_cash_flow, market_cap, "field_absent")
        if currencies_match
        else "field_absent"
    )
    put(
        "free_cash_flow_yield",
        _ratio(free_cash_flow, market_cap) if currencies_match else None,
        free_cash_flow_yield_reason,
    )
    return MatrixRow(security, tuple(sorted(values.items())), tuple(sorted(missing.items())))


def _aligned_bars(
    left: tuple[DailyBar, ...], right: tuple[DailyBar, ...]
) -> tuple[tuple[DailyBar, ...], tuple[DailyBar, ...]]:
    right_by_date = {value.trading_date: value for value in right}
    left_by_date = {value.trading_date: value for value in left}
    dates = sorted(set(left_by_date) & set(right_by_date))
    return tuple(left_by_date[value] for value in dates), tuple(
        right_by_date[value] for value in dates
    )


def _beta(
    left: tuple[DailyBar, ...], right: tuple[DailyBar, ...], *, period: int
) -> tuple[Decimal | None, str]:
    left_returns = _simple_returns(left, period)
    right_returns = _simple_returns(right, period)
    if len(left_returns) != period or len(right_returns) != period:
        return None, "insufficient_history"
    left_mean = _mean(left_returns)
    right_mean = _mean(right_returns)
    with localcontext(CONTEXT):
        covariance = sum(
            (
                (left_value - left_mean) * (right_value - right_mean)
                for left_value, right_value in zip(left_returns, right_returns, strict=True)
            ),
            start=Decimal(0),
        ) / Decimal(period - 1)
        variance = sum(
            ((value - right_mean) ** 2 for value in right_returns), start=Decimal(0)
        ) / Decimal(period - 1)
        if variance == 0:
            return None, "zero_denominator"
        return +(covariance / variance), "insufficient_history"
