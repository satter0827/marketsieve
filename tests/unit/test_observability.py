from __future__ import annotations

import json
import logging
from io import StringIO
from pathlib import Path

from jsonschema import Draft202012Validator

from marketsieve_cli.observability import JsonLogFormatter, configure_logger

ROOT = Path(__file__).parents[2]


def test_json_formatter_emits_stable_structured_fields() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("marketsieve.tests.observability")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "Completed",
        extra={"event_name": "test.completed", "attributes": {"count": 1}},
    )

    payload = json.loads(stream.getvalue())
    assert payload["schema_version"] == "1.0.0"
    assert payload["severity_text"] == "INFO"
    assert payload["event_name"] == "test.completed"
    assert payload["attributes"] == {"count": 1}
    assert payload["resource"] == {"service.name": "marketsieve-cli"}
    assert payload["timestamp"].endswith("Z")
    schema = json.loads(
        (ROOT / "packages/cli/schemas/log-record/v1/schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(payload)


def test_json_formatter_preserves_trace_context() -> None:
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Failed", (), None)
    record.__dict__["trace_id"] = "a" * 32
    record.__dict__["span_id"] = "b" * 16

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["trace_id"] == "a" * 32
    assert payload["span_id"] == "b" * 16


def test_configure_logger_can_write_under_state_directory(tmp_path: Path) -> None:
    logger = configure_logger(level="INFO", write_file=True, state_dir=tmp_path)

    logger.info("Recorded", extra={"event_name": "test.recorded", "attributes": {}})
    for handler in logger.handlers:
        handler.flush()

    logs = tuple((tmp_path / "logs").glob("*.jsonl"))
    assert len(logs) == 1
    assert json.loads(logs[0].read_text(encoding="utf-8"))["event_name"] == "test.recorded"
