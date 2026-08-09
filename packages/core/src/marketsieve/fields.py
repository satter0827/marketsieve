"""Stable public field-definition catalog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """Definition of one stable Market Snapshot field."""

    name: str
    group: str
    data_type: str
    unit: str | None
    source: str
    definition: str
    formula: str | None
    period: str | None
    applicable_to: str = "all_equities"
    comparison_scope: str = "same_market_and_currency"
    exclusion_conditions: tuple[str, ...] = ()
    definition_version: str = "market-snapshot-fields/v2"


def field_definitions() -> tuple[FieldDefinition, ...]:
    """Return the complete stable field catalog."""

    from marketsieve._snapshot_fields import field_definitions as build_catalog

    return build_catalog()


__all__ = ["FieldDefinition", "field_definitions"]
