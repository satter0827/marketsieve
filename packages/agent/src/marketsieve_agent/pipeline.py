"""One-attempt explanation of an immutable decision report."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from marketsieve import DecisionReport

PROMPT_VERSION = "decision-report-selection-v1"
MAX_SELECTED_FACTS = 16
ALLOWED_EMPHASIS = frozenset({"context", "trend", "quality", "risk", "valuation"})
UNSAFE_TERMS = (
    "recommend",
    "should invest",
    "strong pick",
    "target price",
    "entry point",
    "exit point",
    "推奨",
    "投資すべき",
    "目標株価",
    "エントリー",
    "利確",
    "損切り",
)
NUMBER_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|billion|trillion)\b",
    re.IGNORECASE,
)
NON_DIGIT_NUMERIC = re.compile(
    "[〇零一二三四五六七八九十百千万億兆%\N{FULLWIDTH PERCENT SIGN}$¥￥€£]"
)
DEFAULT_CONNECTIONS = {
    "ja": "保存済みレポートの判断と根拠を整理します。",
    "en": "The stored report decisions and evidence are organized below.",
}
FOOTERS = {
    "ja": "判断値は保存済みレポートから引用し、AIは変更していません。",
    "en": "Decision values are quoted from the stored report and were not changed by the model.",
}


class TextModel(Protocol):
    """Minimal synchronous model boundary used by every provider."""

    provider: str
    model: str

    def invoke(self, prompt: str) -> str: ...


@dataclass(frozen=True, slots=True)
class Fact:
    """One renderer-owned report fact exposed to a model by identifier."""

    fact_id: str
    section: str
    label: str
    value: str
    as_of: str | None
    evidence_id: str | None

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
            raise TypeError("agent input must be DecisionReport")
        as_of = report.as_of.isoformat()
        facts = [
            Fact("report.session", "report", "session", report.session.value, as_of, None),
            Fact("report.as_of", "report", "as of", as_of, as_of, None),
            Fact(
                "report.policy",
                "report",
                "policy",
                f"{report.policy_name}@{report.policy_version}",
                as_of,
                None,
            ),
        ]
        for decision in report.decisions:
            instrument = f"{decision.instrument.mic}:{decision.instrument.symbol}"
            prefix = f"decision.{instrument}"
            facts.extend(
                (
                    Fact(
                        f"{prefix}.action", instrument, "action", decision.action.value, as_of, None
                    ),
                    Fact(
                        f"{prefix}.confidence",
                        instrument,
                        "confidence",
                        decision.confidence.value,
                        as_of,
                        None,
                    ),
                    Fact(
                        f"{prefix}.next_action",
                        instrument,
                        "next action",
                        decision.next_action,
                        as_of,
                        None,
                    ),
                )
            )
            for index, evidence in enumerate(decision.evidence):
                evidence_id = evidence.evidence_ids[0] if evidence.evidence_ids else None
                facts.append(
                    Fact(
                        f"{prefix}.evidence.{index}",
                        instrument,
                        f"evidence {evidence.code}",
                        _evidence_value(
                            evidence.direction.value, evidence.value, evidence.threshold
                        ),
                        as_of,
                        evidence_id,
                    )
                )
        for index, diagnostic in enumerate(report.diagnostics):
            facts.append(
                Fact(
                    f"diagnostic.{index}", "diagnostics", "data limitation", diagnostic, as_of, None
                )
            )
        facts.sort(key=lambda fact: fact.fact_id)
        sections = tuple(dict.fromkeys(fact.section for fact in facts))
        payload = [fact.prompt_document() | {"evidence_id": fact.evidence_id} for fact in facts]
        catalog_hash = _digest({"report_id": report.report_id, "facts": payload})
        return cls(report.report_id, tuple(facts), sections, catalog_hash)

    def prompt_document(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "catalog_hash": self.catalog_hash,
            "sections": list(self.sections),
            "facts": [fact.prompt_document() for fact in self.facts],
        }


@dataclass(frozen=True, slots=True)
class SelectedFact:
    fact_id: str
    emphasis: str


@dataclass(frozen=True, slots=True)
class ModelPlan:
    """Strict model-owned selection; it contains no report values."""

    section_order: tuple[str, ...]
    selected_facts: tuple[SelectedFact, ...]
    connections: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExplanationResult:
    """Safe renderer output and audit metadata."""

    status: str
    provider: str
    model: str
    prompt_version: str
    report_id: str
    catalog_hash: str
    selected_fact_ids: tuple[str, ...]
    fallback_reason: str | None
    text: str

    def as_document(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "report_id": self.report_id,
            "catalog_hash": self.catalog_hash,
            "selected_fact_ids": list(self.selected_fact_ids),
            "fallback_reason": self.fallback_reason,
            "text": self.text,
        }


def explain(
    report: DecisionReport,
    *,
    model: TextModel,
    locale: str = "ja",
) -> ExplanationResult:
    """Explain one validated report or return its deterministic safe template."""

    if locale not in DEFAULT_CONNECTIONS:
        raise ValueError("locale must be ja or en")
    catalog = FactCatalog.from_report(report)
    prompt = build_prompt(catalog, locale)
    try:
        raw = model.invoke(prompt)
        plan = parse_plan(raw, catalog)
    except (RuntimeError, TimeoutError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _fallback(catalog, model, locale, _fallback_code(error))
    return ExplanationResult(
        status="model",
        provider=model.provider,
        model=model.model,
        prompt_version=PROMPT_VERSION,
        report_id=report.report_id,
        catalog_hash=catalog.catalog_hash,
        selected_fact_ids=tuple(item.fact_id for item in plan.selected_facts),
        fallback_reason=None,
        text=render(catalog, plan, locale),
    )


def build_prompt(catalog: FactCatalog, locale: str) -> str:
    if locale not in DEFAULT_CONNECTIONS:
        raise ValueError("locale must be ja or en")
    instructions = {
        "task": "Select only supplied fact IDs to explain the immutable decision report.",
        "output": {
            "section_order": "unique supplied section names",
            "selected_facts": [{"fact_id": "supplied ID", "emphasis": sorted(ALLOWED_EMPHASIS)}],
            "connections": (
                "short text without numbers, dates, symbols, values, advice, or new decisions"
            ),
        },
        "limits": {"selected_facts": MAX_SELECTED_FACTS, "attempts": 1},
        "locale": locale,
    }
    return json.dumps(
        {
            "prompt_version": PROMPT_VERSION,
            "instructions": instructions,
            "catalog": catalog.prompt_document(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def parse_plan(raw: str, catalog: FactCatalog) -> ModelPlan:
    document = json.loads(raw)
    if not isinstance(document, dict) or set(document) != {
        "section_order",
        "selected_facts",
        "connections",
    }:
        raise ValueError("model response does not match the plan schema")
    known = {fact.fact_id: fact for fact in catalog.facts}
    section_order = _string_tuple(document["section_order"], "section_order")
    if len(set(section_order)) != len(section_order) or any(
        section not in catalog.sections for section in section_order
    ):
        raise ValueError("model response contains an invalid section order")
    raw_selected = document["selected_facts"]
    if not isinstance(raw_selected, list) or not 1 <= len(raw_selected) <= MAX_SELECTED_FACTS:
        raise ValueError("model response contains an invalid fact selection")
    selected: list[SelectedFact] = []
    for item in raw_selected:
        if not isinstance(item, dict) or set(item) != {"fact_id", "emphasis"}:
            raise ValueError("model response contains an invalid selected fact")
        fact_id = _required_text(item["fact_id"], "fact_id")
        emphasis = _required_text(item["emphasis"], "emphasis")
        if fact_id not in known or emphasis not in ALLOWED_EMPHASIS:
            raise ValueError("model response references an unknown fact or emphasis")
        selected.append(SelectedFact(fact_id, emphasis))
    ids = [item.fact_id for item in selected]
    if len(set(ids)) != len(ids):
        raise ValueError("model response selects a fact more than once")
    if any(known[item.fact_id].section not in section_order for item in selected):
        raise ValueError("model response omits a selected fact section")
    connections = _string_tuple(document["connections"], "connections")
    if not connections or len(connections) > len(section_order):
        raise ValueError("model response contains an invalid connection count")
    for connection in connections:
        _validate_connection(connection)
    return ModelPlan(section_order, tuple(selected), connections)


def render(catalog: FactCatalog, plan: ModelPlan, locale: str) -> str:
    facts = {fact.fact_id: fact for fact in catalog.facts}
    lines = [f"report={catalog.report_id}", plan.connections[0]]
    for section in plan.section_order:
        selected = [
            facts[item.fact_id]
            for item in plan.selected_facts
            if facts[item.fact_id].section == section
        ]
        if not selected:
            continue
        lines.append(f"[{section}]")
        for fact in selected:
            suffix = f"; as_of={fact.as_of}" if fact.as_of is not None else ""
            evidence = f"; evidence={fact.evidence_id}" if fact.evidence_id is not None else ""
            lines.append(f"- {fact.label}: {fact.value}{suffix}{evidence}")
    lines.append(FOOTERS[locale])
    return "\n".join(lines)


def _fallback(
    catalog: FactCatalog, model: TextModel, locale: str, reason: str
) -> ExplanationResult:
    selected = tuple(catalog.facts[:MAX_SELECTED_FACTS])
    sections = tuple(dict.fromkeys(fact.section for fact in selected))
    plan = ModelPlan(
        sections,
        tuple(SelectedFact(fact.fact_id, "context") for fact in selected),
        (DEFAULT_CONNECTIONS[locale],),
    )
    return ExplanationResult(
        status="template",
        provider=model.provider,
        model=model.model,
        prompt_version=PROMPT_VERSION,
        report_id=catalog.report_id,
        catalog_hash=catalog.catalog_hash,
        selected_fact_ids=tuple(fact.fact_id for fact in selected),
        fallback_reason=reason,
        text=render(catalog, plan, locale),
    )


def _evidence_value(direction: str, value: str | None, threshold: str | None) -> str:
    parts = [direction]
    if value is not None:
        parts.append(f"value={value}")
    if threshold is not None:
        parts.append(f"threshold={threshold}")
    return ";".join(parts)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return tuple(value)


def _validate_connection(text: str) -> None:
    normalized = text.casefold()
    if (
        len(text) > 160
        or re.search(r"\d", text)
        or NUMBER_WORDS.search(text)
        or NON_DIGIT_NUMERIC.search(text)
        or any(term in normalized for term in UNSAFE_TERMS)
    ):
        raise ValueError("model connection contains numeric or unsafe content")


def _fallback_code(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "model_timeout"
    if isinstance(error, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(error, RuntimeError):
        return "model_unavailable"
    return "invalid_model_output"


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
