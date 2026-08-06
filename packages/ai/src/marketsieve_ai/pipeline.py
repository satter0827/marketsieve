"""Manual, grounded explanation of an immutable decision report."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from marketsieve import DecisionReport, InstrumentDecision

PROMPT_VERSION = "decision-report-manual-selection-v1"
REQUEST_SCHEMA = "report-ai-request/v1"
RESPONSE_SCHEMA = "report-ai-response/v1"
EXPLANATION_SCHEMA = "report-ai-explanation/v1"
MAX_SELECTED_FACTS = 16
MAX_RESPONSE_BYTES = 65_536
ALLOWED_RELATIONS = frozenset({"supports", "contrasts", "context_for"})
JSON_FENCE = re.compile(r"\A```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```\Z", re.DOTALL)
FOOTERS = {
    "ja": "判断値は保存済みレポートから引用し、AIは変更していません。",
    "en": "Decision values are quoted from the stored report and were not changed by AI.",
}


@dataclass(frozen=True, slots=True)
class Fact:
    """One renderer-owned report fact exposed by identifier."""

    fact_id: str
    section: str
    label: str
    value: str
    as_of: str | None
    evidence_ids: tuple[str, ...]

    def prompt_document(self) -> dict[str, str | None]:
        return {
            "fact_id": self.fact_id,
            "section": self.section,
            "label": self.label,
            "value": self.value,
            "as_of": self.as_of,
        }


@dataclass(frozen=True, slots=True)
class FactCatalog:
    """Canonical non-private fact set derived from one decision report."""

    report_id: str
    facts: tuple[Fact, ...]
    sections: tuple[str, ...]
    catalog_hash: str

    @classmethod
    def from_report(cls, report: DecisionReport) -> FactCatalog:
        if not isinstance(report, DecisionReport):
            raise TypeError("AI input must be DecisionReport")
        as_of = report.as_of.isoformat()
        facts = [
            Fact("report.session", "report", "session", report.session.value, as_of, ()),
            Fact("report.as_of", "report", "as of", as_of, as_of, ()),
            Fact(
                "report.policy",
                "report",
                "policy",
                f"{report.policy_name}@{report.policy_version}",
                as_of,
                (),
            ),
        ]
        for decision in report.decisions:
            instrument = f"{decision.instrument.mic}:{decision.instrument.symbol}"
            facts.extend(
                _decision_facts(
                    decision,
                    as_of=as_of,
                    namespace="decision",
                    section=instrument,
                )
            )
        for candidate in report.candidate_decisions:
            instrument = f"{candidate.instrument.mic}:{candidate.instrument.symbol}"
            facts.extend(
                _decision_facts(
                    candidate,
                    as_of=as_of,
                    namespace="candidate",
                    section=f"candidate:{instrument}",
                )
            )
        for index, diagnostic in enumerate(report.diagnostics):
            facts.append(
                Fact(f"diagnostic.{index}", "diagnostics", "data limitation", diagnostic, as_of, ())
            )
        facts.sort(key=lambda fact: fact.fact_id)
        sections = tuple(dict.fromkeys(fact.section for fact in facts))
        identity = [
            fact.prompt_document() | {"evidence_ids": list(fact.evidence_ids)} for fact in facts
        ]
        return cls(
            report.report_id,
            tuple(facts),
            sections,
            _digest({"report_id": report.report_id, "facts": identity}),
        )

    def prompt_document(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "catalog_hash": self.catalog_hash,
            "sections": list(self.sections),
            "facts": [fact.prompt_document() for fact in self.facts],
        }


@dataclass(frozen=True, slots=True)
class FactConnection:
    from_fact_id: str
    relation: str
    to_fact_id: str


@dataclass(frozen=True, slots=True)
class ModelPlan:
    """Strict AI-owned selection containing no report values."""

    section_order: tuple[str, ...]
    selected_fact_ids: tuple[str, ...]
    connections: tuple[FactConnection, ...]


def build_report_request(report: DecisionReport, locale: str = "ja") -> dict[str, Any]:
    """Build one content-addressed file for a manual ChatGPT interaction."""

    if locale not in FOOTERS:
        raise ValueError("locale must be ja or en")
    catalog = FactCatalog.from_report(report)
    semantic: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "service": "chatgpt",
        "task": "explain_decision_report",
        "prompt_version": PROMPT_VERSION,
        "locale": locale,
        "interaction": {
            "mode": "temporary_chat",
            "project": False,
            "web_search": False,
            "external_tools": False,
            "custom_instructions": "disabled",
        },
        "instructions": {
            "task": "Select only supplied fact IDs to explain the immutable decision report.",
            "rules": [
                "Do not calculate, browse, use tools, or create a new investment decision.",
                "Return only one JSON object matching response_schema.",
                "Connections may use only selected fact IDs and the declared relation enum.",
            ],
            "limits": {"selected_fact_ids": MAX_SELECTED_FACTS, "attempts": 1},
        },
        "catalog": catalog.prompt_document(),
        "response_schema": _response_schema(),
    }
    return {"request_id": _digest(semantic), **semantic}


def parse_report_response(
    raw: bytes | str,
    request: dict[str, Any],
    report: DecisionReport,
) -> ModelPlan:
    """Validate one manual response against its exact request and report."""

    document = decode_response(raw)
    if set(document) != {
        "request_id",
        "section_order",
        "selected_fact_ids",
        "connections",
    }:
        raise ValueError("AI response does not match the response schema")
    request_id = request.get("request_id")
    if document["request_id"] != request_id:
        raise ValueError("AI response request ID does not match the prepared request")
    _validate_request(request, report)
    catalog = FactCatalog.from_report(report)
    return parse_plan(
        {
            "section_order": document["section_order"],
            "selected_fact_ids": document["selected_fact_ids"],
            "connections": document["connections"],
        },
        catalog,
    )


def decode_response(raw: bytes | str) -> dict[str, Any]:
    """Decode raw JSON or one otherwise-empty JSON code fence."""

    document = json.loads(_response_text(raw))
    if not isinstance(document, dict):
        raise ValueError("AI response must be one JSON object")
    return document


def parse_plan(document: object, catalog: FactCatalog) -> ModelPlan:
    if not isinstance(document, dict) or set(document) != {
        "section_order",
        "selected_fact_ids",
        "connections",
    }:
        raise ValueError("AI response does not match the plan schema")
    known = {fact.fact_id: fact for fact in catalog.facts}
    section_order = _string_tuple(document["section_order"], "section_order")
    if len(set(section_order)) != len(section_order) or any(
        section not in catalog.sections for section in section_order
    ):
        raise ValueError("AI response contains an invalid section order")
    selected_fact_ids = _string_tuple(document["selected_fact_ids"], "selected_fact_ids")
    if not 1 <= len(selected_fact_ids) <= MAX_SELECTED_FACTS:
        raise ValueError("AI response contains an invalid fact selection")
    if any(fact_id not in known for fact_id in selected_fact_ids):
        raise ValueError("AI response references an unknown fact")
    if len(set(selected_fact_ids)) != len(selected_fact_ids):
        raise ValueError("AI response selects a fact more than once")
    if any(known[fact_id].section not in section_order for fact_id in selected_fact_ids):
        raise ValueError("AI response omits a selected fact section")
    raw_connections = document["connections"]
    if not isinstance(raw_connections, list) or len(raw_connections) > len(selected_fact_ids):
        raise ValueError("AI response contains an invalid connection count")
    connections: list[FactConnection] = []
    for item in raw_connections:
        if not isinstance(item, dict) or set(item) != {
            "from_fact_id",
            "relation",
            "to_fact_id",
        }:
            raise ValueError("AI response contains an invalid connection")
        connection = FactConnection(
            _required_text(item["from_fact_id"], "from_fact_id"),
            _required_text(item["relation"], "relation"),
            _required_text(item["to_fact_id"], "to_fact_id"),
        )
        if (
            connection.from_fact_id not in selected_fact_ids
            or connection.to_fact_id not in selected_fact_ids
            or connection.from_fact_id == connection.to_fact_id
            or connection.relation not in ALLOWED_RELATIONS
            or connection in connections
        ):
            raise ValueError("AI response contains an invalid connection")
        connections.append(connection)
    return ModelPlan(section_order, selected_fact_ids, tuple(connections))


def render(catalog: FactCatalog, plan: ModelPlan, locale: str) -> str:
    """Render only catalog-owned values selected by the AI response."""

    if locale not in FOOTERS:
        raise ValueError("locale must be ja or en")
    facts = {fact.fact_id: fact for fact in catalog.facts}
    lines = [f"report={catalog.report_id}"]
    relation_labels = {
        "ja": {"supports": "補強", "contrasts": "対比", "context_for": "背景"},
        "en": {"supports": "supports", "contrasts": "contrasts", "context_for": "context for"},
    }
    for connection in plan.connections:
        relation = relation_labels[locale][connection.relation]
        lines.append(f"relation: {connection.from_fact_id} {relation} {connection.to_fact_id}")
    for section in plan.section_order:
        selected = [
            facts[fact_id]
            for fact_id in plan.selected_fact_ids
            if facts[fact_id].section == section
        ]
        if not selected:
            continue
        lines.append(f"[{section}]")
        for fact in selected:
            suffix = f"; as_of={fact.as_of}" if fact.as_of is not None else ""
            evidence = f"; evidence={','.join(fact.evidence_ids)}" if fact.evidence_ids else ""
            lines.append(f"- {fact.label}: {fact.value}{suffix}{evidence}")
    lines.append(FOOTERS[locale])
    return "\n".join(lines)


def _validate_request(request: dict[str, Any], report: DecisionReport) -> None:
    locale = request.get("locale")
    if not isinstance(locale, str):
        raise ValueError("prepared AI request is not canonical")
    try:
        expected = build_report_request(report, locale)
    except ValueError:
        raise ValueError("prepared AI request is not canonical") from None
    if request != expected:
        raise ValueError("prepared AI request does not match the immutable report")


def _response_text(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("AI response exceeds the size limit")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("AI response must be UTF-8") from error
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("AI response exceeds the size limit")
        text = raw
    else:
        raise TypeError("AI response must be bytes or text")
    stripped = text.strip()
    match = JSON_FENCE.fullmatch(stripped)
    return match.group("body") if match is not None else stripped


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["request_id", "section_order", "selected_fact_ids", "connections"],
        "additionalProperties": False,
        "properties": {
            "request_id": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "section_order": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
            "selected_fact_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_SELECTED_FACTS,
                "items": {"type": "string"},
                "uniqueItems": True,
            },
            "connections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["from_fact_id", "relation", "to_fact_id"],
                    "additionalProperties": False,
                    "properties": {
                        "from_fact_id": {"type": "string"},
                        "relation": {"enum": sorted(ALLOWED_RELATIONS)},
                        "to_fact_id": {"type": "string"},
                    },
                },
            },
        },
    }


def _evidence_value(direction: str, value: str | None, threshold: str | None) -> str:
    parts = [direction]
    if value is not None:
        parts.append(f"value={value}")
    if threshold is not None:
        parts.append(f"threshold={threshold}")
    return ";".join(parts)


def _decision_facts(
    decision: InstrumentDecision,
    *,
    as_of: str,
    namespace: str,
    section: str,
) -> tuple[Fact, ...]:
    instrument = f"{decision.instrument.mic}:{decision.instrument.symbol}"
    prefix = f"{namespace}.{instrument}"
    facts = [
        Fact(f"{prefix}.action", section, "action", decision.action.value, as_of, ()),
        Fact(
            f"{prefix}.confidence",
            section,
            "confidence",
            decision.confidence.value,
            as_of,
            (),
        ),
        Fact(
            f"{prefix}.next_action",
            section,
            "next action",
            decision.next_action,
            as_of,
            (),
        ),
    ]
    for index, evidence in enumerate(decision.evidence):
        facts.append(
            Fact(
                f"{prefix}.evidence.{index}",
                section,
                f"evidence {evidence.code}",
                _evidence_value(
                    evidence.direction.value,
                    None if evidence.code == "concentrated" else evidence.value,
                    None if evidence.code == "concentrated" else evidence.threshold,
                ),
                as_of,
                evidence.evidence_ids,
            )
        )
    return tuple(facts)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return tuple(value)


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
