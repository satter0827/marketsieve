"""Stable field catalog for Market Snapshot evidence."""

from __future__ import annotations

from marketsieve.fields import FieldDefinition

MARKET_INDEX_IDS = ("dow30", "nasdaq100", "nikkei225", "sp500", "topix500")
PERIODS = (1, 5, 20, 60, 120, 252)
RELATIVE_PERIODS = (20, 60, 120, 252)


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
    applicable_to: str = "all_equities",
    comparison_scope: str = "same_market_and_currency",
    exclusion_conditions: tuple[str, ...] = (),
) -> FieldDefinition:
    return FieldDefinition(
        name,
        group,
        data_type,
        unit,
        source,
        definition,
        formula,
        period,
        applicable_to,
        comparison_scope,
        exclusion_conditions,
    )


def field_definitions() -> tuple[FieldDefinition, ...]:
    """Return the complete stable v2 field catalog."""

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
                unit="bounded_ratio",
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
    for index in MARKET_INDEX_IDS:
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
    limited_applicability = {
        "current_ratio",
        "quick_ratio",
        "debt_to_equity",
        "enterprise_to_revenue",
        "enterprise_to_ebitda",
    }
    multiple_financials = {
        "trailing_pe",
        "forward_pe",
        "price_to_book",
        "price_to_sales",
        "enterprise_to_revenue",
        "enterprise_to_ebitda",
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
                unit=(
                    "financial_currency"
                    if name in monetary_financials
                    else "multiple"
                    if name in multiple_financials
                    else "ratio"
                ),
                source="yfinance",
                definition=definition,
                formula=formula,
                period=financial_period,
                applicable_to=(
                    "non_financial_non_reit_equities"
                    if name in limited_applicability
                    else "all_equities"
                ),
                exclusion_conditions=(
                    ("financial_or_insurance_issuer", "reit")
                    if name in limited_applicability
                    else ()
                ),
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
                applicable_to="non_financial_non_reit_equities",
                exclusion_conditions=("financial_or_insurance_issuer", "reit"),
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
                applicable_to="non_financial_non_reit_equities",
                exclusion_conditions=("financial_or_insurance_issuer", "reit"),
            ),
        )
    )
    return tuple(sorted(fields, key=lambda value: value.name))
