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
        "analysis-context",
        "capabilities-result",
        "cli-error",
        "doctor-result",
        "decision-report",
        "experiment-comparison",
        "experiment-run",
        "instrument-universe",
        "portfolio-result",
        "log-record",
        "report-list",
        "review-report",
        "market-matrix",
        "market-matrix-comparison",
        "market-matrix-manifest",
        "market-matrix-row",
        "market-matrix-security",
        "snapshot-result",
        "source-result",
        "watchlist-result",
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


@pytest.mark.parametrize(
    ("schema_name", "major", "document"),
    (
        (
            "watchlist-result",
            2,
            {
                "watchlist_id": "a" * 64,
                "schema": "watchlist-result/v2",
                "as_of": "2026-08-07T00:00:00+00:00",
                "previous_watchlist_id": None,
                "change": None,
                "items": [{"key": "XNAS:MSFT", "instrument": {}}],
            },
        ),
        (
            "market-matrix-row",
            1,
            {
                "schema": "market-matrix-row/v1",
                "matrix_id": "a" * 64,
                "instrument_id": "XNAS:MSFT",
                "instrument": {},
                "provider_symbol": "MSFT",
                "memberships": ["sp500"],
                "retrieved_at": "2026-08-07T00:00:00+00:00",
                "evidence_id": "b" * 64,
                "values": {"close": "100"},
                "missing": {},
            },
        ),
        (
            "market-matrix-comparison",
            1,
            {
                "schema": "market-matrix-comparison/v1",
                "matrix_id": "a" * 64,
                "fields": ["close"],
                "rows": [
                    {"instrument_id": "XNAS:MSFT", "values": {}, "missing": {}},
                    {"instrument_id": "XTKS:7203", "values": {}, "missing": {}},
                ],
            },
        ),
    ),
)
def test_replacement_schemas_reject_empty_nested_contracts(
    schema_name: str, major: int, document: dict[str, object]
) -> None:
    schema = json.loads(
        (SCHEMAS / schema_name / f"v{major}" / "schema.json").read_text(encoding="utf-8")
    )

    with pytest.raises(ValidationError):
        Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
            document
        )
