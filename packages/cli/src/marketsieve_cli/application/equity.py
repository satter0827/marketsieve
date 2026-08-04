"""Pure section composition for the offline equity workbench."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from typing import Any

from marketsieve.analysis.indicators import IndicatorResult, IndicatorStatus

NUMERIC_CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)
BASE_FINANCIAL_CONCEPTS = frozenset(
    {
        "revenue",
        "operating_income",
        "net_income",
        "eps",
        "operating_cash_flow",
        "capital_expenditure",
        "assets",
        "equity",
        "interest_bearing_debt",
    }
)
DERIVED_FINANCIAL_CONCEPTS = frozenset(
    {
        "free_cash_flow",
        "revenue_growth",
        "eps_growth",
        "operating_margin",
        "net_margin",
        "roe",
        "roa",
        "equity_ratio",
        "debt_to_equity",
    }
)
VALUATION_CONCEPTS = (
    "trailing_per",
    "pbr",
    "psr",
    "dividend_yield",
    "fcf_yield",
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def canonical(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if not numerator.is_finite() or not denominator.is_finite() or denominator == 0:
        return None
    with localcontext(NUMERIC_CONTEXT):
        return +(numerator / denominator)


def unavailable(reason: str = "not_present_in_snapshot") -> dict[str, Any]:
    return {
        "status": "unavailable",
        "completeness": "0",
        "values": {},
        "warnings": [],
        "missing_reasons": [reason],
        "provenance": [],
        "evidence_id": None,
    }


def completeness(present: int, total: int) -> str:
    if present == 0:
        return "0"
    if present == total:
        return "1"
    with localcontext(NUMERIC_CONTEXT):
        return canonical(Decimal(present) / Decimal(total))


def technical_section(
    indicators: tuple[IndicatorResult, ...], latest: dict[str, Any]
) -> dict[str, Any]:
    documents = {result.name.value: indicator_document(result) for result in indicators}
    available = sum(result.status is IndicatorStatus.OK for result in indicators)
    return {
        "status": "available" if available == len(indicators) else "partial",
        "as_of": latest["available_at"],
        "completeness": completeness(available, len(indicators)),
        "values": documents,
        "warnings": [],
        "missing_reasons": [] if available == len(indicators) else ["insufficient_history"],
        "provenance": [latest["provenance"]],
        "evidence_id": digest([item["evidence_id"] for item in documents.values()]),
    }


def indicator_document(result: IndicatorResult) -> dict[str, Any]:
    return {
        "name": result.name.value,
        "definition_version": result.definition_version,
        "parameters": dict(result.parameters),
        "status": result.status.value,
        "as_of": result.as_of.isoformat() if result.as_of is not None else None,
        "values": dict(result.values),
        "observation_count": result.observation_count,
        "numeric_policy": result.numeric_policy,
        "evidence_id": result.evidence_id,
    }


def financial_section(section: dict[str, Any]) -> dict[str, Any]:
    if section["status"] in {"unavailable", "invalid"}:
        return section
    facts = section["values"]["facts"]
    derived, reasons = _derived_financials(facts)
    present = {
        item["concept"] for item in facts if isinstance(item, dict) and item.get("concept")
    } | set(derived)
    missing = list(dict.fromkeys([*section["missing_reasons"], *reasons]))
    total = len(BASE_FINANCIAL_CONCEPTS | DERIVED_FINANCIAL_CONCEPTS)
    section = {
        **section,
        "status": (
            "available"
            if (BASE_FINANCIAL_CONCEPTS | DERIVED_FINANCIAL_CONCEPTS).issubset(present)
            and not missing
            else "partial"
        ),
        "completeness": completeness(
            len(present & (BASE_FINANCIAL_CONCEPTS | DERIVED_FINANCIAL_CONCEPTS)), total
        ),
        "values": {"facts": facts, "derived": derived},
        "missing_reasons": missing,
    }
    section["evidence_id"] = digest(
        {"input": section["evidence_id"], "derived": derived, "missing": missing}
    )
    return section


def _derived_financials(
    facts: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    groups: dict[tuple[object, ...], dict[str, dict[str, Any]]] = defaultdict(dict)
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("period") != "annual":
            continue
        key = (
            fact.get("fiscal_period_start"),
            fact.get("fiscal_period_end"),
            fact.get("accounting_standard"),
            fact.get("consolidation"),
            fact.get("revision"),
            fact.get("currency"),
        )
        groups[key][str(fact.get("concept"))] = fact
    eligible = [
        (key, values)
        for key, values in groups.items()
        if key[0] is not None and key[2] is not None and key[3] != "unknown" and key[4] != "unknown"
    ]
    eligible.sort(key=lambda item: str(item[0][1]), reverse=True)
    if not eligible:
        return {}, ["compatible_annual_financial_period_not_available"]
    selected_key, current = eligible[0]
    previous = next(
        (
            values
            for candidate, values in eligible[1:]
            if candidate[2:6] == selected_key[2:6]
            and candidate[0] is not None
            and str(candidate[1]) < str(selected_key[0])
        ),
        {},
    )
    derived: dict[str, dict[str, Any]] = {}

    def amount(values: dict[str, dict[str, Any]], concept: str) -> Decimal | None:
        fact = values.get(concept)
        if fact is None:
            return None
        value = Decimal(str(fact["value"]))
        scale = Decimal(int(fact["scale"]))
        with localcontext(NUMERIC_CONTEXT):
            return +(value * scale)

    def add(name: str, value: Decimal | None, inputs: tuple[str, ...]) -> None:
        if value is None or not value.is_finite():
            return
        derived[name] = {
            "value": canonical(value),
            "origin": "marketsieve",
            "definition_version": f"{name}-v1",
            "inputs": list(inputs),
            "period_end": selected_key[1],
            "accounting_standard": selected_key[2],
            "consolidation": selected_key[3],
            "revision": selected_key[4],
            "currency": (
                None
                if name.endswith(("margin", "growth", "ratio"))
                or name in {"roe", "roa", "debt_to_equity"}
                else selected_key[5]
            ),
        }

    revenue = amount(current, "revenue")
    operating_income = amount(current, "operating_income")
    net_income = amount(current, "net_income")
    eps = amount(current, "eps")
    operating_cash_flow = amount(current, "operating_cash_flow")
    capital_expenditure = amount(current, "capital_expenditure")
    assets = amount(current, "assets")
    equity = amount(current, "equity")
    debt = amount(current, "interest_bearing_debt")
    if operating_cash_flow is not None and capital_expenditure is not None:
        with localcontext(NUMERIC_CONTEXT):
            add(
                "free_cash_flow",
                +(operating_cash_flow - abs(capital_expenditure)),
                ("operating_cash_flow", "capital_expenditure"),
            )
    ratio_specs = (
        ("operating_margin", operating_income, revenue, ("operating_income", "revenue")),
        ("net_margin", net_income, revenue, ("net_income", "revenue")),
        ("roe", net_income, equity, ("net_income", "equity")),
        ("roa", net_income, assets, ("net_income", "assets")),
        ("equity_ratio", equity, assets, ("equity", "assets")),
        ("debt_to_equity", debt, equity, ("interest_bearing_debt", "equity")),
    )
    for name, numerator, denominator, inputs in ratio_specs:
        add(
            name,
            ratio(numerator, denominator)
            if numerator is not None and denominator is not None
            else None,
            inputs,
        )
    previous_revenue = amount(previous, "revenue")
    previous_eps = amount(previous, "eps")
    if revenue is not None and previous_revenue is not None:
        with localcontext(NUMERIC_CONTEXT):
            add(
                "revenue_growth",
                ratio(+(revenue - previous_revenue), previous_revenue),
                ("revenue", "previous_revenue"),
            )
    if eps is not None and previous_eps is not None:
        with localcontext(NUMERIC_CONTEXT):
            add(
                "eps_growth",
                ratio(+(eps - previous_eps), abs(previous_eps)),
                ("eps", "previous_eps"),
            )
    reasons = [
        f"{name}_inputs_not_compatible_or_missing"
        for name in sorted(DERIVED_FINANCIAL_CONCEPTS - set(derived))
    ]
    return derived, reasons


def valuation_section(
    instrument: dict[str, Any], price: dict[str, Any], financial: dict[str, Any]
) -> dict[str, Any]:
    raw_profile = instrument.get("profile", {})
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    attributes = profile.get("attributes", {})
    values: dict[str, dict[str, Any]] = {}
    provider_fields = {
        "trailing_per": "trailing_per",
        "pbr": "price_to_book",
        "psr": "price_to_sales_ttm",
        "dividend_yield": "dividend_yield",
    }
    for concept, field in provider_fields.items():
        raw = attributes.get(field) if isinstance(attributes, dict) else None
        if raw in (None, "", "None", "-"):
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            continue
        if value.is_finite():
            values[concept] = {
                "value": canonical(value),
                "origin": "provider",
                "provider_field": field,
            }
    derived = financial.get("values", {}).get("derived", {})
    free_cash_flow = derived.get("free_cash_flow") if isinstance(derived, dict) else None
    market_cap = attributes.get("market_capitalization") if isinstance(attributes, dict) else None
    if isinstance(free_cash_flow, dict) and market_cap not in (None, "", "None", "-"):
        fcf_currency = free_cash_flow.get("currency")
        if fcf_currency == instrument.get("currency"):
            try:
                fcf_yield = ratio(Decimal(str(free_cash_flow["value"])), Decimal(str(market_cap)))
            except (InvalidOperation, ValueError):
                fcf_yield = None
            if fcf_yield is not None:
                values["fcf_yield"] = {
                    "value": canonical(fcf_yield),
                    "origin": "marketsieve",
                    "definition_version": "fcf-yield-v1",
                    "inputs": ["free_cash_flow", "market_capitalization"],
                }
    missing = [f"{name}_not_available" for name in VALUATION_CONCEPTS if name not in values]
    count = len(values)
    evidence = digest(
        {
            "price": price.get("evidence_id"),
            "financial": financial.get("evidence_id"),
            "values": values,
        }
    )
    return {
        "status": "unavailable" if not values else "available" if not missing else "partial",
        "as_of": max(
            value
            for value in (price.get("as_of"), profile.get("available_at"))
            if isinstance(value, str)
        ),
        "completeness": completeness(count, len(VALUATION_CONCEPTS)),
        "values": values,
        "warnings": [],
        "missing_reasons": missing,
        "provenance": [*price.get("provenance", []), *financial.get("provenance", [])],
        "evidence_id": evidence if values else None,
    }


def risk_section(technical: dict[str, Any]) -> dict[str, Any]:
    indicators = technical.get("values", {})
    selected = {
        name: indicators[name]
        for name in ("atr", "period_return", "maximum_drawdown")
        if name in indicators and indicators[name].get("status") == "ok"
    }
    missing = [
        f"{name}_not_available"
        for name in ("atr", "period_return", "maximum_drawdown")
        if name not in selected
    ]
    return {
        "status": "unavailable" if not selected else "available" if not missing else "partial",
        "as_of": technical.get("as_of"),
        "completeness": completeness(len(selected), 3),
        "values": selected,
        "warnings": [],
        "missing_reasons": missing,
        "provenance": technical.get("provenance", []),
        "evidence_id": (
            digest([item["evidence_id"] for item in selected.values()]) if selected else None
        ),
    }


def data_quality_section(sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    names = tuple(name for name in sections if name != "data_quality")
    available = sum(sections[name]["status"] in {"available", "partial"} for name in names)
    warnings = [
        f"{name}:{warning}" for name in names for warning in sections[name].get("warnings", [])
    ]
    missing = [
        f"{name}:{reason}" for name in names for reason in sections[name].get("missing_reasons", [])
    ]
    values = {
        "section_statuses": {name: sections[name]["status"] for name in names},
        "available_sections": available,
        "total_sections": len(names),
    }
    return {
        "status": "available" if available == len(names) and not missing else "partial",
        "completeness": completeness(available, len(names)),
        "values": values,
        "warnings": warnings,
        "missing_reasons": missing,
        "provenance": [],
        "evidence_id": digest({name: sections[name].get("evidence_id") for name in names}),
    }


def report_document(view: dict[str, Any]) -> dict[str, Any]:
    sections = view["sections"]
    summaries = [
        {
            "section": name,
            "status": section["status"],
            "completeness": section["completeness"],
            "evidence_id": section["evidence_id"],
        }
        for name, section in sections.items()
    ]
    payload = {
        "schema_version": "2.0.0",
        "instrument": view["instrument"],
        "source_profile": view["source_profile"],
        "as_of": max(
            section["as_of"] for section in sections.values() if section.get("as_of") is not None
        ),
        "sections": sections,
        "summary": summaries,
        "disclaimer": "Market data and derived indicators only; not investment advice.",
    }
    return {**payload, "report_id": digest(payload)}


def comparison_document(views: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if len(views) < 2:
        raise ValueError("comparison requires at least two instruments")
    as_of = max(
        section["as_of"]
        for view in views
        for section in view["sections"].values()
        if section.get("as_of") is not None
    )
    metrics: list[dict[str, Any]] = []

    def add_metric(
        section_name: str,
        metric: str,
        values: list[object],
        comparable: bool,
        reason: str | None = None,
    ) -> None:
        metrics.append(
            {
                "section": section_name,
                "metric": metric,
                "values": [
                    {
                        "instrument": (
                            f"{view['instrument']['mic']}:{view['instrument']['symbol']}"
                        ),
                        "value": value,
                    }
                    for view, value in zip(views, values, strict=True)
                ],
                "comparable": comparable,
                "reason": reason,
            }
        )

    currencies = {view["instrument"]["currency"] for view in views}
    adjustments = {view["sections"]["price"].get("values", {}).get("adjustment") for view in views}
    closes = [view["sections"]["price"].get("values", {}).get("close") for view in views]
    price_comparable = len(currencies) == 1 and len(adjustments) == 1 and all(closes)
    add_metric(
        "price",
        "close",
        closes,
        price_comparable,
        None if price_comparable else "currency_or_adjustment_not_comparable",
    )
    for metric in ("rsi", "period_return", "maximum_drawdown"):
        documents = [view["sections"]["technical"].get("values", {}).get(metric) for view in views]
        values = [
            next(iter(document["values"].values()))
            if isinstance(document, dict) and document.get("status") == "ok"
            else None
            for document in documents
        ]
        financial_definitions = {
            (
                document.get("definition_version"),
                json.dumps(document.get("parameters"), sort_keys=True),
            )
            for document in documents
            if isinstance(document, dict)
        }
        comparable = all(value is not None for value in values) and len(financial_definitions) == 1
        add_metric(
            "technical",
            metric,
            values,
            comparable,
            None if comparable else "definition_or_value_not_comparable",
        )
    for metric in VALUATION_CONCEPTS:
        entries = [view["sections"]["valuation"].get("values", {}).get(metric) for view in views]
        values = [entry.get("value") if isinstance(entry, dict) else None for entry in entries]
        comparable = all(value is not None for value in values)
        add_metric(
            "valuation",
            metric,
            values,
            comparable,
            None if comparable else "valuation_value_not_available",
        )
    for metric in sorted(DERIVED_FINANCIAL_CONCEPTS):
        entries = [
            view["sections"]["financial"].get("values", {}).get("derived", {}).get(metric)
            for view in views
        ]
        values = [entry.get("value") if isinstance(entry, dict) else None for entry in entries]
        definitions = {
            (
                entry.get("period_end"),
                entry.get("accounting_standard"),
                entry.get("consolidation"),
                entry.get("revision"),
                entry.get("currency"),
            )
            for entry in entries
            if isinstance(entry, dict)
        }
        comparable = all(value is not None for value in values) and len(definitions) == 1
        add_metric(
            "financial",
            metric,
            values,
            comparable,
            None if comparable else "period_scope_or_currency_not_comparable",
        )
    payload = {
        "schema_version": "1.0.0",
        "knowledge_as_of": as_of,
        "source_profile": views[0]["source_profile"],
        "instruments": [view["instrument"] for view in views],
        "metrics": metrics,
        "warnings": ["absolute financial amounts are not ranked or currency-converted"],
    }
    return {**payload, "comparison_id": digest(payload)}
