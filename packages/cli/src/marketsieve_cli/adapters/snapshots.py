"""Immutable content-addressed snapshot persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from marketsieve.data.daily import Adjustment, DailyBar, Provenance
from marketsieve_extension_api import ImportedDailyBars, ImportedEvents, ImportedFinancials

SNAPSHOT_SCHEMA = "marketsieve-snapshot/v1"
NORMALIZED_SCHEMA = "marketsieve-normalized-daily-bars/v1"
INSTRUMENT_KEY = re.compile(r"^[A-Z0-9]{4}:[A-Z0-9]+$")
SNAPSHOT_KINDS = frozenset({"daily_bars", "financials", "events"})


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _instrument_document(imported: ImportedDailyBars) -> dict[str, str]:
    instrument = imported.instrument
    return {
        "currency": instrument.currency,
        "mic": instrument.mic,
        "symbol": instrument.symbol,
        "timezone": instrument.exchange_timezone.key,
        "type": instrument.instrument_type.value,
    }


def _normalized_document(imported: ImportedDailyBars) -> dict[str, Any]:
    document = {
        "schema": NORMALIZED_SCHEMA,
        "instrument": _instrument_document(imported),
        "adjustment": imported.adjustment.value,
        "bars": [
            {
                "trading_date": bar.trading_date.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": bar.volume,
                "available_at": bar.available_at.isoformat(),
                "provenance": {
                    "source": bar.provenance.source,
                    "dataset": bar.provenance.dataset,
                    "version": bar.provenance.version,
                },
            }
            for bar in imported.bars
        ],
    }
    if imported.instrument_profile is not None:
        profile = imported.instrument_profile
        document["instrument_profile"] = {
            "observation_date": profile.observation_date.isoformat(),
            "published_at": profile.published_at.isoformat() if profile.published_at else None,
            "names": dict(profile.names),
            "attributes": dict(profile.attributes),
        }
    return document


def _identity_document(imported: ImportedDailyBars, normalized: dict[str, Any]) -> dict[str, Any]:
    request = {"mode": "import", "bundle_sha256": imported.bundle_hash}
    if imported.fetch_request is not None:
        fetch = imported.fetch_request
        request = {
            "mode": "fetch",
            "start": fetch.start.isoformat(),
            "end": fetch.end.isoformat(),
            "adjustment": fetch.adjustment.value,
            "response_sha256": imported.bundle_hash,
        }
    return {
        "schema": SNAPSHOT_SCHEMA,
        "kind": "daily_bars",
        "source": {
            "profile": imported.source_profile,
            "name": imported.source_name,
            "version": imported.source_version,
            "dataset": imported.dataset,
        },
        "instrument": _instrument_document(imported),
        "acquisition": {
            "retrieved_at": imported.retrieved_at.isoformat(),
            "availability_basis": imported.availability_basis.value,
        },
        "request": request,
        "normalized": normalized,
    }


def _financial_document(imported: ImportedFinancials) -> dict[str, Any]:
    provenance = {
        "source": imported.source_name,
        "dataset": imported.dataset,
        "version": imported.source_version,
    }
    return {
        "schema": "marketsieve-normalized-financials/v1",
        "instrument": _instrument_document_from_request(imported),
        "facts": [
            {
                "concept": fact.concept,
                "provider_fact": fact.provider_fact,
                "accounting_standard": fact.accounting_standard,
                "period": fact.period.value,
                "fiscal_period_start": fact.fiscal_period_start.isoformat(),
                "fiscal_period_end": fact.fiscal_period_end.isoformat(),
                "published_at": fact.published_at.isoformat() if fact.published_at else None,
                "available_at": fact.available_at.isoformat(),
                "availability_basis": fact.availability_basis.value,
                "consolidation": fact.consolidation.value,
                "revision": fact.revision.value,
                "currency": fact.currency,
                "scale": fact.scale,
                "value": str(fact.value),
                "provenance": provenance,
            }
            for fact in imported.facts
        ],
        "missing_reasons": list(imported.missing_reasons),
    }


def _event_document(imported: ImportedEvents) -> dict[str, Any]:
    provenance = {
        "source": imported.source_name,
        "dataset": imported.dataset,
        "version": imported.source_version,
    }
    return {
        "schema": "marketsieve-normalized-events/v1",
        "instrument": _instrument_document_from_request(imported),
        "events": [
            {
                "type": event.event_type.value,
                "observation_date": event.observation_date.isoformat(),
                "effective_date": event.effective_date.isoformat(),
                "published_at": event.published_at.isoformat() if event.published_at else None,
                "available_at": event.available_at.isoformat(),
                "availability_basis": event.availability_basis.value,
                "values": dict(event.values),
                "provenance": provenance,
            }
            for event in imported.events
        ],
        "missing_reasons": list(imported.missing_reasons),
    }


def _instrument_document_from_request(
    imported: ImportedFinancials | ImportedEvents,
) -> dict[str, str]:
    instrument = imported.request.instrument
    return {
        "currency": instrument.currency,
        "mic": instrument.mic,
        "symbol": instrument.symbol,
        "timezone": instrument.exchange_timezone.key,
        "type": instrument.instrument_type.value,
    }


def _fact_identity(
    imported: ImportedFinancials | ImportedEvents,
    kind: str,
    normalized: dict[str, Any],
) -> dict[str, Any]:
    request = imported.request
    return {
        "schema": SNAPSHOT_SCHEMA,
        "kind": kind,
        "source": {
            "profile": request.source_profile,
            "name": imported.source_name,
            "version": imported.source_version,
            "dataset": imported.dataset,
        },
        "instrument": _instrument_document_from_request(imported),
        "acquisition": {
            "retrieved_at": imported.retrieved_at.isoformat(),
            "availability_basis": "retrieval",
        },
        "request": {
            "mode": "fetch",
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "response_sha256": imported.response_hash,
        },
        "normalized": normalized,
    }


@dataclass(frozen=True, slots=True)
class StoredSnapshot:
    """Identity and manifest of one verified immutable object."""

    object_id: str
    manifest: dict[str, Any]


class SnapshotStore:
    """Persist immutable objects and rebuildable profile references."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._objects = root / "objects"
        self._refs = root / "refs"

    def put_daily_bars(self, imported: ImportedDailyBars) -> StoredSnapshot:
        self._validate_profile(imported.source_profile)
        self._ensure_directory(self._objects)
        normalized = _normalized_document(imported)
        normalized_bytes = _json_bytes(normalized)
        identity = _identity_document(imported, normalized)
        object_id = _sha256(_json_bytes(identity))
        manifest = {key: value for key, value in identity.items() if key != "normalized"}
        manifest.update(
            {
                "object_id": object_id,
                "normalized": {
                    "path": "normalized/daily-bars.json",
                    "sha256": _sha256(normalized_bytes),
                    "observations": len(imported.bars),
                },
                "raw": {"stored": False, "sha256": imported.bundle_hash},
            }
        )
        destination = self._objects / object_id
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise ValueError("snapshot object path must be a real directory")
            stored = self.verify(object_id)
            self._write_ref(
                imported.source_profile,
                imported.instrument.mic,
                imported.instrument.symbol,
                "daily_bars",
                object_id,
            )
            return stored
        temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=self._objects))
        try:
            normalized_dir = temporary / "normalized"
            normalized_dir.mkdir()
            (normalized_dir / "daily-bars.json").write_bytes(normalized_bytes)
            (temporary / "manifest.json").write_bytes(_json_bytes(manifest))
            os.rename(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        self._write_ref(
            imported.source_profile,
            imported.instrument.mic,
            imported.instrument.symbol,
            "daily_bars",
            object_id,
        )
        return StoredSnapshot(object_id, manifest)

    def put_financials(self, imported: ImportedFinancials) -> StoredSnapshot:
        return self._put_facts(imported, "financials", _financial_document(imported))

    def put_events(self, imported: ImportedEvents) -> StoredSnapshot:
        return self._put_facts(imported, "events", _event_document(imported))

    def _put_facts(
        self,
        imported: ImportedFinancials | ImportedEvents,
        kind: str,
        normalized: dict[str, Any],
    ) -> StoredSnapshot:
        request = imported.request
        self._validate_profile(request.source_profile)
        self._ensure_directory(self._objects)
        normalized_bytes = _json_bytes(normalized)
        identity = _fact_identity(imported, kind, normalized)
        object_id = _sha256(_json_bytes(identity))
        manifest = {key: value for key, value in identity.items() if key != "normalized"}
        manifest.update(
            {
                "object_id": object_id,
                "normalized": {
                    "path": f"normalized/{kind}.json",
                    "sha256": _sha256(normalized_bytes),
                    "observations": len(imported.facts)
                    if isinstance(imported, ImportedFinancials)
                    else len(imported.events),
                },
                "raw": {"stored": False, "sha256": imported.response_hash},
            }
        )
        destination = self._objects / object_id
        if not destination.exists():
            temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=self._objects))
            try:
                normalized_dir = temporary / "normalized"
                normalized_dir.mkdir()
                (normalized_dir / f"{kind}.json").write_bytes(normalized_bytes)
                (temporary / "manifest.json").write_bytes(_json_bytes(manifest))
                os.rename(temporary, destination)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        stored = self.verify(object_id)
        self._write_ref(
            request.source_profile,
            request.instrument.mic,
            request.instrument.symbol,
            kind,
            object_id,
        )
        return stored

    def _write_ref(self, profile: str, mic: str, symbol: str, kind: str, object_id: str) -> None:
        self._validate_kind(kind)
        directory = self._refs / profile
        self._ensure_directory(directory)
        suffix = "" if kind == "daily_bars" else f"-{kind}"
        destination = directory / f"{mic}-{symbol}{suffix}.json"
        if destination.is_symlink():
            raise ValueError("snapshot reference must not be a symbolic link")
        payload = _json_bytes({"kind": kind, "object_id": object_id})
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, destination)

    def list(self) -> tuple[StoredSnapshot, ...]:
        if not self._objects.exists():
            return ()
        self._require_real_directories(self._root.parent, self._root, self._objects)
        return tuple(
            self._read_manifest(path.name)
            for path in sorted(self._objects.iterdir())
            if path.is_dir() and not path.name.startswith(".")
        )

    def show(self, object_id: str) -> StoredSnapshot:
        self._validate_id(object_id)
        return self._read_manifest(object_id)

    def verify(self, object_id: str) -> StoredSnapshot:
        stored = self.show(object_id)
        manifest = stored.manifest
        normalized_directory = self._objects / object_id / "normalized"
        normalized_path = self._objects / object_id / self._normalized_path(manifest)
        self._require_real_directories(normalized_directory)
        if normalized_path.is_symlink() or not normalized_path.is_file():
            raise ValueError("normalized snapshot must be a regular file")
        normalized_bytes = normalized_path.read_bytes()
        if _sha256(normalized_bytes) != manifest["normalized"]["sha256"]:
            raise ValueError("normalized snapshot checksum does not match its manifest")
        normalized = json.loads(normalized_bytes)
        identity = {
            key: value
            for key, value in manifest.items()
            if key not in {"object_id", "normalized", "raw"}
        }
        identity["normalized"] = normalized
        if _sha256(_json_bytes(identity)) != object_id:
            raise ValueError("snapshot object ID does not match its canonical content")
        return stored

    def resolve(self, profile: str, instrument: str, kind: str = "daily_bars") -> StoredSnapshot:
        self._validate_profile(profile)
        self._validate_kind(kind)
        if INSTRUMENT_KEY.fullmatch(instrument) is None:
            raise ValueError("instrument must use uppercase MIC:SYMBOL form")
        profile_directory = self._refs / profile
        suffix = "" if kind == "daily_bars" else f"-{kind}"
        ref = profile_directory / f"{instrument.replace(':', '-')}{suffix}.json"
        if profile_directory.exists():
            self._require_real_directories(
                self._root.parent, self._root, self._refs, profile_directory
            )
        if not ref.is_file() or ref.is_symlink():
            command = "marketsieve source import PATH"
            raise LookupError(f"snapshot not found; run '{command}' for {profile} {instrument}")
        document = json.loads(ref.read_bytes())
        if document.get("kind") != kind:
            raise ValueError("snapshot reference kind is invalid")
        return self.verify(document["object_id"])

    def normalized(self, object_id: str) -> dict[str, Any]:
        self.verify(object_id)
        normalized_directory = self._objects / object_id / "normalized"
        manifest = self.show(object_id).manifest
        path = self._objects / object_id / self._normalized_path(manifest)
        self._require_real_directories(normalized_directory)
        if path.is_symlink() or not path.is_file():
            raise ValueError("normalized snapshot must not be a symbolic link")
        document = json.loads(path.read_bytes())
        if not isinstance(document, dict):
            raise ValueError("normalized snapshot document must be an object")
        return document

    def daily_bars(self, object_id: str) -> tuple[DailyBar, ...]:
        """Rebuild validated SDK values from one verified normalized object."""

        document = self.normalized(object_id)
        adjustment = Adjustment(document["adjustment"])
        return tuple(
            DailyBar(
                trading_date=date.fromisoformat(item["trading_date"]),
                open=Decimal(item["open"]),
                high=Decimal(item["high"]),
                low=Decimal(item["low"]),
                close=Decimal(item["close"]),
                volume=item["volume"],
                adjustment=adjustment,
                available_at=datetime.fromisoformat(item["available_at"]),
                provenance=Provenance(
                    item["provenance"]["source"],
                    item["provenance"]["dataset"],
                    item["provenance"]["version"],
                ),
            )
            for item in document["bars"]
        )

    def _read_manifest(self, object_id: str) -> StoredSnapshot:
        directory = self._objects / object_id
        path = directory / "manifest.json"
        if directory.exists():
            self._require_real_directories(self._root.parent, self._root, self._objects, directory)
        if not path.is_file() or path.is_symlink():
            raise LookupError(f"snapshot {object_id} does not exist")
        manifest = json.loads(path.read_bytes())
        if not isinstance(manifest, dict) or manifest.get("object_id") != object_id:
            raise ValueError("snapshot manifest identity is invalid")
        return StoredSnapshot(object_id, manifest)

    @staticmethod
    def _validate_id(object_id: str) -> None:
        if len(object_id) != 64 or any(
            character not in "0123456789abcdef" for character in object_id
        ):
            raise ValueError("snapshot ID must be a lowercase SHA-256 digest")

    @staticmethod
    def _validate_profile(profile: str) -> None:
        if not profile.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "source profile must contain only letters, numbers, dash, or underscore"
            )

    @staticmethod
    def _validate_kind(kind: str) -> None:
        if kind not in SNAPSHOT_KINDS:
            raise ValueError("snapshot kind is not supported")

    @staticmethod
    def _normalized_path(manifest: dict[str, Any]) -> str:
        expected = {
            "daily_bars": "normalized/daily-bars.json",
            "financials": "normalized/financials.json",
            "events": "normalized/events.json",
        }
        kind = manifest.get("kind")
        normalized = manifest.get("normalized")
        if not isinstance(kind, str) or not isinstance(normalized, dict):
            raise ValueError("normalized snapshot path is invalid for its kind")
        path = normalized.get("path")
        if kind not in expected or path != expected[kind]:
            raise ValueError("normalized snapshot path is invalid for its kind")
        return path

    def _ensure_directory(self, path: Path) -> None:
        current = self._root
        descendants: list[Path] = []
        for part in path.relative_to(self._root).parts:
            current /= part
            descendants.append(current)
        state_paths = (self._root.parent, self._root, *descendants)
        if any(candidate.is_symlink() for candidate in state_paths):
            raise ValueError("snapshot state directories must not be symbolic links")
        path.mkdir(parents=True, exist_ok=True)
        if any(not candidate.is_dir() for candidate in state_paths):
            raise ValueError("snapshot state directories must not be symbolic links")

    @staticmethod
    def _require_real_directories(*paths: Path) -> None:
        if any(path.is_symlink() or not path.is_dir() for path in paths):
            raise ValueError("snapshot state directories must not be symbolic links")
