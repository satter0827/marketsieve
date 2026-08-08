"""Small application-facing values shared by input adapters and use cases."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MarketConfiguration:
    """Complete operational bounds for one Market Snapshot run."""

    indices: tuple[str, ...]
    history_days: int
    batch_size: int
    profile_workers: int
    timeout_seconds: int
    max_retries: int
    retry_base_seconds: float
    minimum_overall_price_coverage: Decimal
    minimum_index_price_coverage: Decimal


@dataclass(frozen=True, slots=True)
class ResearchConfiguration:
    """Operational bounds for one yfinance security research build."""

    history_days: int
    minimum_price_observations: int
    timeout_seconds: int
    max_retries: int
    retry_base_seconds: float
