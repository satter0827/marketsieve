"""Content-addressed persistence for optional report explanations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

REPORT_EXPLANATION_SCHEMA = "report-explanation/v1"


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


class ExplanationStore:
    """Store model output separately from immutable decision-report objects."""

    def __init__(self, root: Path, *, schema: str = REPORT_EXPLANATION_SCHEMA) -> None:
        self._root = root
        self._objects = root / "objects"
        self._schema = schema

    def put(self, value: dict[str, Any]) -> dict[str, Any]:
        if {"schema", "explanation_id"} & set(value):
            raise ValueError("explanation semantic content contains a reserved field")
        semantic = {"schema": self._schema, **value}
        explanation_id = hashlib.sha256(_json_bytes(semantic)).hexdigest()
        document = {"explanation_id": explanation_id, **semantic}
        payload = _json_bytes(document)
        self._ensure_directory()
        path = self._objects / f"{explanation_id}.json"
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ValueError("immutable explanation artifact conflicts with existing content")
        else:
            self._write_atomic(path, payload)
        return document

    def show(self, explanation_id: str) -> dict[str, Any]:
        self._validate_id(explanation_id)
        if self._root.is_symlink() or self._objects.is_symlink() or not self._objects.is_dir():
            raise LookupError("explanation storage directory does not exist")
        path = self._objects / f"{explanation_id}.json"
        if path.is_symlink() or not path.is_file():
            raise LookupError(f"explanation {explanation_id} does not exist")
        document = json.loads(path.read_bytes())
        if not isinstance(document, dict) or document.get("schema") != self._schema:
            raise ValueError("stored explanation is invalid")
        stored_id = document.get("explanation_id")
        semantic = {key: value for key, value in document.items() if key != "explanation_id"}
        expected = hashlib.sha256(_json_bytes(semantic)).hexdigest()
        if (
            stored_id != explanation_id
            or expected != explanation_id
            or _json_bytes(document) != path.read_bytes()
        ):
            raise ValueError("stored explanation is not canonical")
        return document

    def _ensure_directory(self) -> None:
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise ValueError("explanation root must be a real directory")
        self._root.mkdir(parents=True, exist_ok=True)
        if self._objects.exists() and (self._objects.is_symlink() or not self._objects.is_dir()):
            raise ValueError("explanation object path must be a real directory")
        self._objects.mkdir(exist_ok=True)

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_id(value: str) -> None:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("explanation ID must be a lowercase SHA-256 digest")
