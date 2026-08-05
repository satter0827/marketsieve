"""Explicit non-secret TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketsieve_cli.contracts import ScreeningConfiguration


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
    operation: str | None = None


@dataclass(frozen=True, slots=True)
class ScreeningProfile:
    source_profile: str
    acquisition_limit: int
    processing_limit: int
    display_limit: int


@dataclass(frozen=True, slots=True)
class AgentProvider:
    name: str
    model: str
    endpoint: str | None = None


DEFAULT_DAILY_LOOKBACK_DAYS = 400
DEFAULT_FINANCIAL_LOOKBACK_DAYS = 1500
DEFAULT_WEEKLY_MAX_AGE_DAYS = 7
DEFAULT_SCREEN_ACQUISITION_LIMIT = 100
DEFAULT_SCREEN_PROCESSING_LIMIT = 100
DEFAULT_SCREEN_DISPLAY_LIMIT = 20


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
        for kind in ("daily_bars", "financials", "events", "instrument_universe"):
            source = value.get(kind)
            if source is None:
                continue
            if not isinstance(source, dict) or not isinstance(source.get("plugin"), str):
                raise ValueError(f"source profile {name!r} {kind}.plugin must be a string")
            settings = source.get("settings", {})
            operation = source.get("operation")
            unknown = set(source) - {"plugin", "settings", "operation"}
            if unknown:
                raise ValueError(f"source profile {name!r} {kind} contains unsupported settings")
            if operation is not None and operation not in {"import", "fetch"}:
                raise ValueError(
                    f"source profile {name!r} {kind}.operation must be import or fetch"
                )
            if kind == "instrument_universe" and operation is None:
                raise ValueError(
                    f"source profile {name!r} instrument_universe.operation is required"
                )
            if kind != "instrument_universe" and operation is not None:
                raise ValueError(f"source profile {name!r} {kind}.operation is not supported")
            if not isinstance(settings, dict) or any(
                not isinstance(key, str) or not isinstance(item, (str, int, float))
                for key, item in settings.items()
            ):
                raise ValueError(f"source profile {name!r} {kind}.settings must be scalar values")
            sources[kind] = SourceBinding(
                plugin=source["plugin"],
                settings={key: str(item) for key, item in settings.items()},
                operation=operation,
            )
        if not sources:
            raise ValueError(f"source profile {name!r} must configure at least one data kind")
        return SourceProfile(
            name=name,
            currency=currency,
            timezone=timezone,
            sources=sources,
        )

    def agent_provider(self, name: str) -> AgentProvider:
        agent = self._document().get("agent", {})
        if not isinstance(agent, dict):
            raise ValueError("agent configuration must be a TOML table")
        providers = agent.get("providers", {})
        if not isinstance(providers, dict) or name not in providers:
            raise LookupError(
                f"agent provider {name!r} is not configured; add it to marketsieve.toml"
            )
        value = providers[name]
        if not isinstance(value, dict) or not isinstance(value.get("model"), str):
            raise ValueError(f"agent provider {name!r} must declare model")
        endpoint = value.get("endpoint")
        if endpoint is not None and not isinstance(endpoint, str):
            raise ValueError(f"agent provider {name!r} endpoint must be a string")
        unknown = set(value) - {"model", "endpoint"}
        if unknown:
            raise ValueError(f"agent provider {name!r} contains unsupported settings")
        return AgentProvider(name=name, model=value["model"], endpoint=endpoint)

    def daily_profile(self, market: str) -> tuple[str, int, int]:
        """Return the explicit source profile and bounded history for one market."""

        if market not in {"jp", "us"}:
            raise ValueError("market must be jp or us")
        routines = self._document().get("routines")
        if not isinstance(routines, dict):
            raise LookupError(
                "daily routines are not configured; add [routines.jp] and [routines.us]"
            )
        value = routines.get(market)
        if not isinstance(value, dict) or not isinstance(value.get("source_profile"), str):
            raise LookupError(f"daily routine {market!r} must declare source_profile")
        unknown = set(value) - {
            "source_profile",
            "lookback_days",
            "financial_lookback_days",
        }
        if unknown:
            raise ValueError(f"daily routine {market!r} contains unsupported settings")
        lookback = value.get("lookback_days", DEFAULT_DAILY_LOOKBACK_DAYS)
        if (
            not isinstance(lookback, int)
            or isinstance(lookback, bool)
            or not 60 <= lookback <= 2000
        ):
            raise ValueError("daily lookback_days must be an integer from 60 through 2000")
        financial_lookback = value.get("financial_lookback_days", DEFAULT_FINANCIAL_LOOKBACK_DAYS)
        if (
            not isinstance(financial_lookback, int)
            or isinstance(financial_lookback, bool)
            or not 365 <= financial_lookback <= 4000
        ):
            raise ValueError(
                "daily financial_lookback_days must be an integer from 365 through 4000"
            )
        return value["source_profile"], lookback, financial_lookback

    def weekly_max_age_days(self) -> int:
        """Return the maximum age accepted for each daily input report."""

        routines = self._document().get("routines", {})
        if not isinstance(routines, dict):
            raise ValueError("routines configuration must be a TOML table")
        value = routines.get("weekly", {})
        if not isinstance(value, dict):
            raise ValueError("weekly routine must be a TOML table")
        unknown = set(value) - {"max_age_days"}
        if unknown:
            raise ValueError("weekly routine contains unsupported settings")
        maximum = value.get("max_age_days", DEFAULT_WEEKLY_MAX_AGE_DAYS)
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 14:
            raise ValueError("weekly max_age_days must be an integer from 1 through 14")
        return maximum

    def screening_profile(self, market: str) -> ScreeningProfile:
        """Return one explicit universe profile and bounded screening budgets."""

        if market not in {"jp", "us"}:
            raise ValueError("market must be jp or us")
        screening = self._document().get("screening")
        if not isinstance(screening, dict):
            raise LookupError("screening is not configured; add [screening.jp] and [screening.us]")
        value = screening.get(market)
        if not isinstance(value, dict) or not isinstance(value.get("source_profile"), str):
            raise LookupError(f"screening profile {market!r} must declare source_profile")
        unknown = set(value) - {
            "source_profile",
            "acquisition_limit",
            "processing_limit",
            "display_limit",
        }
        if unknown:
            raise ValueError(f"screening profile {market!r} contains unsupported settings")
        acquisition = self._bounded_screen_limit(
            value.get("acquisition_limit", DEFAULT_SCREEN_ACQUISITION_LIMIT),
            "acquisition_limit",
            1000,
        )
        processing = self._bounded_screen_limit(
            value.get("processing_limit", DEFAULT_SCREEN_PROCESSING_LIMIT),
            "processing_limit",
            1000,
        )
        display = self._bounded_screen_limit(
            value.get("display_limit", DEFAULT_SCREEN_DISPLAY_LIMIT),
            "display_limit",
            100,
        )
        return ScreeningProfile(value["source_profile"], acquisition, processing, display)

    def screening_configuration(self, market: str) -> ScreeningConfiguration:
        """Resolve one complete screening operation without leaking configuration structure."""

        screening = self.screening_profile(market)
        profile = self.source_profile(screening.source_profile)
        binding = profile.binding("instrument_universe")
        assert binding.operation is not None
        return ScreeningConfiguration(
            source_profile=profile.name,
            plugin=binding.plugin,
            operation=binding.operation,
            settings=dict(binding.settings),
            acquisition_limit=screening.acquisition_limit,
            processing_limit=screening.processing_limit,
            display_limit=screening.display_limit,
        )

    @staticmethod
    def _bounded_screen_limit(value: object, name: str, maximum: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
            raise ValueError(f"screening {name} must be an integer from 1 through {maximum}")
        return value
