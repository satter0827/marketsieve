"""Small application-facing values shared by input adapters and use cases."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MatrixConfiguration:
    """Complete operational bounds for one market-matrix run."""

    indices: tuple[str, ...]
    history_days: int
    batch_size: int
    profile_workers: int
    timeout_seconds: int
    max_retries: int
    retry_base_seconds: float
    minimum_overall_price_coverage: Decimal
    minimum_index_price_coverage: Decimal
