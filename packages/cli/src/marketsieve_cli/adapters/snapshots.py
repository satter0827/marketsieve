"""Immutable content-addressed snapshot persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketsieve_extension_api import ImportedDailyBars

SNAPSHOT_SCHEMA = "marketsieve-snapshot/v1"
NORMALIZED_SCHEMA = "marketsieve-normalized-daily-bars/v1"
INSTRUMENT_KEY = re.compile(r"^[A-Z0-9]{4}:[A-Z0-9]+$")


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
    return {
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


def _identity_document(imported: ImportedDailyBars, normalized: dict[str, Any]) -> dict[str, Any]:
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
        "request": {"bundle_sha256": imported.bundle_hash},
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
            self._write_ref(imported, object_id)
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
        self._write_ref(imported, object_id)
        return StoredSnapshot(object_id, manifest)

    def _write_ref(self, imported: ImportedDailyBars, object_id: str) -> None:
        profile = imported.source_profile
        directory = self._refs / profile
        self._ensure_directory(directory)
        destination = directory / f"{imported.instrument.mic}-{imported.instrument.symbol}.json"
        if destination.is_symlink():
            raise ValueError("snapshot reference must not be a symbolic link")
        payload = _json_bytes({"kind": "daily_bars", "object_id": object_id})
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
        normalized_path = normalized_directory / "daily-bars.json"
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

    def resolve(self, profile: str, instrument: str) -> StoredSnapshot:
        self._validate_profile(profile)
        if INSTRUMENT_KEY.fullmatch(instrument) is None:
            raise ValueError("instrument must use uppercase MIC:SYMBOL form")
        profile_directory = self._refs / profile
        ref = profile_directory / f"{instrument.replace(':', '-')}.json"
        if profile_directory.exists():
            self._require_real_directories(
                self._root.parent, self._root, self._refs, profile_directory
            )
        if not ref.is_file() or ref.is_symlink():
            command = "marketsieve source import PATH"
            raise LookupError(f"snapshot not found; run '{command}' for {profile} {instrument}")
        document = json.loads(ref.read_bytes())
        return self.verify(document["object_id"])

    def normalized(self, object_id: str) -> dict[str, Any]:
        self.verify(object_id)
        normalized_directory = self._objects / object_id / "normalized"
        path = normalized_directory / "daily-bars.json"
        self._require_real_directories(normalized_directory)
        if path.is_symlink() or not path.is_file():
            raise ValueError("normalized snapshot must not be a symbolic link")
        document = json.loads(path.read_bytes())
        if not isinstance(document, dict):
            raise ValueError("normalized snapshot document must be an object")
        return document

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
