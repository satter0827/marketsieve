from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketsieve_cli.schema_registry import SchemaRegistry


def test_registry_resolves_exact_schema_and_sanitizes_validation_errors(tmp_path: Path) -> None:
    path = tmp_path / "example" / "v1"
    path.mkdir(parents=True)
    path.joinpath("schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "urn:marketsieve:schema:example:1.0.0",
                "type": "object",
                "required": ["schema", "value"],
                "properties": {
                    "schema": {"const": "example/v1"},
                    "value": {"type": "integer"},
                },
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    registry = SchemaRegistry(tmp_path)

    registry.validate({"schema": "example/v1", "value": 1})
    with pytest.raises(ValueError, match=r"example/v1 at value") as error:
        registry.validate({"schema": "example/v1", "value": "private value"})

    assert "private value" not in str(error.value)


@pytest.mark.parametrize("schema_id", ("example", "Example/v1", "../example/v1", "example/v0"))
def test_registry_rejects_invalid_or_unregistered_ids(tmp_path: Path, schema_id: str) -> None:
    with pytest.raises(LookupError):
        SchemaRegistry(tmp_path).validator(schema_id)


def test_installed_registry_contains_the_current_snapshot_contract() -> None:
    validator = SchemaRegistry().validator("market-snapshot/v9")

    assert isinstance(validator.schema, dict)
    assert validator.schema["$id"] == "urn:marketsieve:schema:market-snapshot:9.0.0"
