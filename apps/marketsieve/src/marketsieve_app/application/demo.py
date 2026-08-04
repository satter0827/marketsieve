"""Offline demo orchestration and structured application results."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from marketsieve.analysis.sma20 import Sma20Result, analyze
from marketsieve.data.daily import Adjustment, DailyBarRequest, DailyBarSource, Provenance
from marketsieve.domain import Instrument

DEMO_AS_OF = datetime(2026, 2, 10, tzinfo=UTC)
SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class DemoMarket:
    """One explicit market/source binding owned by the application."""

    key: str
    instrument: Instrument
    source: DailyBarSource
    start: date
    end: date


@dataclass(frozen=True, slots=True)
class DemoOutcome:
    """Structured result of one market analysis."""

    market: str
    instrument: Instrument
    request: DailyBarRequest
    as_of: datetime
    result: Sma20Result
    provenance: tuple[Provenance, ...]


def serialize(outcome: DemoOutcome) -> dict[str, Any]:
    """Convert an outcome to the versioned machine contract."""

    result = outcome.result
    return {
        "market": outcome.market,
        "instrument": {
            "symbol": outcome.instrument.symbol,
            "mic": outcome.instrument.mic,
            "currency": outcome.instrument.currency,
            "exchange_timezone": outcome.instrument.exchange_timezone.key,
            "instrument_type": outcome.instrument.instrument_type.value,
        },
        "input": {
            "start": outcome.request.start.isoformat(),
            "end": outcome.request.end.isoformat(),
            "as_of": outcome.as_of.isoformat(),
            "adjustment": outcome.request.adjustment.value,
        },
        "observations": {
            "included": result.observation_count,
            "excluded_after_as_of": result.excluded_after_as_of,
        },
        "analysis": {
            "indicator": "SMA20",
            "period": result.period,
            "definition": result.definition,
            "status": result.status.value,
            "current_date": result.current_date.isoformat() if result.current_date else None,
            "current_close": str(result.current_close)
            if result.current_close is not None
            else None,
            "current_sma": str(result.current_sma) if result.current_sma is not None else None,
            "current_state": result.current_state.value if result.current_state else None,
            "previous_state": result.previous_state.value if result.previous_state else None,
            "transition": result.transition,
        },
        "provenance": [
            {"source": item.source, "dataset": item.dataset, "version": item.version}
            for item in outcome.provenance
        ],
        "evidence_id": result.evidence_id,
    }


class DemoService:
    """Combine explicit daily sources with deterministic SMA20 analysis."""

    def __init__(self, markets: tuple[DemoMarket, ...], logger: logging.Logger) -> None:
        self._markets = markets
        self._logger = logger

    def run(self, selected: str) -> dict[str, Any]:
        requested = (
            self._markets
            if selected == "all"
            else tuple(market for market in self._markets if market.key == selected)
        )
        if not requested:
            raise ValueError(f"unsupported demo market: {selected}")
        outcomes = []
        try:
            for market in requested:
                request = DailyBarRequest(
                    instrument=market.instrument,
                    start=market.start,
                    end=market.end,
                    adjustment=Adjustment.RAW,
                )
                series = market.source.load(request, as_of=DEMO_AS_OF)
                result = analyze(series)
                provenance = tuple(dict.fromkeys(bar.provenance for bar in series.bars))
                outcomes.append(
                    DemoOutcome(
                        market=market.key,
                        instrument=market.instrument,
                        request=request,
                        as_of=DEMO_AS_OF,
                        result=result,
                        provenance=provenance,
                    )
                )
                self._logger.info(
                    "offline demo completed",
                    extra={
                        "event_name": "demo.completed",
                        "attributes": {
                            "market": market.key,
                            "status": result.status.value,
                            "observations": result.observation_count,
                            "evidence_id": result.evidence_id,
                        },
                    },
                )
        except (RuntimeError, TypeError, ValueError):
            self._logger.error(
                "offline demo failed",
                extra={"event_name": "demo.failed", "attributes": {"market": selected}},
            )
            raise
        return {"schema_version": SCHEMA_VERSION, "results": [serialize(item) for item in outcomes]}
