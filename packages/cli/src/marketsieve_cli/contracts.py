"""Small application-facing values shared by input adapters and use cases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScreeningConfiguration:
    source_profile: str
    plugin: str
    operation: str
    settings: dict[str, str]
    acquisition_limit: int
    processing_limit: int
    display_limit: int
