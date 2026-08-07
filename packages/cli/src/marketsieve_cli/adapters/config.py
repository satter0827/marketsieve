"""Explicit non-secret TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from marketsieve_cli.contracts import MatrixConfiguration


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


DEFAULT_DAILY_LOOKBACK_DAYS = 400
DEFAULT_FINANCIAL_LOOKBACK_DAYS = 1500
DEFAULT_WEEKLY_MAX_AGE_DAYS = 7
DEFAULT_MATRIX_INDICES = ("dow30", "nasdaq100", "nikkei225", "sp500", "topix500")
DEFAULT_MATRIX_HISTORY_DAYS = 1095
DEFAULT_MATRIX_BATCH_SIZE = 50
DEFAULT_MATRIX_PROFILE_WORKERS = 2
DEFAULT_MATRIX_TIMEOUT_SECONDS = 30
DEFAULT_MATRIX_MAX_RETRIES = 3
DEFAULT_MATRIX_RETRY_BASE_SECONDS = 2.0
DEFAULT_MATRIX_MINIMUM_OVERALL_PRICE_COVERAGE = Decimal("0.95")
DEFAULT_MATRIX_MINIMUM_INDEX_PRICE_COVERAGE = Decimal("0.90")


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

    def matrix_configuration(self) -> MatrixConfiguration:
        """Return zero-configuration defaults or one validated matrix table."""

        value = self._document().get("matrix", {})
        if not isinstance(value, dict):
            raise ValueError("matrix configuration must be a TOML table")
        allowed = {
            "indices",
            "history_days",
            "batch_size",
            "profile_workers",
            "timeout_seconds",
            "max_retries",
            "retry_base_seconds",
            "minimum_overall_price_coverage",
            "minimum_index_price_coverage",
        }
        if unknown := set(value) - allowed:
            raise ValueError(
                f"matrix configuration contains unsupported settings: {sorted(unknown)}"
            )
        raw_indices = value.get("indices", list(DEFAULT_MATRIX_INDICES))
        if (
            not isinstance(raw_indices, list)
            or not raw_indices
            or any(
                not isinstance(item, str) or item not in DEFAULT_MATRIX_INDICES
                for item in raw_indices
            )
            or len(raw_indices) != len(set(raw_indices))
        ):
            raise ValueError("matrix indices must be a unique non-empty list of built-in index IDs")

        def integer(name: str, default: int, minimum: int, maximum: int) -> int:
            result = value.get(name, default)
            if (
                not isinstance(result, int)
                or isinstance(result, bool)
                or not minimum <= result <= maximum
            ):
                raise ValueError(
                    f"matrix {name} must be an integer from {minimum} through {maximum}"
                )
            return result

        retry_base = value.get("retry_base_seconds", DEFAULT_MATRIX_RETRY_BASE_SECONDS)
        if (
            not isinstance(retry_base, (int, float))
            or isinstance(retry_base, bool)
            or not 0 <= retry_base <= 60
        ):
            raise ValueError("matrix retry_base_seconds must be a number from 0 through 60")

        def coverage(name: str, default: Decimal) -> Decimal:
            try:
                result = Decimal(str(value.get(name, default)))
            except (InvalidOperation, ValueError):
                raise ValueError(f"matrix {name} must be a decimal ratio") from None
            if not result.is_finite():
                raise ValueError(f"matrix {name} must be a finite decimal ratio")
            if not Decimal("0") <= result <= Decimal("1"):
                raise ValueError(f"matrix {name} must be from 0 through 1")
            return result

        return MatrixConfiguration(
            indices=tuple(sorted(raw_indices)),
            history_days=integer("history_days", DEFAULT_MATRIX_HISTORY_DAYS, 400, 4000),
            batch_size=integer("batch_size", DEFAULT_MATRIX_BATCH_SIZE, 1, 250),
            profile_workers=integer("profile_workers", DEFAULT_MATRIX_PROFILE_WORKERS, 1, 8),
            timeout_seconds=integer("timeout_seconds", DEFAULT_MATRIX_TIMEOUT_SECONDS, 1, 120),
            max_retries=integer("max_retries", DEFAULT_MATRIX_MAX_RETRIES, 1, 10),
            retry_base_seconds=float(retry_base),
            minimum_overall_price_coverage=coverage(
                "minimum_overall_price_coverage",
                DEFAULT_MATRIX_MINIMUM_OVERALL_PRICE_COVERAGE,
            ),
            minimum_index_price_coverage=coverage(
                "minimum_index_price_coverage",
                DEFAULT_MATRIX_MINIMUM_INDEX_PRICE_COVERAGE,
            ),
        )
