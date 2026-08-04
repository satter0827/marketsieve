"""Explicit non-secret TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceProfile:
    name: str
    daily_bars_plugin: str
    currency: str
    timezone: str
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
        daily = value.get("daily_bars")
        if not isinstance(daily, dict) or not isinstance(daily.get("plugin"), str):
            raise ValueError(f"source profile {name!r} must declare daily_bars.plugin")
        currency = value.get("currency")
        timezone = value.get("timezone")
        if not isinstance(currency, str) or not isinstance(timezone, str):
            raise ValueError(f"source profile {name!r} must declare currency and timezone")
        settings = daily.get("settings", {})
        if not isinstance(settings, dict) or any(
            not isinstance(key, str) or not isinstance(item, (str, int, float))
            for key, item in settings.items()
        ):
            raise ValueError(f"source profile {name!r} daily_bars.settings must be scalar values")
        return SourceProfile(
            name=name,
            daily_bars_plugin=daily["plugin"],
            currency=currency,
            timezone=timezone,
            settings={key: str(item) for key, item in settings.items()},
        )
