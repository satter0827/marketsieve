"""Operational settings kept separate from per-run analytical inputs."""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from marketsieve_cli.contracts import (
    MarketQualitySettings,
    ResearchQualitySettings,
    RuntimeSettings,
    YFinanceSettings,
)


class Settings:
    """Load optional non-secret runtime settings with strict keys."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._loaded: dict[str, Any] | None = None

    @classmethod
    def resolve(cls, explicit: Path | None) -> Settings:
        if explicit is not None:
            return cls(explicit)
        local = Path("marketsieve.settings.toml")
        return cls(local if local.is_file() else None)

    def runtime(self) -> RuntimeSettings:
        document = self._document()
        unknown = set(document) - {"yfinance", "quality"}
        if unknown:
            raise ValueError(f"settings contain unsupported tables: {sorted(unknown)}")
        yfinance = self._table(document, "yfinance")
        quality = self._table(document, "quality")
        unknown_quality = set(quality) - {"market", "research"}
        if unknown_quality:
            raise ValueError(
                f"quality settings contain unsupported tables: {sorted(unknown_quality)}"
            )
        market = self._table(quality, "market")
        research = self._table(quality, "research")
        self._reject_unknown(
            yfinance,
            {
                "batch_size",
                "company_workers",
                "timeout_seconds",
                "max_retries",
                "retry_base_seconds",
            },
            "yfinance",
        )
        self._reject_unknown(
            market,
            {"minimum_overall_price_coverage", "minimum_index_price_coverage"},
            "quality.market",
        )
        self._reject_unknown(
            research,
            {"minimum_price_observations"},
            "quality.research",
        )
        return RuntimeSettings(
            yfinance=YFinanceSettings(
                batch_size=self._integer(yfinance, "batch_size", 50, 1, 250),
                company_workers=self._integer(yfinance, "company_workers", 2, 1, 8),
                timeout_seconds=self._integer(yfinance, "timeout_seconds", 30, 1, 120),
                max_retries=self._integer(yfinance, "max_retries", 3, 1, 10),
                retry_base_seconds=self._number(yfinance, "retry_base_seconds", 2.0, 0.0, 60.0),
            ),
            market_quality=MarketQualitySettings(
                minimum_overall_price_coverage=self._ratio(
                    market, "minimum_overall_price_coverage", Decimal("0.95")
                ),
                minimum_index_price_coverage=self._ratio(
                    market, "minimum_index_price_coverage", Decimal("0.90")
                ),
            ),
            research_quality=ResearchQualitySettings(
                minimum_price_observations=self._integer(
                    research, "minimum_price_observations", 252, 1, 5000
                )
            ),
        )

    def effective_document(self) -> dict[str, Any]:
        settings = self.runtime()
        return {
            "yfinance": {
                "batch_size": settings.yfinance.batch_size,
                "company_workers": settings.yfinance.company_workers,
                "timeout_seconds": settings.yfinance.timeout_seconds,
                "max_retries": settings.yfinance.max_retries,
                "retry_base_seconds": str(settings.yfinance.retry_base_seconds),
            },
            "quality": {
                "market": {
                    "minimum_overall_price_coverage": str(
                        settings.market_quality.minimum_overall_price_coverage
                    ),
                    "minimum_index_price_coverage": str(
                        settings.market_quality.minimum_index_price_coverage
                    ),
                },
                "research": {
                    "minimum_price_observations": (
                        settings.research_quality.minimum_price_observations
                    )
                },
            },
        }

    def effective_hash(self) -> str:
        payload = json.dumps(
            self.effective_document(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def _document(self) -> dict[str, Any]:
        if self._loaded is not None:
            return self._loaded
        if self.path is None:
            self._loaded = {}
            return self._loaded
        if not self.path.is_file():
            raise ValueError(f"settings file does not exist: {self.path}")
        try:
            value = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"settings file could not be read: {self.path}") from error
        if not isinstance(value, dict):
            raise ValueError("settings root must be a TOML table")
        self._loaded = value
        return value

    @staticmethod
    def _table(document: dict[str, Any], name: str) -> dict[str, Any]:
        value = document.get(name, {})
        if not isinstance(value, dict):
            raise ValueError(f"{name} settings must be a TOML table")
        return value

    @staticmethod
    def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
        if unknown := set(value) - allowed:
            raise ValueError(f"{label} settings contain unsupported keys: {sorted(unknown)}")

    @staticmethod
    def _integer(value: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
        result = value.get(name, default)
        if (
            not isinstance(result, int)
            or isinstance(result, bool)
            or not minimum <= result <= maximum
        ):
            raise ValueError(f"{name} must be an integer from {minimum} through {maximum}")
        return result

    @staticmethod
    def _number(
        value: dict[str, Any], name: str, default: float, minimum: float, maximum: float
    ) -> float:
        result = value.get(name, default)
        if not isinstance(result, (int, float)) or isinstance(result, bool):
            raise ValueError(f"{name} must be a number")
        number = float(result)
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f"{name} must be from {minimum} through {maximum}")
        return number

    @staticmethod
    def _ratio(value: dict[str, Any], name: str, default: Decimal) -> Decimal:
        try:
            result = Decimal(str(value.get(name, default)))
        except (InvalidOperation, ValueError):
            raise ValueError(f"{name} must be a decimal ratio") from None
        if not result.is_finite() or not Decimal(0) <= result <= Decimal(1):
            raise ValueError(f"{name} must be from 0 through 1")
        return result
