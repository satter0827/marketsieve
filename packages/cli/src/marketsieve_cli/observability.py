"""Structured logging configuration owned by the repository application."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG_SCHEMA_VERSION = "1.0.0"
LOGGER_NAME = "marketsieve"
SERVICE_NAME = "marketsieve-cli"
DEFAULT_STATE_DIR = Path(".marketsieve")


class JsonLogFormatter(logging.Formatter):
    """Render a stable OpenTelemetry-aligned JSON Lines record."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = (
            datetime.fromtimestamp(record.created, tz=UTC).isoformat().replace("+00:00", "Z")
        )
        payload: dict[str, Any] = {
            "schema_version": LOG_SCHEMA_VERSION,
            "timestamp": timestamp,
            "severity_text": record.levelname,
            "body": record.getMessage(),
            "event_name": getattr(record, "event_name", record.name),
            "attributes": getattr(record, "attributes", {}),
            "resource": {"service.name": SERVICE_NAME},
        }
        trace_id = getattr(record, "trace_id", None)
        span_id = getattr(record, "span_id", None)
        if trace_id is not None:
            payload["trace_id"] = trace_id
        if span_id is not None:
            payload["span_id"] = span_id
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def configure_logger(
    *,
    level: str | None = None,
    write_file: bool = False,
    state_dir: Path | None = None,
) -> logging.Logger:
    """Create an application logger without changing root logging configuration."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.propagate = False
    effective_level = level or ("INFO" if write_file else "WARNING")
    logger.setLevel(effective_level)

    formatter = JsonLogFormatter()
    if level is not None:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        logger.addHandler(stderr_handler)

    if write_file:
        root = state_dir or Path(os.environ.get("MARKETSIEVE_STATE_DIR", DEFAULT_STATE_DIR))
        log_dir = root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        file_handler = logging.FileHandler(log_dir / f"marketsieve-{stamp}.jsonl", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    return logger
