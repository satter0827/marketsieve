"""Load and validate the machine contracts shipped with the CLI."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

SCHEMA_ID = re.compile(r"^(?P<name>[a-z][a-z0-9-]*)/(?P<version>v[1-9][0-9]*)$")


class SchemaRegistry:
    """Resolve versioned schemas from installed resources or the source tree."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._validators: dict[str, Draft202012Validator] = {}

    def _text(self, schema_id: str) -> str:
        match = SCHEMA_ID.fullmatch(schema_id)
        if match is None:
            raise LookupError(f"invalid schema ID: {schema_id}")
        parts = (match.group("name"), match.group("version"), "schema.json")
        if self._root is not None:
            path = self._root.joinpath(*parts)
            if not path.is_file():
                raise LookupError(f"schema is not registered: {schema_id}")
            return path.read_text(encoding="utf-8")
        installed = resources.files("marketsieve_cli").joinpath("schemas", *parts)
        if installed.is_file():
            return installed.read_text(encoding="utf-8")
        source = Path(__file__).resolve().parents[2].joinpath("schemas", *parts)
        if source.is_file():
            return source.read_text(encoding="utf-8")
        raise LookupError(f"schema is not registered: {schema_id}")

    def validator(self, schema_id: str) -> Draft202012Validator:
        """Return a cached validator for one exact schema ID."""

        if schema_id not in self._validators:
            try:
                schema = json.loads(self._text(schema_id))
                Draft202012Validator.check_schema(schema)
            except (json.JSONDecodeError, SchemaError) as error:
                raise ValueError(f"registered schema is invalid: {schema_id}") from error
            self._validators[schema_id] = Draft202012Validator(
                schema, format_checker=FormatChecker()
            )
        return self._validators[schema_id]

    def validate(self, document: Any, schema_id: str | None = None) -> None:
        """Validate one document without exposing its values in an error."""

        resolved = schema_id
        if resolved is None and isinstance(document, dict):
            value = document.get("schema")
            resolved = value if isinstance(value, str) else None
        if resolved is None:
            raise ValueError("machine document has no schema ID")
        try:
            self.validator(resolved).validate(document)
        except ValidationError as error:
            location = "/".join(str(value) for value in error.absolute_path) or "$"
            raise ValueError(f"document does not match {resolved} at {location}") from error


SCHEMAS = SchemaRegistry()


def validate_document(document: Any, schema_id: str | None = None) -> None:
    """Validate one public machine document."""

    SCHEMAS.validate(document, schema_id)


__all__ = ["SCHEMAS", "SchemaRegistry", "validate_document"]
