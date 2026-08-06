"""Immutable local persistence for manual AI exchange artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ARTIFACTS = {
    "request": ("report-ai-request/v1", "request_id"),
    "response": ("report-ai-response/v1", "response_id"),
    "validation": ("report-ai-validation/v1", "validation_id"),
    "explanation": ("report-ai-explanation/v1", "explanation_id"),
}


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        + b"\n"
    )


def semantic_digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


class AiExchangeStore:
    """Store each request, response, validation, and explanation independently."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, kind: str, value: dict[str, Any]) -> dict[str, Any]:
        schema, id_field = self._artifact(kind)
        content = dict(value)
        declared_schema = content.pop("schema", schema)
        if declared_schema != schema:
            raise ValueError(f"AI {kind} uses an unexpected schema")
        if id_field in content:
            raise ValueError(f"AI {kind} semantic content contains a reserved field")
        semantic = {"schema": schema, **content}
        object_id = semantic_digest(semantic)
        document = {id_field: object_id, **semantic}
        path = self.path(kind, object_id)
        self._ensure_directory(path.parent)
        payload = canonical_bytes(document)
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ValueError(f"immutable AI {kind} conflicts with existing content")
        else:
            self._write_atomic(path, payload)
        if kind in {"request", "explanation"}:
            self._write_ref(f"latest-{kind}", object_id)
        return document

    def show(self, kind: str, object_id: str) -> dict[str, Any]:
        schema, id_field = self._artifact(kind)
        selected = self.resolve_ref(f"latest-{kind}") if object_id == "latest" else object_id
        self._validate_id(selected)
        path = self.path(kind, selected)
        if path.is_symlink() or not path.is_file():
            raise LookupError(f"AI {kind} {selected} does not exist")
        payload = path.read_bytes()
        document = json.loads(payload)
        if not isinstance(document, dict) or document.get("schema") != schema:
            raise ValueError(f"stored AI {kind} is not canonical")
        stored_id = document.get(id_field)
        semantic = {key: value for key, value in document.items() if key != id_field}
        expected = semantic_digest(semantic)
        if stored_id != selected or expected != selected or canonical_bytes(document) != payload:
            raise ValueError(f"stored AI {kind} is not canonical")
        return document

    def path(self, kind: str, object_id: str) -> Path:
        self._artifact(kind)
        return self.root / kind / "objects" / f"{object_id}.json"

    def response_path(self, request_id: str) -> Path:
        self._validate_id(request_id)
        inbox = self.root / "inbox"
        self._ensure_directory(inbox)
        return inbox / f"{request_id}.response.json"

    def next_trial(self, request_id: str) -> int:
        self._validate_id(request_id)
        directory = self.root / "response" / "objects"
        if not directory.is_dir() or directory.is_symlink():
            return 1
        trials = []
        for path in directory.glob("*.json"):
            if path.is_symlink() or not path.is_file():
                raise ValueError("stored AI response is not canonical")
            document = self.show("response", path.stem)
            if isinstance(document, dict) and document.get("request_id") == request_id:
                trial = document.get("trial")
                if isinstance(trial, int) and not isinstance(trial, bool):
                    trials.append(trial)
        return max(trials, default=0) + 1

    def resolve_ref(self, name: str) -> str:
        path = self.root / "refs" / f"{name}.json"
        if path.is_symlink() or not path.is_file():
            raise LookupError(f"AI {name} reference does not exist")
        document = json.loads(path.read_bytes())
        if not isinstance(document, dict) or set(document) != {"object_id"}:
            raise ValueError(f"AI {name} reference is invalid")
        object_id = document["object_id"]
        if not isinstance(object_id, str):
            raise ValueError(f"AI {name} reference is invalid")
        self._validate_id(object_id)
        return object_id

    def _write_ref(self, name: str, object_id: str) -> None:
        refs = self.root / "refs"
        self._ensure_directory(refs)
        self._write_atomic(refs / f"{name}.json", canonical_bytes({"object_id": object_id}))

    def _ensure_directory(self, path: Path) -> None:
        if any(ancestor.is_symlink() for ancestor in (self.root, *self.root.parents)):
            raise ValueError("AI storage root must not traverse a symbolic link")
        if self.root.exists() and not self.root.is_dir():
            raise ValueError("AI storage root must be a real directory")
        self.root.mkdir(parents=True, exist_ok=True)
        if (
            self.root.is_symlink()
            or not self.root.is_dir()
            or self.root.resolve() != self.root.absolute()
        ):
            raise ValueError("AI storage root must be a real directory")
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            raise ValueError("AI storage path must remain below its root") from None
        current = self.root
        for part in relative.parts:
            current /= part
            if current.exists() or current.is_symlink():
                if current.is_symlink() or not current.is_dir():
                    raise ValueError("AI storage path must be a real directory")
            else:
                current.mkdir()

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_id(value: str) -> None:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("AI object ID must be a lowercase SHA-256 digest")

    @staticmethod
    def _artifact(kind: str) -> tuple[str, str]:
        try:
            return ARTIFACTS[kind]
        except KeyError:
            raise ValueError(f"unsupported AI artifact kind: {kind}") from None
