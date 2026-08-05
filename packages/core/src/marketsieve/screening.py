"""Deterministic candidate screening over validated local decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from marketsieve._time import as_utc
from marketsieve.analysis.indicators import canonical_decimal
from marketsieve.decision import (
    DecisionAction,
    DecisionConfidence,
    EvidenceDirection,
    InstrumentDecision,
)
from marketsieve.domain import Instrument

_DIGEST_CHARACTERS = frozenset("0123456789abcdef")
_ACTION_PRIORITY = {
    DecisionAction.BUY_CANDIDATE: 0,
    DecisionAction.WAIT_FOR_PULLBACK: 1,
    DecisionAction.WAIT_FOR_EARNINGS: 2,
}
_CONFIDENCE_PRIORITY = {
    DecisionConfidence.HIGH: 0,
    DecisionConfidence.MEDIUM: 1,
    DecisionConfidence.LOW: 2,
}


def _digest(document: object) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _instrument_identity(instrument: Instrument) -> tuple[str, str]:
    return instrument.mic, instrument.symbol


def _instrument_document(instrument: Instrument) -> dict[str, str]:
    return {
        "symbol": instrument.symbol,
        "mic": instrument.mic,
        "currency": instrument.currency,
        "timezone": instrument.exchange_timezone.key,
        "instrument_type": instrument.instrument_type.value,
    }


def _decision_document(decision: InstrumentDecision) -> dict[str, object]:
    return {
        "instrument": _instrument_document(decision.instrument),
        "held": decision.held,
        "action": decision.action.value,
        "confidence": decision.confidence.value,
        "evidence": [
            {
                "code": item.code,
                "direction": item.direction.value,
                "value": item.value,
                "threshold": item.threshold,
                "evidence_ids": list(item.evidence_ids),
            }
            for item in decision.evidence
        ],
        "next_earnings_date": (
            decision.next_earnings_date.isoformat()
            if decision.next_earnings_date is not None
            else None
        ),
        "revenue_growth": (
            canonical_decimal(decision.revenue_growth)
            if decision.revenue_growth is not None
            else None
        ),
        "eps_growth": (
            canonical_decimal(decision.eps_growth) if decision.eps_growth is not None else None
        ),
        "free_cash_flow": (
            canonical_decimal(decision.free_cash_flow)
            if decision.free_cash_flow is not None
            else None
        ),
        "valuation": list(decision.valuation),
        "fundamentals": list(decision.fundamentals),
        "invalidation_conditions": list(decision.invalidation_conditions),
        "next_action": decision.next_action,
        "policy": {
            "name": decision.policy_name,
            "version": decision.policy_version,
            "settings": list(decision.policy_settings),
        },
    }


@dataclass(frozen=True, slots=True)
class InstrumentUniverse:
    """One immutable, exchange-qualified instrument set."""

    universe_id: str
    market: str
    source_profile: str
    as_of: datetime
    instruments: tuple[Instrument, ...]
    source_ids: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.universe_id) != 64 or any(
            character not in _DIGEST_CHARACTERS for character in self.universe_id
        ):
            raise ValueError("universe ID must be a lowercase SHA-256 digest")
        if self.market not in {"jp", "us"}:
            raise ValueError("universe market must be jp or us")
        if not self.source_profile:
            raise ValueError("universe source profile must not be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("universe as_of must include a UTC offset")
        identities = tuple(_instrument_identity(item) for item in self.instruments)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("universe instruments must be unique and sorted")
        if not self.instruments:
            raise ValueError("universe must contain at least one instrument")
        if (
            self.source_ids != tuple(sorted(self.source_ids))
            or len(self.source_ids) != len(set(self.source_ids))
            or any(not value for value in self.source_ids)
        ):
            raise ValueError("universe source IDs must be non-empty, unique, and sorted")
        if (
            self.diagnostics != tuple(sorted(self.diagnostics))
            or any(not value for value in self.diagnostics)
            or len(set(self.diagnostics)) != len(self.diagnostics)
        ):
            raise ValueError("universe diagnostics must be non-empty, unique, and sorted")
        expected = _digest(self._identity_document())
        if self.universe_id != expected:
            raise ValueError("universe ID does not match its semantic content")

    def _identity_document(self) -> dict[str, object]:
        return {
            "schema": "instrument-universe/v1",
            "market": self.market,
            "source_profile": self.source_profile,
            "as_of": as_utc(self.as_of).isoformat(),
            "instruments": [_instrument_document(item) for item in self.instruments],
            "source_ids": list(self.source_ids),
            "diagnostics": list(self.diagnostics),
        }

    @classmethod
    def create(
        cls,
        *,
        market: str,
        source_profile: str,
        as_of: datetime,
        instruments: tuple[Instrument, ...],
        source_ids: tuple[str, ...],
        diagnostics: tuple[str, ...] = (),
    ) -> InstrumentUniverse:
        ordered = tuple(sorted(instruments, key=_instrument_identity))
        partial = cls.__new__(cls)
        object.__setattr__(partial, "market", market)
        object.__setattr__(partial, "source_profile", source_profile)
        object.__setattr__(partial, "as_of", as_of)
        object.__setattr__(partial, "instruments", ordered)
        object.__setattr__(partial, "source_ids", tuple(sorted(source_ids)))
        object.__setattr__(partial, "diagnostics", tuple(sorted(diagnostics)))
        object.__setattr__(partial, "universe_id", _digest(partial._identity_document()))
        partial.__post_init__()
        return partial


@dataclass(frozen=True, slots=True)
class ScreenCandidate:
    """One visible candidate with a transparent ordering input."""

    decision: InstrumentDecision
    supporting_evidence_count: int

    def __post_init__(self) -> None:
        if self.decision.held:
            raise ValueError("screen candidates must not be held instruments")
        if self.decision.action not in _ACTION_PRIORITY:
            raise ValueError("screen candidate action is not eligible")
        expected = sum(
            item.direction is EvidenceDirection.SUPPORTING for item in self.decision.evidence
        )
        if self.supporting_evidence_count != expected:
            raise ValueError("supporting evidence count does not match the decision")


@dataclass(frozen=True, slots=True)
class ScreeningReport:
    """Immutable candidate result; storage and rendering live outside the SDK."""

    report_id: str
    schema_version: str
    universe_id: str
    as_of: datetime
    policy_name: str
    policy_version: str
    processed_count: int
    eligible_count: int
    candidates: tuple[ScreenCandidate, ...]
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.report_id) != 64 or any(
            character not in _DIGEST_CHARACTERS for character in self.report_id
        ):
            raise ValueError("screening report ID must be a lowercase SHA-256 digest")
        if self.schema_version != "screening-report/v1":
            raise ValueError("unsupported screening report schema")
        if len(self.universe_id) != 64 or any(
            character not in _DIGEST_CHARACTERS for character in self.universe_id
        ):
            raise ValueError("screening universe ID must be a lowercase SHA-256 digest")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("screening as_of must include a UTC offset")
        if not self.policy_name or not self.policy_version:
            raise ValueError("screening policy identity must not be empty")
        if self.processed_count < 0 or not 0 <= self.eligible_count <= self.processed_count:
            raise ValueError("screening counts are inconsistent")
        if len(self.candidates) > self.eligible_count:
            raise ValueError("visible candidates must not exceed eligible candidates")
        if tuple(self.candidates) != tuple(sorted(self.candidates, key=_candidate_order)):
            raise ValueError("screening candidates must use the stable policy order")
        if any(not value for value in self.diagnostics) or len(set(self.diagnostics)) != len(
            self.diagnostics
        ):
            raise ValueError("screening diagnostics must be non-empty and unique")
        if self.report_id != _digest(self._identity_document()):
            raise ValueError("screening report ID does not match its semantic content")

    def _identity_document(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "universe_id": self.universe_id,
            "as_of": as_utc(self.as_of).isoformat(),
            "policy": {"name": self.policy_name, "version": self.policy_version},
            "processed_count": self.processed_count,
            "eligible_count": self.eligible_count,
            "candidates": [
                {
                    "decision": _decision_document(item.decision),
                    "supporting_evidence_count": item.supporting_evidence_count,
                }
                for item in self.candidates
            ],
            "diagnostics": list(self.diagnostics),
        }


@runtime_checkable
class ScreenPolicy(Protocol):
    name: str
    version: str

    def screen(
        self,
        universe: InstrumentUniverse,
        decisions: tuple[InstrumentDecision, ...],
        *,
        as_of: datetime,
        processing_limit: int = 100,
        display_limit: int = 20,
    ) -> ScreeningReport: ...


@dataclass(frozen=True, slots=True)
class BalancedCandidateScreen:
    """Keep actionable non-held decisions without inventing an opaque score."""

    name = "balanced_candidate"
    version = "1.0.0"

    def screen(
        self,
        universe: InstrumentUniverse,
        decisions: tuple[InstrumentDecision, ...],
        *,
        as_of: datetime,
        processing_limit: int = 100,
        display_limit: int = 20,
    ) -> ScreeningReport:
        if processing_limit <= 0 or display_limit <= 0:
            raise ValueError("screening limits must be positive")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("screening as_of must include a UTC offset")
        allowed = {_instrument_identity(item) for item in universe.instruments[:processing_limit]}
        identities = tuple(_instrument_identity(item.instrument) for item in decisions)
        if len(identities) != len(set(identities)):
            raise ValueError("screening decisions must have unique instruments")
        if not set(identities) <= allowed:
            raise ValueError("screening decisions must belong to the processed universe")
        eligible = tuple(
            ScreenCandidate(
                item,
                sum(e.direction is EvidenceDirection.SUPPORTING for e in item.evidence),
            )
            for item in decisions
            if not item.held and item.action in _ACTION_PRIORITY
        )
        ordered = tuple(sorted(eligible, key=_candidate_order))
        diagnostics = tuple(
            message
            for condition, message in (
                (
                    len(universe.instruments) > processing_limit,
                    f"processing_limit_reached:{processing_limit}",
                ),
                (len(ordered) > display_limit, f"display_limit_reached:{display_limit}"),
            )
            if condition
        )
        visible = ordered[:display_limit]
        partial = ScreeningReport.__new__(ScreeningReport)
        values = {
            "schema_version": "screening-report/v1",
            "universe_id": universe.universe_id,
            "as_of": as_of,
            "policy_name": self.name,
            "policy_version": self.version,
            "processed_count": len(decisions),
            "eligible_count": len(ordered),
            "candidates": visible,
            "diagnostics": diagnostics,
        }
        for name, value in values.items():
            object.__setattr__(partial, name, value)
        object.__setattr__(partial, "report_id", _digest(partial._identity_document()))
        partial.__post_init__()
        return partial


def _candidate_order(candidate: ScreenCandidate) -> tuple[int, int, int, str, str]:
    decision = candidate.decision
    return (
        _ACTION_PRIORITY[decision.action],
        _CONFIDENCE_PRIORITY[decision.confidence],
        -candidate.supporting_evidence_count,
        decision.instrument.mic,
        decision.instrument.symbol,
    )
