"""Canonical storage for instrument universes and screening reports."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from marketsieve import InstrumentUniverse, ScreenCandidate, ScreeningReport
from marketsieve._time import as_utc
from marketsieve.domain import Instrument, InstrumentType
from marketsieve_cli.adapters.reports import _decision_document, _json_bytes, _parse_decision
from marketsieve_extension_api import ImportedInstrumentUniverse


def _instrument_document(instrument: Instrument) -> dict[str, str]:
    return {
        "symbol": instrument.symbol,
        "mic": instrument.mic,
        "currency": instrument.currency,
        "timezone": instrument.exchange_timezone.key,
        "instrument_type": instrument.instrument_type.value,
    }


def universe_document(universe: InstrumentUniverse) -> dict[str, object]:
    return {
        "schema": "instrument-universe/v1",
        "universe_id": universe.universe_id,
        "market": universe.market,
        "source_profile": universe.source_profile,
        "as_of": as_utc(universe.as_of).isoformat(),
        "instruments": [_instrument_document(item) for item in universe.instruments],
        "source_ids": list(universe.source_ids),
        "diagnostics": list(universe.diagnostics),
    }


def screening_document(report: ScreeningReport) -> dict[str, object]:
    return {
        "schema": report.schema_version,
        "report_id": report.report_id,
        "universe_id": report.universe_id,
        "as_of": as_utc(report.as_of).isoformat(),
        "policy": {"name": report.policy_name, "version": report.policy_version},
        "processed_count": report.processed_count,
        "eligible_count": report.eligible_count,
        "candidates": [
            {
                "decision": _decision_document(item.decision),
                "supporting_evidence_count": item.supporting_evidence_count,
            }
            for item in report.candidates
        ],
        "diagnostics": list(report.diagnostics),
    }


class ScreeningStore:
    """Persist immutable screening inputs/results and rebuildable latest references."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._universe_objects = root / "universes" / "objects"
        self._universe_refs = root / "universes" / "refs"
        self._report_objects = root / "reports" / "objects"
        self._report_refs = root / "reports" / "refs"

    def put_universe(self, imported: ImportedInstrumentUniverse) -> InstrumentUniverse:
        diagnostics = set(imported.diagnostics)
        if imported.truncated:
            diagnostics.add(f"acquisition_limit_reached:{imported.request.limit}")
        universe = InstrumentUniverse.create(
            market=imported.request.market,
            source_profile=imported.request.source_profile,
            as_of=imported.retrieved_at,
            instruments=imported.instruments,
            source_ids=(imported.source_hash,),
            diagnostics=tuple(sorted(diagnostics)),
        )
        self._put_object(self._universe_objects, universe.universe_id, universe_document(universe))
        self._put_ref(self._universe_refs, universe.market, "universe_id", universe.universe_id)
        return self.show_universe(universe.universe_id)

    def show_universe(self, universe_id: str) -> InstrumentUniverse:
        document = self._read_object(self._universe_objects, universe_id, "universe")
        try:
            instruments = tuple(
                Instrument.create(
                    symbol=item["symbol"],
                    mic=item["mic"],
                    currency=item["currency"],
                    exchange_timezone=item["timezone"],
                    instrument_type=InstrumentType(item["instrument_type"]),
                )
                for item in document["instruments"]
            )
            universe = InstrumentUniverse.create(
                market=document["market"],
                source_profile=document["source_profile"],
                as_of=datetime.fromisoformat(document["as_of"]),
                instruments=instruments,
                source_ids=tuple(document["source_ids"]),
                diagnostics=tuple(document["diagnostics"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("stored universe is invalid") from error
        if universe.universe_id != universe_id or universe_document(universe) != document:
            raise ValueError("stored universe is not canonical")
        return universe

    def latest_universe(self, market: str) -> InstrumentUniverse:
        return self.show_universe(self._read_ref(self._universe_refs, market, "universe_id"))

    def put_report(self, report: ScreeningReport, *, market: str) -> ScreeningReport:
        self._validate_market(market)
        universe = self.show_universe(report.universe_id)
        if universe.market != market:
            raise ValueError("screening report market must match its universe")
        self._put_object(self._report_objects, report.report_id, screening_document(report))
        self._put_ref(self._report_refs, market, "report_id", report.report_id)
        return self.show_report(report.report_id)

    def show_report(self, report_id: str) -> ScreeningReport:
        document = self._read_object(self._report_objects, report_id, "screening report")
        try:
            policy = document["policy"]
            report = ScreeningReport(
                report_id=document["report_id"],
                schema_version=document["schema"],
                universe_id=document["universe_id"],
                as_of=datetime.fromisoformat(document["as_of"]),
                policy_name=policy["name"],
                policy_version=policy["version"],
                processed_count=document["processed_count"],
                eligible_count=document["eligible_count"],
                candidates=tuple(
                    ScreenCandidate(
                        _parse_decision(item["decision"]), item["supporting_evidence_count"]
                    )
                    for item in document["candidates"]
                ),
                diagnostics=tuple(document["diagnostics"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("stored screening report is invalid") from error
        if report.report_id != report_id or screening_document(report) != document:
            raise ValueError("stored screening report is not canonical")
        return report

    def latest_report(self, market: str) -> ScreeningReport:
        return self.show_report(self._read_ref(self._report_refs, market, "report_id"))

    def resolve_report(self, report_id: str, market: str | None = None) -> ScreeningReport:
        if report_id != "latest":
            return self.show_report(report_id)
        if market is not None:
            return self.latest_report(market)
        candidates: list[ScreeningReport] = []
        for selected in ("jp", "us"):
            with suppress(LookupError):
                candidates.append(self.latest_report(selected))
        if not candidates:
            raise LookupError("no screening report exists")
        return max(candidates, key=lambda item: (item.as_of.timestamp(), item.report_id))

    def _put_object(self, directory: Path, object_id: str, document: object) -> None:
        payload = _json_bytes(document)
        self._ensure_directory(directory)
        destination = directory / f"{object_id}.json"
        if destination.exists():
            if (
                destination.is_symlink()
                or not destination.is_file()
                or destination.read_bytes() != payload
            ):
                raise ValueError("immutable screening artifact conflicts with existing content")
            return
        self._atomic_write(destination, payload)

    def _put_ref(self, directory: Path, market: str, key: str, object_id: str) -> None:
        self._validate_market(market)
        self._ensure_directory(directory)
        self._atomic_write(directory / f"{market}-latest.json", _json_bytes({key: object_id}))

    def _read_object(self, directory: Path, object_id: str, label: str) -> dict[str, Any]:
        self._validate_id(object_id)
        self._require_directory(directory)
        path = directory / f"{object_id}.json"
        if path.is_symlink() or not path.is_file():
            raise LookupError(f"{label} {object_id} does not exist")
        payload = path.read_bytes()
        try:
            document = cast(dict[str, Any], json.loads(payload))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"stored {label} is invalid") from error
        if not isinstance(document, dict) or _json_bytes(document) != payload:
            raise ValueError(f"stored {label} is not canonical")
        return document

    def _read_ref(self, directory: Path, market: str, key: str) -> str:
        self._validate_market(market)
        self._require_directory(directory)
        path = directory / f"{market}-latest.json"
        if path.is_symlink() or not path.is_file():
            raise LookupError(f"latest {market} screening artifact does not exist")
        payload = path.read_bytes()
        value = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {key} or _json_bytes(value) != payload:
            raise ValueError("screening latest reference is invalid")
        object_id = value[key]
        if not isinstance(object_id, str):
            raise ValueError("screening latest reference is invalid")
        return object_id

    def _ensure_directory(self, path: Path) -> None:
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise ValueError("screening root must be a real directory")
        current = self._root
        ancestors = [self._root]
        for part in path.relative_to(self._root).parts:
            current /= part
            ancestors.append(current)
        if any(candidate.is_symlink() for candidate in ancestors):
            raise ValueError("screening storage path must be a real directory")
        path.mkdir(parents=True, exist_ok=True)
        if any(not candidate.is_dir() for candidate in ancestors):
            raise ValueError("screening storage path must be a real directory")

    def _require_directory(self, path: Path) -> None:
        current = self._root
        ancestors = [self._root]
        for part in path.relative_to(self._root).parts:
            current /= part
            ancestors.append(current)
        if any(candidate.is_symlink() or not candidate.is_dir() for candidate in ancestors):
            raise LookupError("screening storage directory does not exist")

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        if path.is_symlink():
            raise ValueError("screening storage path must not be a symbolic link")
        descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _validate_id(value: str) -> None:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("screening object ID must be a lowercase SHA-256 digest")

    @staticmethod
    def _validate_market(market: str) -> None:
        if market not in {"jp", "us"}:
            raise ValueError("market must be jp or us")
