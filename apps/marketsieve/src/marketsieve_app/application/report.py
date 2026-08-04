"""Historical report orchestration and machine-contract serialization."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from marketsieve.analysis.replay import replay_sma20
from marketsieve.analysis.sma20 import Sma20Result
from marketsieve.data.daily import DailyBarRequest, DailyBarSource
from marketsieve.reporting.sma20 import Sma20ReplayReport, build_sma20_replay_report

REPORT_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ReportMarket:
    """One explicit market, source, request, and evaluation schedule."""

    key: str
    source: DailyBarSource
    request: DailyBarRequest
    as_ofs: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class MarketReport:
    """A report associated with its application market key."""

    market: str
    report: Sma20ReplayReport


@dataclass(frozen=True, slots=True)
class ReportDocument:
    """One channel-neutral application result."""

    reports: tuple[MarketReport, ...]
    schema_version: str = REPORT_SCHEMA_VERSION


class ReportOutput(Protocol):
    """Consume one completed report document."""

    def emit_report(self, document: ReportDocument) -> None: ...


def _analysis_payload(result: Sma20Result) -> dict[str, Any]:
    return {
        "indicator": "SMA20",
        "period": result.period,
        "definition": result.definition,
        "status": result.status.value,
        "current_date": result.current_date.isoformat() if result.current_date else None,
        "current_close": str(result.current_close) if result.current_close is not None else None,
        "current_sma": str(result.current_sma) if result.current_sma is not None else None,
        "current_state": result.current_state.value if result.current_state else None,
        "evidence_id": result.evidence_id,
    }


def serialize_report_document(document: ReportDocument) -> dict[str, Any]:
    """Serialize a report document into its versioned machine contract."""

    reports = []
    for market_report in document.reports:
        report = market_report.report
        instrument = report.request.instrument
        reports.append(
            {
                "market": market_report.market,
                "instrument": {
                    "symbol": instrument.symbol,
                    "mic": instrument.mic,
                    "currency": instrument.currency,
                    "exchange_timezone": instrument.exchange_timezone.key,
                    "instrument_type": instrument.instrument_type.value,
                },
                "input": {
                    "start": report.request.start.isoformat(),
                    "end": report.request.end.isoformat(),
                    "adjustment": report.request.adjustment.value,
                    "first_as_of": report.first_as_of.isoformat(),
                    "last_as_of": report.last_as_of.isoformat(),
                    "evaluation_count": report.evaluation_count,
                },
                "latest": _analysis_payload(report.latest),
                "transitions": [
                    {
                        "as_of": item.as_of.isoformat(),
                        "trading_date": item.trading_date.isoformat(),
                        "previous_state": item.previous_state.value,
                        "current_state": item.current_state.value,
                        "evidence_id": item.evidence_id,
                    }
                    for item in report.transitions
                ],
                "provenance": [
                    {"source": item.source, "dataset": item.dataset, "version": item.version}
                    for item in report.provenance
                ],
                "replay_id": report.replay_id,
                "report_id": report.report_id,
            }
        )
    return {"schema_version": document.schema_version, "reports": reports}


class ReportService:
    """Create and emit deterministic reports for selected markets."""

    def __init__(
        self,
        markets: tuple[ReportMarket, ...],
        output: ReportOutput,
        logger: logging.Logger,
    ) -> None:
        self._markets = markets
        self._output = output
        self._logger = logger

    def run(self, selected: str) -> ReportDocument:
        requested = (
            self._markets
            if selected == "all"
            else tuple(market for market in self._markets if market.key == selected)
        )
        if not requested:
            raise ValueError(f"unsupported report market: {selected}")
        try:
            reports = tuple(
                MarketReport(
                    market.key,
                    build_sma20_replay_report(
                        replay_sma20(market.source, market.request, market.as_ofs)
                    ),
                )
                for market in requested
            )
            document = ReportDocument(reports)
            self._output.emit_report(document)
            for item in reports:
                self._logger.info(
                    "Historical report completed",
                    extra={
                        "event_name": "report.completed",
                        "attributes": {
                            "market": item.market,
                            "report_id": item.report.report_id,
                            "transitions": len(item.report.transitions),
                        },
                    },
                )
            return document
        except (RuntimeError, TypeError, ValueError):
            self._logger.error(
                "Historical report failed",
                extra={"event_name": "report.failed", "attributes": {"market": selected}},
            )
            raise
