"""Deterministic AI analysis context backed by one immutable market matrix."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from marketsieve_cli.adapters.matrices import MatrixStore

ANALYSIS_SCHEMA = "analysis-context/v2"
ANALYSIS_CONSTRAINTS = (
    "Use securities.jsonl as the authoritative security table.",
    "Treat empty values as missing and inspect failures.jsonl for reason codes.",
    "Do not infer missing values or substitute another data source.",
    "Do not generate scores, rankings, or trading recommendations.",
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


class AnalysisWorkspace:
    """Project matrix references for agents without duplicating security rows."""

    def __init__(self, root: Path, matrices: MatrixStore) -> None:
        self._root = root
        self._matrices = matrices
        self._context = root / "context.json"
        self._markdown = root / "analysis.md"

    def build(self, matrix_id: str = "latest") -> dict[str, Any]:
        matrix = self._matrices.show(matrix_id)
        matrix_reference = self._matrix_reference(matrix)
        semantic = {
            "schema": ANALYSIS_SCHEMA,
            "as_of": matrix["created_at"],
            "matrix": matrix_reference,
            "constraints": list(ANALYSIS_CONSTRAINTS),
        }
        document = {
            "context_id": hashlib.sha256(_json_bytes(semantic)).hexdigest(),
            **semantic,
        }
        markdown = render_analysis(document)
        self._ensure_root()
        self._atomic_write(self._context, _json_bytes(document))
        self._atomic_write(self._markdown, markdown.encode())
        return document

    def show(self) -> tuple[dict[str, Any], str]:
        if self._root.parent.is_symlink() or self._root.is_symlink():
            raise ValueError("analysis workspace root must be a real directory")
        if any(path.is_symlink() or not path.is_file() for path in (self._context, self._markdown)):
            raise LookupError("analysis workspace does not exist; run 'marketsieve analysis build'")
        raw = self._context.read_bytes()
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("analysis context is invalid") from error
        if not isinstance(document, dict) or _json_bytes(document) != raw:
            raise ValueError("analysis context is not canonical")
        _validate_analysis_document(document)
        semantic = {key: value for key, value in document.items() if key != "context_id"}
        expected = hashlib.sha256(_json_bytes(semantic)).hexdigest()
        if document["context_id"] != expected:
            raise ValueError("analysis context ID does not match semantic content")
        markdown = self._markdown.read_text(encoding="utf-8")
        if markdown != render_analysis(document):
            raise ValueError("analysis Markdown does not match the canonical context")
        matrix = document["matrix"]
        current = self._matrices.show(matrix["matrix_id"])
        if (
            matrix != self._matrix_reference(current)
            or document["as_of"] != current["created_at"]
            or document["constraints"] != list(ANALYSIS_CONSTRAINTS)
        ):
            raise ValueError("analysis matrix reference is invalid")
        return document, markdown

    def _matrix_reference(self, matrix: dict[str, Any]) -> dict[str, Any]:
        artifacts = matrix["artifacts"]
        return {
            "matrix_id": matrix["matrix_id"],
            "created_at": matrix["created_at"],
            "row_count": matrix["row_count"],
            "field_count": matrix["field_count"],
            "quality_status": matrix["quality_status"],
            "coverage": matrix["coverage"],
            "manifest_path": self._relative(artifacts["manifest.json"]),
            "fields_path": self._relative(artifacts["fields.json"]),
            "index_summary_path": self._relative(artifacts["index-summary.json"]),
            "securities_jsonl_path": self._relative(artifacts["securities.jsonl"]),
            "failures_jsonl_path": self._relative(artifacts["failures.jsonl"]),
        }

    def _relative(self, path: str) -> str:
        return os.path.relpath(Path(path).resolve(), self._root.resolve())

    def _ensure_root(self) -> None:
        if self._root.parent.is_symlink() or (
            self._root.exists() and (self._root.is_symlink() or not self._root.is_dir())
        ):
            raise ValueError("analysis workspace root must be a real directory")
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        if path.is_symlink():
            raise ValueError("analysis workspace path must not be a symbolic link")
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


def render_analysis(document: dict[str, Any]) -> str:
    """Render the compact agent handoff from matrix references only."""

    matrix = document["matrix"]
    coverage = matrix["coverage"]
    lines = [
        "# MarketSieve Analysis Context",
        "",
        f"- Context ID: `{document['context_id']}`",
        f"- Matrix ID: `{matrix['matrix_id']}`",
        f"- Evidence as of: `{document['as_of']}`",
        f"- Securities: {matrix['row_count']}",
        f"- Fields: {matrix['field_count']}",
        f"- Quality status: `{matrix['quality_status']}`",
        f"- Overall price coverage: {coverage['overall']}",
        "",
        "## Authoritative inputs",
        "",
        f"- Security rows: `{matrix['securities_jsonl_path']}`",
        f"- Field definitions: `{matrix['fields_path']}`",
        f"- Index summary: `{matrix['index_summary_path']}`",
        f"- Missing reasons: `{matrix['failures_jsonl_path']}`",
        f"- Manifest: `{matrix['manifest_path']}`",
        "",
        "## Analysis constraints",
        "",
        *(f"- {value}" for value in document["constraints"]),
        "",
    ]
    return "\n".join(lines)


def _validate_analysis_document(document: dict[str, Any]) -> None:
    if set(document) != {"context_id", "schema", "as_of", "matrix", "constraints"}:
        raise ValueError("analysis context structure is invalid")
    if document["schema"] != ANALYSIS_SCHEMA:
        raise ValueError("analysis context schema is unsupported")
    _validate_digest(document["context_id"], "analysis context ID")
    matrix = document["matrix"]
    required = {
        "matrix_id",
        "created_at",
        "row_count",
        "field_count",
        "quality_status",
        "coverage",
        "manifest_path",
        "fields_path",
        "index_summary_path",
        "securities_jsonl_path",
        "failures_jsonl_path",
    }
    if not isinstance(matrix, dict) or set(matrix) != required:
        raise ValueError("analysis matrix reference is invalid")
    _validate_digest(matrix["matrix_id"], "analysis matrix ID")
    if any(
        not isinstance(matrix[key], str)
        for key in (
            "created_at",
            "quality_status",
            "manifest_path",
            "fields_path",
            "index_summary_path",
            "securities_jsonl_path",
            "failures_jsonl_path",
        )
    ):
        raise ValueError("analysis matrix reference values are invalid")
    if any(
        not isinstance(matrix[key], int) or isinstance(matrix[key], bool) or matrix[key] < 0
        for key in ("row_count", "field_count")
    ):
        raise ValueError("analysis matrix counts are invalid")
    coverage = matrix["coverage"]
    if (
        not isinstance(coverage, dict)
        or set(coverage) != {"overall", "indices"}
        or not isinstance(coverage["overall"], str)
        or not isinstance(coverage["indices"], dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in coverage["indices"].items()
        )
    ):
        raise ValueError("analysis matrix coverage is invalid")
    constraints = document["constraints"]
    if (
        not isinstance(constraints, list)
        or not constraints
        or any(not isinstance(value, str) or not value for value in constraints)
        or len(constraints) != len(set(constraints))
    ):
        raise ValueError("analysis constraints are invalid")


def _validate_digest(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} is invalid")
