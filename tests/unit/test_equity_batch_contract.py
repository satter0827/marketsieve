from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from marketsieve.model import Adjustment
from marketsieve_extension_api import (
    EquityAcquisitionFailure,
    EquityBatchInstrument,
    EquityBatchObservation,
    EquityBatchRequest,
    ImportedEquityBatch,
)
from marketsieve_extension_api.testing import JP_INSTRUMENT, US_INSTRUMENT, fixture_bars


def _request() -> EquityBatchRequest:
    item = EquityBatchInstrument(JP_INSTRUMENT, "7203.T", ("nikkei225", "topix500"))
    return EquityBatchRequest(
        "market-yfinance",
        (item,),
        date(2023, 8, 7),
        date(2026, 8, 7),
        Adjustment.ADJUSTED,
        50,
        2,
        30,
        3,
        2.0,
        {"cache_dir": ".marketsieve/cache/yfinance"},
    )


def _adjusted_bars(dataset: str) -> tuple[Any, ...]:
    return tuple(
        replace(bar, adjustment=Adjustment.ADJUSTED)
        for bar in fixture_bars(JP_INSTRUMENT, ("100", "101"), dataset=dataset)
    )


def test_equity_batch_contract_requires_sorted_complete_observations() -> None:
    request = _request()
    observation = EquityBatchObservation(
        request.instruments[0],
        datetime(2026, 8, 7, tzinfo=UTC),
        _adjusted_bars("batch-contract"),
        (("name", "Toyota"),),
        (("revenue_ttm", "10"),),
        "a" * 64,
    )
    imported = ImportedEquityBatch(
        request,
        "yfinance",
        "1.5.2",
        "fixture",
        observation.retrieved_at,
        (observation,),
        (EquityAcquisitionFailure(JP_INSTRUMENT, "financials", "total_assets", "field_absent"),),
        "b" * 64,
    )

    assert imported.observations == (observation,)
    with pytest.raises(ValueError, match="exactly match every requested"):
        replace(imported, observations=())
    mismatched = replace(
        observation,
        requested=replace(request.instruments[0], provider_symbol="7203"),
    )
    with pytest.raises(ValueError, match="exactly match"):
        replace(imported, observations=(mismatched,))
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(request, instruments=(request.instruments[0], request.instruments[0]))
    with pytest.raises(ValueError, match="positive integers"):
        replace(request, batch_size=0)
    with pytest.raises(ValueError, match="unique, and sorted"):
        replace(request.instruments[0], memberships=("topix500", "nikkei225"))


def test_equity_batch_contract_rejects_invalid_boundary_values() -> None:
    request = _request()
    item = request.instruments[0]
    bars = _adjusted_bars("batch-boundaries")
    observation = EquityBatchObservation(
        item,
        datetime(2026, 8, 7, tzinfo=UTC),
        bars,
        (("name", "Toyota"),),
        (("revenue_ttm", "10"),),
        "a" * 64,
    )
    imported = ImportedEquityBatch(
        request,
        "yfinance",
        "1.5.2",
        "fixture",
        observation.retrieved_at,
        (observation,),
        (),
        "b" * 64,
    )

    with pytest.raises(TypeError, match="must use Instrument"):
        replace(item, instrument=cast(Any, None))
    with pytest.raises(ValueError, match="must not be empty"):
        replace(item, provider_symbol="")
    with pytest.raises(ValueError, match="non-empty"):
        replace(item, memberships=())
    with pytest.raises(TypeError, match="benchmark marker"):
        replace(item, is_benchmark=cast(Any, 1))
    with pytest.raises(ValueError, match="source profile"):
        replace(request, source_profile="")
    with pytest.raises(ValueError, match="requires instruments"):
        replace(request, instruments=())
    with pytest.raises(TypeError, match=r"must use datetime\.date"):
        replace(
            request,
            start=cast(Any, datetime(2023, 8, 7, tzinfo=UTC)),
            end=cast(Any, datetime(2026, 8, 7, tzinfo=UTC)),
        )
    with pytest.raises(ValueError, match="must not exceed"):
        replace(request, start=request.end, end=request.start)
    with pytest.raises(TypeError, match="must use Adjustment"):
        replace(request, adjustment=cast(Any, "adjusted"))
    with pytest.raises(ValueError, match="positive integers"):
        replace(request, timeout_seconds=True)
    for invalid_retry_base in (-1, float("nan"), float("inf"), True, cast(Any, "1")):
        with pytest.raises(ValueError, match="finite non-negative"):
            replace(request, retry_base_seconds=invalid_retry_base)
    with pytest.raises(TypeError, match="map strings"):
        replace(request, settings=cast(Any, {"timeout": 1}))

    failure = EquityAcquisitionFailure(JP_INSTRUMENT, "price", "history", "history_empty")
    with pytest.raises(TypeError, match="must use Instrument"):
        replace(failure, instrument=cast(Any, None))
    with pytest.raises(ValueError, match="must not be empty"):
        replace(failure, field="")
    with pytest.raises(ValueError, match="UTC offset"):
        replace(observation, retrieved_at=datetime(2026, 8, 7))
    with pytest.raises(ValueError, match="unique ascending"):
        replace(observation, bars=(bars[0], bars[0]))
    with pytest.raises(ValueError, match="keys must be unique and sorted"):
        replace(observation, profile=(("z", "1"), ("a", "2")))
    with pytest.raises(ValueError, match="values must not be empty"):
        replace(observation, financials=(("revenue", ""),))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(observation, source_hash="invalid")

    with pytest.raises(ValueError, match="source identity"):
        replace(imported, dataset="")
    with pytest.raises(ValueError, match="UTC offset"):
        replace(imported, retrieved_at=datetime(2026, 8, 7))
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(imported, observations=(observation, observation))
    with pytest.raises(ValueError, match="was not requested"):
        replace(
            imported,
            failures=(
                EquityAcquisitionFailure(US_INSTRUMENT, "price", "history", "history_empty"),
            ),
        )
    with pytest.raises(ValueError, match="inside the requested range"):
        replace(
            imported,
            request=replace(
                request,
                start=bars[-1].trading_date,
                end=bars[-1].trading_date,
            ),
        )
    with pytest.raises(ValueError, match="requested adjustment"):
        replace(imported, request=replace(request, adjustment=Adjustment.RAW))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(imported, response_hash="invalid")
