from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from marketsieve_cli.contracts import (
    MarketBuildInputs,
    MarketCompareInputs,
    MarketDiffInputs,
    MarketQueryInputs,
    PreviewInputs,
    ResearchBuildInputs,
)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: MarketBuildInputs((), ("company",), None),
        lambda: MarketBuildInputs(("unknown",), ("company",), None),
        lambda: MarketBuildInputs(("dow30",), (), None),
        lambda: MarketBuildInputs(("dow30",), ("unknown",), None),
        lambda: MarketBuildInputs(("dow30",), ("benchmarks",), 365),
        lambda: MarketBuildInputs(("dow30",), ("price",), None),
        lambda: MarketBuildInputs(("dow30",), ("price",), 29),
        lambda: MarketBuildInputs(("dow30",), ("company",), None, mode="unknown"),
        lambda: MarketBuildInputs(("dow30",), ("company",), None, as_of=date(2026, 1, 1)),
        lambda: MarketBuildInputs(
            ("dow30",), ("price",), 365, mode="historical_price_reconstruction"
        ),
        lambda: MarketBuildInputs(
            ("dow30",),
            ("company",),
            None,
            as_of=date(2026, 1, 1),
            mode="historical_price_reconstruction",
        ),
        lambda: MarketBuildInputs(("dow30",), ("company",), None, session="open"),
    ),
)
def test_market_build_contract_rejects_invalid_combinations(factory: Callable[[], Any]) -> None:
    with pytest.raises(ValueError):
        factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: ResearchBuildInputs("", ("XNAS:MSFT",), ("company",), None),
        lambda: ResearchBuildInputs("latest", ("XNAS:MSFT", "XNAS:MSFT"), ("company",), None),
        lambda: ResearchBuildInputs("latest", ("XNAS:MSFT",), (), None),
        lambda: ResearchBuildInputs("latest", ("XNAS:MSFT",), ("unknown",), None),
        lambda: ResearchBuildInputs("latest", ("XNAS:MSFT",), ("benchmarks",), 365),
        lambda: ResearchBuildInputs("latest", ("XNAS:MSFT",), ("price",), None),
        lambda: ResearchBuildInputs("latest", ("XNAS:MSFT",), ("price",), 29),
    ),
)
def test_research_contract_rejects_invalid_combinations(factory: Callable[[], Any]) -> None:
    with pytest.raises(ValueError):
        factory()


def _query(**changes: Any) -> MarketQueryInputs:
    values: dict[str, Any] = {
        "snapshot_id": "latest",
        "filters": {},
        "minimums": {},
        "maximums": {},
        "present": (),
        "missing": (),
        "fields": (),
    }
    values.update(changes)
    return MarketQueryInputs(**values)


@pytest.mark.parametrize(
    "changes",
    (
        {"snapshot_id": ""},
        {"limit": 0},
        {"domains": ("unknown",)},
        {"domains": ("risk", "risk")},
        {"profile": "unknown"},
        {"budget": Decimal("NaN"), "budget_currency": "JPY"},
        {"budget": Decimal("-1"), "budget_currency": "JPY"},
        {"budget": Decimal("100")},
        {"trading_unit": 0},
    ),
)
def test_query_contract_rejects_invalid_combinations(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _query(**changes)


def test_compare_diff_and_preview_contracts_validate_at_boundary() -> None:
    MarketCompareInputs("latest", ("XNAS:A", "XNAS:B"), ())
    MarketDiffInputs("left", "right", ())
    PreviewInputs("latest", 0)
    with pytest.raises(ValueError, match="at least two"):
        MarketCompareInputs("latest", ("XNAS:A",), ())
    with pytest.raises(ValueError, match="unique"):
        MarketCompareInputs("latest", ("XNAS:A", "XNAS:A"), ())
    with pytest.raises(ValueError, match="snapshot"):
        MarketCompareInputs("", ("XNAS:A", "XNAS:B"), ())
    with pytest.raises(ValueError, match="required"):
        MarketDiffInputs("", "right", ())
    with pytest.raises(ValueError, match="object"):
        PreviewInputs("")
    with pytest.raises(ValueError, match="port"):
        PreviewInputs("latest", 65536)
