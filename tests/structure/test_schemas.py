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
        "agent-result",
        "capabilities-result",
        "cli-error",
        "comparison-result",
        "doctor-result",
        "decision-report",
        "experiment-comparison",
        "experiment-explanation",
        "experiment-run",
        "inspect-result",
        "indicator-result",
        "instrument-universe",
        "portfolio-result",
        "log-record",
        "report-result",
        "report-list",
        "review-report",
        "screening-report",
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
        if "schema_version" in schema["properties"]:
            assert schema["properties"]["schema_version"]["const"] == identifier.group(1)
        else:
            major = identifier.group(1).partition(".")[0]
            assert schema["properties"]["schema"]["const"] == f"{path.parent.parent.name}/v{major}"
        assert path.parent.name == f"v{identifier.group(1).partition('.')[0]}"


def test_schemas_reject_unknown_major_versions() -> None:
    for path in SCHEMAS.glob("*/v*/schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        version_property = (
            "schema_version" if "schema_version" in schema["properties"] else "schema"
        )
        major = int(path.parent.name.removeprefix("v"))
        invalid = f"{major + 1}.0.0"
        if version_property == "schema":
            invalid = f"{path.parent.parent.name}/v{major + 1}"
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate({version_property: invalid})
