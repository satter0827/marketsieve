"""Manual AI exchange for immutable decision reports."""

from __future__ import annotations

import base64
import hashlib
import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from marketsieve import DecisionReport
from marketsieve_ai import (
    MAX_RESPONSE_BYTES,
    FactCatalog,
    ModelPlan,
    build_report_request,
    decode_response,
    parse_report_response,
    render,
)


class DecisionReportReader(Protocol):
    def resolve(self, report_id: str) -> DecisionReport: ...


class AiArtifactRepository(Protocol):
    root: Path

    def put(self, kind: str, value: dict[str, Any]) -> dict[str, Any]: ...

    def show(self, kind: str, object_id: str) -> dict[str, Any]: ...

    def path(self, kind: str, object_id: str) -> Path: ...

    def response_path(self, request_id: str) -> Path: ...

    def next_trial(self, request_id: str) -> int: ...

    def resolve_ref(self, name: str) -> str: ...


@dataclass(frozen=True, slots=True)
class PreparedAiRequest:
    request_id: str
    request_path: Path
    response_path: Path
    import_command: str


class ManualAiService:
    """Prepare and validate one human-mediated ChatGPT exchange."""

    def __init__(
        self,
        reports: DecisionReportReader,
        artifacts: AiArtifactRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reports = reports
        self._artifacts = artifacts
        self._clock = clock or (lambda: datetime.now(UTC))

    def prepare_report(self, report_id: str, locale: str) -> PreparedAiRequest:
        report = self._reports.resolve(report_id)
        request = build_report_request(report, locale)
        expected_id = request.pop("request_id")
        stored = self._artifacts.put("request", request)
        if stored["request_id"] != expected_id:
            raise ValueError("prepared AI request identity is inconsistent")
        request_path = self._artifacts.path("request", expected_id).resolve()
        response_path = self._artifacts.response_path(expected_id).resolve()
        command = f"uv run marketsieve ai import {shlex.quote(str(response_path))}"
        return PreparedAiRequest(expected_id, request_path, response_path, command)

    def import_response(
        self,
        path: Path,
        *,
        model_label: str | None = None,
        controlled: bool = False,
    ) -> dict[str, Any]:
        raw = path.read_bytes()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("AI response exceeds the size limit")
        declared_request_id = self._declared_request_id(raw)
        path_request_id = self._path_request_id(path)
        request_id = path_request_id or declared_request_id
        if request_id is None:
            raise ValueError("AI response cannot be bound to a prepared request")
        try:
            request = self._artifacts.show("request", request_id)
        except (LookupError, ValueError):
            raise ValueError("AI response references an unknown request") from None
        request_id = str(request["request_id"])
        trial = self._artifacts.next_trial(request_id)
        try:
            raw_text: str | None = raw.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = None
        response = self._artifacts.put(
            "response",
            {
                "request_id": request_id,
                "trial": trial,
                "service": "chatgpt",
                "model_label": model_label,
                "controlled": controlled,
                "imported_at": self._aware_now().isoformat(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_base64": base64.b64encode(raw).decode("ascii"),
                "raw_text": raw_text,
            },
        )
        try:
            if declared_request_id is not None and declared_request_id != request_id:
                raise ValueError("AI response references an unknown request")
            report = self._reports.resolve(str(request["catalog"]["report_id"]))
            plan = parse_report_response(raw, request, report)
        except (
            KeyError,
            LookupError,
            OSError,
            RecursionError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            self._artifacts.put(
                "validation",
                {
                    "request_id": request_id,
                    "response_id": response["response_id"],
                    "status": "invalid",
                    "reason": str(error),
                },
            )
            raise ValueError(str(error)) from None
        validation = self._artifacts.put(
            "validation",
            {
                "request_id": request_id,
                "response_id": response["response_id"],
                "status": "valid",
                "reason": None,
                "plan": self._plan_document(plan),
            },
        )
        catalog = FactCatalog.from_report(report)
        return self._artifacts.put(
            "explanation",
            {
                "request_id": request_id,
                "response_id": response["response_id"],
                "validation_id": validation["validation_id"],
                "report_id": report.report_id,
                "trial": trial,
                "service": "chatgpt",
                "model_label": model_label,
                "controlled": controlled,
                "prompt_version": request["prompt_version"],
                "catalog_hash": catalog.catalog_hash,
                "selected_fact_ids": list(plan.selected_fact_ids),
                "text": render(catalog, plan, str(request["locale"])),
            },
        )

    def show(self, explanation_id: str) -> dict[str, Any]:
        return self._artifacts.show("explanation", explanation_id)

    @staticmethod
    def _declared_request_id(raw: bytes) -> str | None:
        try:
            value = decode_response(raw).get("request_id")
        except (RecursionError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        ):
            return value
        return None

    @staticmethod
    def _path_request_id(path: Path) -> str | None:
        suffix = ".response.json"
        if not path.name.endswith(suffix):
            return None
        value = path.name[: -len(suffix)]
        if len(value) == 64 and all(character in "0123456789abcdef" for character in value):
            return value
        return None

    @staticmethod
    def _plan_document(plan: ModelPlan) -> dict[str, Any]:
        return {
            "section_order": list(plan.section_order),
            "selected_fact_ids": list(plan.selected_fact_ids),
            "connections": [
                {
                    "from_fact_id": item.from_fact_id,
                    "relation": item.relation,
                    "to_fact_id": item.to_fact_id,
                }
                for item in plan.connections
            ],
        }

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AI import clock must include a UTC offset")
        return value
