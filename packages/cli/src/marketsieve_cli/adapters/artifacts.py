"""Fault-isolated inventory for immutable evidence objects."""

from __future__ import annotations

import builtins
import json
from datetime import datetime
from pathlib import Path
from typing import Any

CURRENT_SCHEMAS = {
    "snapshot": "market-snapshot-manifest/v8",
    "research": "security-research-manifest/v8",
}
OBJECT_ROOTS = {"snapshot": "market-snapshots", "research": "research"}


class ArtifactInventory:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root

    def list(self, *, object_type: str | None = None, status: str | None = None) -> dict[str, Any]:
        types = (object_type,) if object_type is not None else ("snapshot", "research")
        if any(value not in CURRENT_SCHEMAS for value in types):
            raise ValueError("artifact type must be snapshot or research")
        if status is not None and status not in {"current", "incompatible", "corrupt", "orphan"}:
            raise ValueError("artifact status is unsupported")
        records = [record for value in types for record in self._records(value)]
        if status is not None:
            records = [record for record in records if record["status"] == status]
        records.sort(
            key=lambda item: (item.get("created_at") or "", item["object_id"]), reverse=True
        )
        counts = {
            name: sum(record["status"] == name for record in records)
            for name in ("current", "incompatible", "corrupt", "orphan")
        }
        return {"schema": "artifact-list/v1", "counts": counts, "artifacts": records}

    def doctor(self) -> dict[str, Any]:
        document = self.list()
        return {
            "schema": "artifact-doctor/v1",
            "status": (
                "healthy"
                if not document["counts"]["corrupt"] and not document["counts"]["orphan"]
                else "degraded"
            ),
            "counts": document["counts"],
            "artifacts": document["artifacts"],
        }

    def _records(self, object_type: str) -> builtins.list[dict[str, Any]]:
        root = self.state_root / OBJECT_ROOTS[object_type]
        objects = root / "objects"
        records: builtins.list[dict[str, Any]] = []
        if objects.is_dir() and not objects.is_symlink():
            for path in objects.iterdir():
                if path.name.startswith(".") or path.name == ".DS_Store":
                    continue
                records.append(self._record(object_type, path))
        latest = root / "latest.json"
        if latest.exists() or latest.is_symlink():
            try:
                pointer = json.loads(latest.read_text(encoding="utf-8"))
                object_id = pointer.get("snapshot_id") or pointer.get("research_id")
                if not isinstance(object_id, str) or not (objects / object_id).is_dir():
                    records.append(
                        {
                            "object_type": object_type,
                            "object_id": str(object_id or "latest"),
                            "status": "orphan",
                            "schema": None,
                            "created_at": pointer.get("created_at"),
                            "path": str(latest),
                            "reason": "latest_target_missing",
                        }
                    )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                records.append(
                    {
                        "object_type": object_type,
                        "object_id": "latest",
                        "status": "orphan",
                        "schema": None,
                        "created_at": None,
                        "path": str(latest),
                        "reason": "latest_pointer_invalid",
                    }
                )
        return records

    def _record(self, object_type: str, path: Path) -> dict[str, Any]:
        base = {
            "object_type": object_type,
            "object_id": path.name,
            "path": str(path),
        }
        manifest_path = path / "manifest.json"
        try:
            if path.is_symlink() or not path.is_dir() or manifest_path.is_symlink():
                raise ValueError("object_path_invalid")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest_root_invalid")
            schema = manifest.get("schema")
            created_at = manifest.get("created_at")
            if not isinstance(schema, str) or not isinstance(created_at, str):
                raise ValueError("manifest_metadata_missing")
            datetime.fromisoformat(created_at)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            return {
                **base,
                "status": "corrupt",
                "schema": None,
                "created_at": None,
                "reason": str(error) or type(error).__name__,
            }
        return {
            **base,
            "status": ("current" if schema == CURRENT_SCHEMAS[object_type] else "incompatible"),
            "schema": schema,
            "created_at": created_at,
            "reason": None,
        }
