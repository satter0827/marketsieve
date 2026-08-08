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
        "decision-report",
        "experiment-comparison",
        "experiment-run",
        "instrument-universe",
        "portfolio-result",
        "log-record",
        "report-list",
        "review-report",
        "market-snapshot",
        "market-snapshot-comparison",
        "market-snapshot-list",
        "market-snapshot-manifest",
        "market-snapshot-query-result",
        "market-snapshot-security",
        "market-snapshot-security-result",
        "security-research",
        "security-research-list",
        "security-research-manifest",
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
            "market-snapshot-security-result",
            1,
            {
                "schema": "market-snapshot-security-result/v1",
                "snapshot_id": "a" * 64,
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
            "market-snapshot-comparison",
            1,
            {
                "schema": "market-snapshot-comparison/v1",
                "snapshot_id": "a" * 64,
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


@pytest.mark.parametrize(("schema_name", "major"), (("market-snapshot-security-result", 1),))
def test_market_snapshot_row_schemas_accept_corporate_action_mismatch(
    schema_name: str, major: int
) -> None:
    schema = json.loads(
        (SCHEMAS / schema_name / f"v{major}" / "schema.json").read_text(encoding="utf-8")
    )
    document = {
        "schema": "market-snapshot-security-result/v1",
        "snapshot_id": "a" * 64,
        "instrument_id": "XNAS:MSFT",
        "instrument": {
            "mic": "XNAS",
            "symbol": "MSFT",
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            "instrument_type": "equity",
        },
        "provider_symbol": "MSFT",
        "memberships": ["sp500"],
        "retrieved_at": "2026-08-07T00:00:00+00:00",
        "evidence_id": "b" * 64,
        "values": {},
        "missing": {"close": "corporate_action_mismatch"},
    }

    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        document
    )


def test_market_snapshot_comparison_schema_accepts_corporate_action_mismatch() -> None:
    schema = json.loads(
        (SCHEMAS / "market-snapshot-comparison/v1/schema.json").read_text(encoding="utf-8")
    )
    document = {
        "schema": "market-snapshot-comparison/v1",
        "snapshot_id": "a" * 64,
        "fields": ["close"],
        "rows": [
            {
                "instrument_id": "XNAS:MSFT",
                "values": {},
                "missing": {"close": "corporate_action_mismatch"},
            },
            {"instrument_id": "XTKS:7203", "values": {"close": "1"}, "missing": {}},
        ],
    }

    Draft202012Validator(schema).validate(document)


def test_security_research_manifest_rejects_malformed_nested_metadata() -> None:
    schema = json.loads(
        (SCHEMAS / "security-research-manifest/v1/schema.json").read_text(encoding="utf-8")
    )
    document = {
        "schema": "security-research-manifest/v1",
        "research_id": "a" * 64,
        "snapshot_id": "b" * 64,
        "instrument_id": "XNAS:MSFT",
        "provider_symbol": "MSFT",
        "created_at": "2026-08-08T00:00:00+00:00",
        "source": {"name": None, "version": [], "response_hash": "invalid"},
        "request": {
            "source_profile": None,
            "start": 1,
            "end": {},
            "adjustment": "raw",
            "minimum_price_observations": 0,
            "timeout_seconds": 0,
            "max_retries": 0,
            "retry_base_seconds": -1,
        },
        "price_requirements_met": True,
        "artifacts": {str(index): "unexpected" for index in range(12)},
    }

    with pytest.raises(ValidationError):
        Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
            document
        )
