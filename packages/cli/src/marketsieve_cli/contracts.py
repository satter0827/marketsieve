"""Typed invocation inputs and stable runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

MARKET_EVIDENCE = ("benchmarks", "company", "financials", "price")
RESEARCH_EVIDENCE = ("benchmarks", "company", "events", "financials", "price")
MARKET_INDICES = ("dow30", "nasdaq100", "nikkei225", "sp500", "topix500")
MARKET_INDEX_GROUPS = {
    "jp": ("nikkei225", "topix500"),
    "us": ("dow30", "nasdaq100", "sp500"),
}


@dataclass(frozen=True, slots=True)
class YFinanceSettings:
    batch_size: int = 50
    company_workers: int = 2
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_base_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class MarketQualitySettings:
    minimum_overall_price_coverage: Decimal = Decimal("0.95")
    minimum_index_price_coverage: Decimal = Decimal("0.90")


@dataclass(frozen=True, slots=True)
class ResearchQualitySettings:
    minimum_price_observations: int = 252


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    yfinance: YFinanceSettings = YFinanceSettings()
    market_quality: MarketQualitySettings = MarketQualitySettings()
    research_quality: ResearchQualitySettings = ResearchQualitySettings()


@dataclass(frozen=True, slots=True)
class MarketBuildInputs:
    indices: tuple[str, ...]
    evidence: tuple[str, ...]
    history_days: int | None

    def __post_init__(self) -> None:
        if not self.indices or self.indices != tuple(sorted(set(self.indices))):
            raise ValueError("market indices must be a unique sorted non-empty tuple")
        if set(self.indices) - set(MARKET_INDICES):
            raise ValueError("market indices contain an unsupported index")
        if not self.evidence or self.evidence != tuple(sorted(set(self.evidence))):
            raise ValueError("market evidence must be a unique sorted non-empty tuple")
        if set(self.evidence) - set(MARKET_EVIDENCE):
            raise ValueError("market evidence contains an unsupported domain")
        needs_history = bool({"price", "benchmarks"} & set(self.evidence))
        if "benchmarks" in self.evidence and "price" not in self.evidence:
            raise ValueError("market benchmark evidence requires price evidence")
        if needs_history and self.history_days is None:
            raise ValueError("market price evidence requires --history-days")
        if self.history_days is not None and not 30 <= self.history_days <= 3653:
            raise ValueError("market history days must be from 30 through 3653")


@dataclass(frozen=True, slots=True)
class ResearchBuildInputs:
    snapshot_id: str
    instrument_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    history_days: int | None

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.instrument_ids:
            raise ValueError("research snapshot and instruments are required")
        if self.instrument_ids != tuple(dict.fromkeys(self.instrument_ids)):
            raise ValueError("research instruments must be unique")
        if not self.evidence or self.evidence != tuple(sorted(set(self.evidence))):
            raise ValueError("research evidence must be a unique sorted non-empty tuple")
        if set(self.evidence) - set(RESEARCH_EVIDENCE):
            raise ValueError("research evidence contains an unsupported domain")
        needs_history = bool({"price", "benchmarks", "events"} & set(self.evidence))
        if "benchmarks" in self.evidence and "price" not in self.evidence:
            raise ValueError("research benchmark evidence requires price evidence")
        if needs_history and self.history_days is None:
            raise ValueError("research time-series evidence requires --history-days")
        if self.history_days is not None and not 30 <= self.history_days <= 3653:
            raise ValueError("research history days must be from 30 through 3653")
