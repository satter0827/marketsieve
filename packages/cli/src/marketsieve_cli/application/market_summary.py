"""Neutral aggregate and failure projections for Market Snapshot builds."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any

from marketsieve._snapshot import SnapshotRow
from marketsieve.indicators import CONTEXT, canonical_decimal
from marketsieve_cli.contracts import RuntimeSettings


def _decimal(values: Mapping[str, str], name: str) -> Decimal | None:
    try:
        return Decimal(values[name])
    except (KeyError, ArithmeticError):
        return None


def _median(values: list[Decimal]) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    with localcontext(CONTEXT):
        result = (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
        )
    return canonical_decimal(result)


def _percentile(values: list[Decimal], percentile: int) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    with localcontext(CONTEXT):
        position = Decimal(len(ordered) - 1) * Decimal(percentile) / Decimal(100)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - Decimal(lower)
        result = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return canonical_decimal(result)


def _ratio_text(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator == 0:
        return None
    with localcontext(CONTEXT):
        return canonical_decimal(numerator / denominator)


def _summary(
    rows: tuple[SnapshotRow, ...],
    indices: tuple[str, ...],
    runtime: RuntimeSettings,
    retrieved_at: datetime,
    *,
    price_requested: bool,
) -> dict[str, Any]:
    with localcontext(CONTEXT):
        return _build_summary(rows, indices, runtime, retrieved_at, price_requested=price_requested)


def _build_summary(
    rows: tuple[SnapshotRow, ...],
    indices: tuple[str, ...],
    runtime: RuntimeSettings,
    retrieved_at: datetime,
    *,
    price_requested: bool,
) -> dict[str, Any]:
    groups: dict[str, tuple[SnapshotRow, ...]] = {
        "all": rows,
        **{
            f"index:{index}": tuple(row for row in rows if index in row.security.memberships)
            for index in indices
        },
    }
    groups["market:jp"] = tuple(row for row in rows if row.security.instrument.mic == "XTKS")
    groups["market:us"] = tuple(row for row in rows if row.security.instrument.mic != "XTKS")
    for classification_field, prefix in (("sector", "sector"), ("industry", "industry")):
        classification_values = sorted(
            {
                classification_value
                for row in rows
                if (classification_value := dict(row.values).get(classification_field)) is not None
            }
        )
        for classification_value in classification_values:
            groups[f"{prefix}:{classification_value}"] = tuple(
                row
                for row in rows
                if dict(row.values).get(classification_field) == classification_value
            )
    for market_name, market_rows in (
        ("jp", groups["market:jp"]),
        ("us", groups["market:us"]),
    ):
        sectors = sorted(
            {
                sector
                for row in market_rows
                if (sector := dict(row.values).get("sector")) is not None
            }
        )
        for sector in sectors:
            groups[f"market-sector:{market_name}|{sector}"] = tuple(
                row for row in market_rows if dict(row.values).get("sector") == sector
            )
    documents: dict[str, Any] = {}
    for name, selected in groups.items():
        present = [row for row in selected if "close" in dict(row.values)]
        returns = [
            value
            for row in present
            if (value := _decimal(dict(row.values), "return_1d")) is not None
        ]
        values_by_name = {
            field: [
                value
                for row in selected
                if (value := _decimal(dict(row.values), field)) is not None
            ]
            for field in (
                "return_20d",
                "return_60d",
                "return_252d",
                "volatility_60d",
                "volatility_252d",
                "maximum_drawdown_252d",
                "trailing_pe",
                "price_to_book",
                "return_on_equity",
                "operating_margin",
                "revenue_growth",
            )
        }
        market_caps_by_currency: dict[str, list[Decimal]] = {}
        traded_values_by_currency: dict[str, list[Decimal]] = {}
        for row in selected:
            row_values = dict(row.values)
            currency = row_values.get("currency")
            market_cap = _decimal(row_values, "market_cap")
            if currency is not None and market_cap is not None:
                market_caps_by_currency.setdefault(currency, []).append(market_cap)
            traded_value = _decimal(row_values, "median_traded_value_20d")
            if currency is not None and traded_value is not None:
                traded_values_by_currency.setdefault(currency, []).append(traded_value)
        currency_totals = {
            currency: sum(values, start=Decimal(0))
            for currency, values in market_caps_by_currency.items()
        }
        concentration_by_currency = {}
        for currency, market_caps in sorted(market_caps_by_currency.items()):
            total = currency_totals[currency]
            concentration_by_currency[currency] = {
                "market_cap_observation_count": len(market_caps),
                "top_10_market_cap_share": _ratio_text(
                    sum(sorted(market_caps, reverse=True)[:10], start=Decimal(0)), total
                )
                if total > 0
                else None,
            }
        only_currency = next(iter(market_caps_by_currency), None)
        if len(market_caps_by_currency) != 1:
            only_currency = None
        sector_counts: dict[str, int] = {}
        sector_market_caps: dict[str, dict[str, Decimal]] = {}
        missing_fields: dict[str, int] = {}
        missing_reasons: dict[str, int] = {}
        for row in selected:
            row_values = dict(row.values)
            sector = row_values.get("sector", "unclassified")
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            market_cap = _decimal(row_values, "market_cap")
            currency = row_values.get("currency")
            if market_cap is not None and currency is not None:
                currency_values = sector_market_caps.setdefault(sector, {})
                currency_values[currency] = currency_values.get(currency, Decimal(0)) + market_cap
            for field, reason in row.missing:
                missing_fields[field] = missing_fields.get(field, 0) + 1
                missing_reasons[reason] = missing_reasons.get(reason, 0) + 1
        documents[name] = {
            "security_count": len(selected),
            "price_count": len(present),
            "latest_price_date": max(
                (
                    latest_price_date
                    for row in present
                    if (latest_price_date := dict(row.values).get("price_as_of")) is not None
                ),
                default=None,
            ),
            "price_coverage": _ratio_text(Decimal(len(present)), Decimal(len(selected)))
            if selected
            else "0",
            "advancing_count": sum(value > 0 for value in returns),
            "declining_count": sum(value < 0 for value in returns),
            "unchanged_count": sum(value == 0 for value in returns),
            "above_sma_20_count": sum(
                (_decimal(dict(row.values), "distance_sma_20") or Decimal("-1")) > 0
                for row in present
            ),
            "above_sma_200_count": sum(
                (_decimal(dict(row.values), "distance_sma_200") or Decimal("-1")) > 0
                for row in present
            ),
            "distributions": {
                field: {
                    "count": len(values),
                    "p25": _percentile(values, 25),
                    "median": _median(values),
                    "p75": _percentile(values, 75),
                }
                for field, values in values_by_name.items()
                if values
            },
            "currency_distributions": {
                field: {
                    currency: {
                        "count": len(currency_values),
                        "p25": _percentile(currency_values, 25),
                        "median": _median(currency_values),
                        "p75": _percentile(currency_values, 75),
                    }
                    for currency, currency_values in sorted(values_by_currency.items())
                }
                for field, values_by_currency in (
                    ("market_cap", market_caps_by_currency),
                    ("median_traded_value_20d", traded_values_by_currency),
                )
            },
            "concentration": {
                "market_cap_observation_count": sum(
                    len(values) for values in market_caps_by_currency.values()
                ),
                "top_10_market_cap_share": (
                    concentration_by_currency[only_currency]["top_10_market_cap_share"]
                    if only_currency is not None
                    else None
                ),
                "by_currency": concentration_by_currency,
            },
            "sectors": {
                sector: {
                    "security_count": sector_counts[sector],
                    "market_cap_share": (
                        _ratio_text(
                            sector_market_caps.get(sector, {}).get(only_currency, Decimal(0)),
                            currency_totals[only_currency],
                        )
                        if only_currency is not None and currency_totals[only_currency] > 0
                        else None
                    ),
                    "market_cap_share_by_currency": {
                        currency: (
                            _ratio_text(value, currency_totals[currency])
                            if currency_totals[currency] > 0
                            else None
                        )
                        for currency, value in sorted(sector_market_caps.get(sector, {}).items())
                    },
                }
                for sector in sorted(sector_counts)
            },
            "missing": {
                "fields": dict(sorted(missing_fields.items())),
                "reasons": dict(sorted(missing_reasons.items())),
            },
        }
    overall = Decimal(documents["all"]["price_coverage"])
    index_coverages = {
        index: Decimal(documents[f"index:{index}"]["price_coverage"]) for index in indices
    }
    meets = (not price_requested) or (
        overall >= runtime.market_quality.minimum_overall_price_coverage
        and all(
            value >= runtime.market_quality.minimum_index_price_coverage
            for value in index_coverages.values()
        )
    )
    return {
        "schema": "market-snapshot-summary/v1",
        "generated_at": retrieved_at.isoformat(),
        "coverage": {
            "overall": canonical_decimal(overall),
            "indices": {
                key: canonical_decimal(value) for key, value in sorted(index_coverages.items())
            },
        },
        "price_requirements_met": meets,
        "groups": documents,
    }


def _failures(
    rows: tuple[SnapshotRow, ...],
    provider_failures: tuple[Any, ...],
) -> tuple[dict[str, str], ...]:
    output = []
    for value in provider_failures:
        output.append(
            {
                "schema": "market-snapshot-failure/v2",
                "instrument_id": f"{value.instrument.mic}:{value.instrument.symbol}",
                "stage": value.stage,
                "field": value.field,
                "reason": value.reason,
            }
        )
    # Cell-level absence is authoritative in each row's ``missing`` mapping.
    # failures.jsonl is intentionally limited to acquisition or calculation
    # attempts that actually failed at their boundary.
    del rows
    return tuple(
        sorted(
            output,
            key=lambda value: (
                value["instrument_id"],
                value["stage"],
                value["field"],
                value["reason"],
            ),
        )
    )
