from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).parents[2]
SCHEMAS = ROOT / "packages" / "cli" / "schemas"


def test_public_schemas_are_current_and_valid() -> None:
    paths = sorted(SCHEMAS.glob("*/v*/schema.json"))
    registered_ids = {f"{path.parent.parent.name}/{path.parent.name}" for path in paths}
    runtime_ids = {
        match.group(1)
        for path in (ROOT / "packages").glob("*/src/**/*.py")
        for match in re.finditer(
            r'["\']schema["\']\s*:\s*["\']([a-z][a-z0-9-]*/v[1-9][0-9]*)["\']',
            path.read_text(encoding="utf-8"),
        )
    }

    assert runtime_ids <= registered_ids
    assert len(paths) == len({path.parent.parent.name for path in paths})
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        match = re.fullmatch(
            r"urn:marketsieve:schema:[a-z-]+:([0-9]+\.[0-9]+\.[0-9]+)", schema["$id"]
        )
        assert match and path.parent.name == f"v{match.group(1).partition('.')[0]}"


def test_removed_feature_schemas_do_not_exist() -> None:
    for name in (
        "portfolio-result",
        "watchlist-result",
        "decision-report",
        "experiment-run",
        "source-result",
        "snapshot-result",
    ):
        assert not list((SCHEMAS / name).glob("v*/schema.json"))


@pytest.mark.parametrize(
    ("name", "version", "document"),
    (
        ("market-snapshot", "v9", {"schema": "market-snapshot/v9", "market": {}}),
        (
            "market-snapshot-manifest",
            "v9",
            {"schema": "market-snapshot-manifest/v9", "artifacts": {}},
        ),
        ("market-snapshot-list", "v3", {"schema": "market-snapshot-list/v3", "snapshots": [{}]}),
        (
            "security-research",
            "v9",
            {"schema": "security-research/v9", "quality_summary": {}, "artifacts": {}},
        ),
        (
            "security-research-manifest",
            "v9",
            {"schema": "security-research-manifest/v9", "artifacts": {}},
        ),
        (
            "security-research-list",
            "v3",
            {"schema": "security-research-list/v3", "research": [{}]},
        ),
    ),
)
def test_current_object_schemas_reject_empty_nested_shapes(
    name: str, version: str, document: dict[str, object]
) -> None:
    schema = json.loads((SCHEMAS / name / version / "schema.json").read_text())

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(document)
