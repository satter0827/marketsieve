from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from marketsieve import (
    BalancedCandidateScreen,
    DecisionAction,
    DecisionConfidence,
    DecisionEvidence,
    EvidenceDirection,
)
from marketsieve.decision import InstrumentDecision
from marketsieve.domain import Instrument
from marketsieve_cli.adapters.screening import ScreeningStore
from marketsieve_extension_api import ImportedInstrumentUniverse, UniverseRequest


def _instrument(symbol: str = "AAA") -> Instrument:
    return Instrument.create(
        symbol=symbol,
        mic="XNAS",
        currency="USD",
        exchange_timezone="America/New_York",
    )


def _imported(*symbols: str) -> ImportedInstrumentUniverse:
    return ImportedInstrumentUniverse(
        UniverseRequest("offline-us", "us", 100, {}),
        "csv",
        "1.0.0",
        "instrument-universe",
        datetime(2026, 8, 1, tzinfo=UTC),
        tuple(_instrument(symbol) for symbol in sorted(symbols)),
        "a" * 64,
        len(symbols),
        False,
    )


def _decision(instrument: Instrument) -> InstrumentDecision:
    return InstrumentDecision(
        instrument,
        False,
        DecisionAction.BUY_CANDIDATE,
        DecisionConfidence.HIGH,
        (DecisionEvidence("trend_support", EvidenceDirection.SUPPORTING, "up", None),),
        None,
        None,
        None,
        None,
        (),
        (),
        ("trend_change",),
        "review_candidate",
        "balanced_medium_term",
        "1.0.0",
        (),
    )


def test_store_round_trips_immutable_universe_report_and_latest_refs(tmp_path: Path) -> None:
    store = ScreeningStore(tmp_path / "screening")
    universe = store.put_universe(_imported("AAA", "BBB"))
    report = BalancedCandidateScreen().screen(
        universe, (_decision(universe.instruments[0]),), as_of=universe.as_of
    )

    stored = store.put_report(report, market="us")

    assert store.latest_universe("us") == universe
    assert store.latest_report("us") == stored
    assert store.resolve_report("latest") == stored
    assert store.show_report(report.report_id) == report


def test_store_rejects_tampered_objects_and_noncanonical_refs(tmp_path: Path) -> None:
    root = tmp_path / "screening"
    store = ScreeningStore(root)
    universe = store.put_universe(_imported("AAA"))
    path = root / "universes" / "objects" / f"{universe.universe_id}.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match=r"invalid|canonical"):
        store.show_universe(universe.universe_id)

    ref = root / "universes" / "refs" / "us-latest.json"
    ref.write_text('{"universe_id":"' + universe.universe_id + '"}', encoding="utf-8")
    with pytest.raises(ValueError, match="reference"):
        store.latest_universe("us")


def test_store_records_provider_truncation_as_a_stable_diagnostic(tmp_path: Path) -> None:
    imported = _imported("AAA")
    truncated = ImportedInstrumentUniverse(
        UniverseRequest("offline-us", "us", 1, {}),
        imported.source_name,
        imported.source_version,
        imported.dataset,
        imported.retrieved_at,
        imported.instruments,
        imported.source_hash,
        2,
        True,
    )

    universe = ScreeningStore(tmp_path / "screening").put_universe(truncated)

    assert universe.diagnostics == ("acquisition_limit_reached:1",)
