"""Explicit non-secret TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceProfile:
    name: str
    currency: str
    timezone: str
    sources: dict[str, SourceBinding]

    @property
    def daily_bars_plugin(self) -> str:
        return self.binding("daily_bars").plugin

    @property
    def settings(self) -> dict[str, str]:
        return self.binding("daily_bars").settings

    def binding(self, kind: str) -> SourceBinding:
        try:
            return self.sources[kind]
        except KeyError:
            raise LookupError(f"source profile {self.name!r} does not configure {kind}") from None


@dataclass(frozen=True, slots=True)
class SourceBinding:
    plugin: str
    settings: dict[str, str]


class Configuration:
    """Load source profiles without environment-driven setting overrides."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._loaded_document: dict[str, Any] | None = None

    def _document(self) -> dict[str, Any]:
        if self._loaded_document is not None:
            return self._loaded_document
        if self.path is None:
            self._loaded_document = {}
            return self._loaded_document
        if not self.path.is_file():
            raise ValueError(f"configuration does not exist: {self.path}")
        try:
            document = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"configuration could not be read: {self.path}") from error
        if not isinstance(document, dict):
            raise ValueError("configuration root must be a TOML table")
        self._loaded_document = document
        return document

    @classmethod
    def resolve(cls, explicit: Path | None) -> Configuration:
        if explicit is not None:
            return cls(explicit)
        local = Path("marketsieve.toml")
        return cls(local if local.is_file() else None)

    def source_profile(self, name: str) -> SourceProfile:
        profiles = self._document().get("source_profiles")
        if not isinstance(profiles, dict) or name not in profiles:
            raise LookupError(
                f"source profile {name!r} is not configured; add it to marketsieve.toml"
            )
        value = profiles[name]
        if not isinstance(value, dict):
            raise ValueError(f"source profile {name!r} must be a TOML table")
        currency = value.get("currency")
        timezone = value.get("timezone")
        if not isinstance(currency, str) or not isinstance(timezone, str):
            raise ValueError(f"source profile {name!r} must declare currency and timezone")
        sources: dict[str, SourceBinding] = {}
        for kind in ("daily_bars", "financials", "events"):
            source = value.get(kind)
            if source is None:
                continue
            if not isinstance(source, dict) or not isinstance(source.get("plugin"), str):
                raise ValueError(f"source profile {name!r} {kind}.plugin must be a string")
            settings = source.get("settings", {})
            if not isinstance(settings, dict) or any(
                not isinstance(key, str) or not isinstance(item, (str, int, float))
                for key, item in settings.items()
            ):
                raise ValueError(f"source profile {name!r} {kind}.settings must be scalar values")
            sources[kind] = SourceBinding(
                plugin=source["plugin"],
                settings={key: str(item) for key, item in settings.items()},
            )
        if not sources:
            raise ValueError(f"source profile {name!r} must configure at least one data kind")
        return SourceProfile(
            name=name,
            currency=currency,
            timezone=timezone,
            sources=sources,
        )
