from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).parents[2]
SCHEMAS = ROOT / "schemas"


def test_schemas_are_draft_2020_12_and_semantically_versioned() -> None:
    paths = sorted(SCHEMAS.glob("*/v*/schema.json"))
    assert {path.parent.parent.name for path in paths} == {
        "capabilities-result",
        "cli-error",
        "doctor-result",
        "inspect-result",
        "indicator-result",
        "log-record",
        "report-result",
        "review-report",
        "snapshot-result",
        "source-result",
    }

    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        identifier = re.fullmatch(
            r"urn:marketsieve:schema:[a-z-]+:([0-9]+\.[0-9]+\.[0-9]+)", schema["$id"]
        )
        assert identifier is not None
        assert schema["properties"]["schema_version"]["const"] == identifier.group(1)
        assert path.parent.name == f"v{identifier.group(1).partition('.')[0]}"


def test_schemas_reject_unknown_major_versions() -> None:
    for path in SCHEMAS.glob("*/v*/schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        version = schema["properties"]["schema_version"]["const"]
        major = int(version.partition(".")[0])
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate({"schema_version": f"{major + 1}.0.0"})
