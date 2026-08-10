"""Pure filtering and projection for saved Market Snapshot rows."""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from functools import cmp_to_key
from typing import Any

from marketsieve._snapshot_fields import MARKET_INDEX_IDS
from marketsieve_cli.contracts import ANALYSIS_PROFILES


def query_snapshot(
    *,
    snapshot_id: str,
    source_rows: Iterable[dict[str, Any]],
    definitions_document: dict[str, Any],
    market_indicators: Iterable[dict[str, Any]],
    filters: dict[str, tuple[str, ...]],
    minimums: dict[str, Decimal],
    maximums: dict[str, Decimal],
    present: tuple[str, ...],
    missing: tuple[str, ...],
    fields: tuple[str, ...],
    order: tuple[str, ...] = (),
    limit: int | None = None,
    domains: tuple[str, ...] = (),
    profile: str | None = None,
    budget: Decimal | None = None,
    budget_currency: str | None = None,
    trading_unit: int | None = None,
    use_snapshot_fx: bool = False,
) -> dict[str, Any]:
    allowed_filters = {
        "market",
        "index",
        "mic",
        "exchange",
        "country",
        "currency",
        "sector",
        "industry",
    }
    if unknown_filters := set(filters) - allowed_filters:
        raise ValueError(
            f"unknown market snapshot classification filters: {sorted(unknown_filters)}"
        )
    if any(not values for values in filters.values()):
        raise ValueError("market snapshot classification filters cannot be empty")
    if any(len(values) != len(set(values)) for values in filters.values()):
        raise ValueError("market snapshot classification filter values must be unique")
    if invalid_indices := set(filters.get("index", ())) - set(MARKET_INDEX_IDS):
        raise ValueError(f"unknown market snapshot indices: {sorted(invalid_indices)}")
    if any(len(values) != len(set(values)) for values in (present, missing, fields, domains)):
        raise ValueError("market snapshot query field selections must be unique")
    definitions = definitions_document["fields"]
    field_types = {value["name"]: value["data_type"] for value in definitions}
    known = set(field_types)
    order_fields: list[tuple[str, str]] = []
    for item in order:
        name, separator, direction = item.partition(":")
        if not separator or direction not in {"asc", "desc"}:
            raise ValueError("market snapshot order requires FIELD:asc or FIELD:desc")
        order_fields.append((name, direction))
    if len({name for name, _ in order_fields}) != len(order_fields):
        raise ValueError("market snapshot order fields must be unique")
    requested = (
        set(fields)
        | set(minimums)
        | set(maximums)
        | set(present)
        | set(missing)
        | {name for name, _ in order_fields}
    )
    if unknown := requested - known:
        raise ValueError(f"unknown market snapshot fields: {sorted(unknown)}")
    numeric = {name for name, kind in field_types.items() if kind in {"decimal", "integer"}}
    if invalid := (set(minimums) | set(maximums)) - numeric:
        raise ValueError(
            f"market snapshot numeric filters require numeric fields: {sorted(invalid)}"
        )
    if set(present) & set(missing):
        raise ValueError("market snapshot fields cannot be both present and missing")
    if invalid_bounds := {
        name for name in set(minimums) & set(maximums) if minimums[name] > maximums[name]
    }:
        raise ValueError(f"market snapshot minimum exceeds maximum: {sorted(invalid_bounds)}")
    known_domains = {value["group"] for value in definitions} | {"quality"}
    if invalid_domains := set(domains) - known_domains:
        raise ValueError(f"unknown market snapshot domains: {sorted(invalid_domains)}")
    if profile is not None and profile not in ANALYSIS_PROFILES:
        raise ValueError(f"unknown market snapshot profile: {profile}")
    selected_by_domain = {value["name"] for value in definitions if value["group"] in domains}
    if "quality" in domains:
        selected_by_domain.update({"price_as_of"})
    selected_source = set(fields) if fields else selected_by_domain or known
    if profile is not None and not fields:
        windows = set(ANALYSIS_PROFILES[profile]["windows"])
        selected_source = {
            name
            for name in selected_source
            if not (match := re.search(r"_(\d+)(?:d)?(?:$|_)", name))
            or int(match.group(1)) in windows
        }
        selected_source.update(
            {"name", "exchange", "country", "currency", "sector", "industry", "close"} & known
        )
    selected = tuple(sorted(selected_source))

    def classification_matches(row: dict[str, Any], name: str, accepted: tuple[str, ...]) -> bool:
        values = row["values"]
        actual: Any = {
            "market": "jp" if row["instrument"]["mic"] == "XTKS" else "us",
            "index": tuple(row["memberships"]),
            "mic": row["instrument"]["mic"],
            "exchange": values.get("exchange"),
            "country": values.get("country"),
            "currency": values.get("currency", row["instrument"]["currency"]),
            "sector": values.get("sector"),
            "industry": values.get("industry"),
        }[name]
        return bool(set(accepted) & set(actual)) if name == "index" else actual in accepted

    source_rows = list(source_rows)
    candidates = source_rows
    funnel: list[dict[str, Any]] = [
        {"condition": "input", "passed_count": len(candidates), "excluded_count": 0}
    ]
    conditions: list[tuple[str, Any]] = []
    for name, accepted in sorted(filters.items()):
        conditions.append(
            (
                f"{name}={','.join(accepted)}",
                lambda row, name=name, accepted=accepted: classification_matches(
                    row, name, accepted
                ),
            )
        )
    for name, threshold in sorted(minimums.items()):
        conditions.append(
            (
                f"min:{name}={threshold}",
                lambda row, name=name, threshold=threshold: (
                    name in row["values"] and Decimal(row["values"][name]) >= threshold
                ),
            )
        )
    for name, threshold in sorted(maximums.items()):
        conditions.append(
            (
                f"max:{name}={threshold}",
                lambda row, name=name, threshold=threshold: (
                    name in row["values"] and Decimal(row["values"][name]) <= threshold
                ),
            )
        )
    conditions.extend(
        (f"present:{name}", lambda row, name=name: name in row["values"])
        for name in sorted(present)
    )
    conditions.extend(
        (f"missing:{name}", lambda row, name=name: name in row["missing"])
        for name in sorted(missing)
    )
    exclusion_reasons: dict[str, int] = {}
    for label, predicate in conditions:
        before = len(candidates)
        candidates = [row for row in candidates if predicate(row)]
        excluded = before - len(candidates)
        funnel.append(
            {"condition": label, "passed_count": len(candidates), "excluded_count": excluded}
        )
        if excluded:
            exclusion_reasons[label] = excluded

    fx = None
    if use_snapshot_fx:
        indicators = tuple(market_indicators)
        usd_jpy = next((item for item in indicators if item.get("indicator_id") == "usd_jpy"), None)
        if usd_jpy is None or not usd_jpy.get("observations"):
            raise ValueError("Snapshot USD/JPY evidence is unavailable")
        latest_fx = usd_jpy["observations"][-1]
        fx = {
            "value": latest_fx["value"],
            "as_of": latest_fx["date"],
            "retrieved_at": usd_jpy["retrieved_at"],
            "source": "yfinance",
            "unit": "JPY_per_USD",
        }

    rows: list[dict[str, Any]] = []
    for row in candidates:
        values_document = {name: row["values"][name] for name in selected if name in row["values"]}
        purchase_projection = None
        if budget is not None and budget_currency is not None:
            currency = row["values"].get("currency", row["instrument"]["currency"])
            close = row["values"].get("close")
            unit = trading_unit or 1
            native_purchase = Decimal(close) * unit if close is not None else None
            minimum_purchase = native_purchase
            if native_purchase is not None and currency != budget_currency and fx is not None:
                rate = Decimal(fx["value"])
                if currency == "USD" and budget_currency == "JPY":
                    minimum_purchase = native_purchase * rate
                elif currency == "JPY" and budget_currency == "USD":
                    minimum_purchase = native_purchase / rate
                else:
                    minimum_purchase = None
            purchase_projection = {
                "budget": str(budget),
                "budget_currency": budget_currency,
                "security_currency": currency,
                "trading_unit": unit,
                "minimum_purchase_amount": (
                    str(minimum_purchase) if minimum_purchase is not None else None
                ),
                "affordable": (
                    minimum_purchase <= budget if minimum_purchase is not None else None
                ),
                "reason": (None if minimum_purchase is not None else "currency_mismatch"),
                "fx": fx if currency != budget_currency else None,
            }
        rows.append(
            {
                "instrument_id": row["instrument_id"],
                "instrument": row["instrument"],
                "provider_symbol": row["provider_symbol"],
                "memberships": row["memberships"],
                "retrieved_at": row["retrieved_at"],
                "values": values_document,
                "_order_values": {name: row["values"].get(name) for name, _ in order_fields},
                "missing": {
                    name: row["missing"][name] for name in selected if name in row["missing"]
                },
                **(
                    {"purchase_projection": purchase_projection}
                    if purchase_projection is not None
                    else {}
                ),
            }
        )

    def compare(left: dict[str, Any], right: dict[str, Any]) -> int:
        for name, direction in order_fields:
            left_value = left["_order_values"].get(name)
            right_value = right["_order_values"].get(name)
            if left_value is None or right_value is None:
                if left_value is right_value:
                    continue
                return 1 if left_value is None else -1
            if name in numeric:
                left_value, right_value = Decimal(left_value), Decimal(right_value)
            if left_value == right_value:
                continue
            result = -1 if left_value < right_value else 1
            return result if direction == "asc" else -result
        left_id, right_id = str(left["instrument_id"]), str(right["instrument_id"])
        return (left_id > right_id) - (left_id < right_id)

    rows.sort(key=cmp_to_key(compare))
    total_count = len(rows)
    if limit is not None:
        if limit <= 0:
            raise ValueError("market snapshot query limit must be positive")
        rows = rows[:limit]
    for row in rows:
        del row["_order_values"]
    return {
        "schema": "market-snapshot-query-result/v3",
        "snapshot_id": snapshot_id,
        "input_count": len(source_rows),
        "matched_count": len(rows),
        "total_matched_count": total_count,
        "fields": list(selected),
        "profile": profile,
        "domains": list(domains),
        "order": list(order),
        "limit": limit,
        "filters": {
            "classifications": {name: list(values) for name, values in sorted(filters.items())},
            "minimums": {name: str(value) for name, value in sorted(minimums.items())},
            "maximums": {name: str(value) for name, value in sorted(maximums.items())},
            "present": list(sorted(present)),
            "missing": list(sorted(missing)),
        },
        "filter_funnel": funnel,
        "exclusion_reasons": exclusion_reasons,
        "field_definitions_schema": definitions_document["schema"],
        "rows": rows,
    }
