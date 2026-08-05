from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from marketsieve.domain import Instrument
from marketsieve_extension_api import ImportedInstrumentUniverse, UniverseRequest


def instrument(symbol: str = "MSFT") -> Instrument:
    return Instrument.create(
        symbol=symbol,
        mic="XNAS",
        currency="USD",
        exchange_timezone="America/New_York",
    )


def request(*, limit: int = 2) -> UniverseRequest:
    return UniverseRequest("sec-us", "us", limit, {})


def imported() -> ImportedInstrumentUniverse:
    return ImportedInstrumentUniverse(
        request(),
        "sec",
        "v1",
        "company_tickers_exchange",
        datetime(2026, 8, 1, tzinfo=UTC),
        (instrument(),),
        "a" * 64,
        1,
        False,
    )


@pytest.mark.parametrize(
    "value",
    (
        UniverseRequest("sec-us", "us", 1, {}),
        UniverseRequest("japan", "jp", 100, {"timeout_seconds": "10"}),
    ),
)
def test_universe_request_accepts_explicit_markets_and_limits(value: UniverseRequest) -> None:
    assert value.limit > 0


@pytest.mark.parametrize(
    ("values", "message"),
    (
        (("", "us", 1), "profile"),
        (("sec-us", "eu", 1), "market"),
        (("sec-us", "us", 0), "positive"),
        (("sec-us", "us", True), "positive"),
    ),
)
def test_universe_request_rejects_implicit_or_unbounded_input(
    values: tuple[str, str, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        UniverseRequest(*values, {})


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"source_name": ""}, "identity"),
        ({"retrieved_at": datetime(2026, 8, 1)}, "UTC offset"),
        ({"source_hash": "bad"}, "SHA-256"),
        ({"instruments": ()}, "non-empty"),
        ({"instruments": (instrument("ZZZ"), instrument("AAA"))}, "sorted"),
        ({"instruments": (instrument(), instrument())}, "unique"),
        (
            {"request": request(limit=1), "instruments": (instrument("A"), instrument("B"))},
            "exceeds",
        ),
        ({"provider_total": 0}, "cover"),
        ({"provider_total": 2, "truncated": False}, "truncation"),
        ({"diagnostics": ("same", "same")}, "diagnostics"),
    ),
)
def test_imported_universe_rejects_noncanonical_results(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(imported(), **cast(Any, changes))
