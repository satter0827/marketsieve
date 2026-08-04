"""One-attempt model pipeline with deterministic grounding and fallback."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.language_models.fake import FakeListLLM
from langsmith import tracing_context

PROMPT_VERSION = "fact-selection-v1"
MAX_SELECTED_FACTS = 12
ALLOWED_EMPHASIS = frozenset({"context", "trend", "quality", "risk", "valuation"})
SECTION_ORDER = (
    "price",
    "technical",
    "financial",
    "valuation",
    "risk",
    "events",
    "data_quality",
)
UNSAFE_TERMS = (
    "buy",
    "sell",
    "hold",
    "recommend",
    "should invest",
    "strong pick",
    "買い",
    "売り",
    "保有すべき",
    "推奨",
    "投資すべき",
)
DISCLAIMER = "Market data and derived indicators only; not investment advice."
DEFAULT_CONNECTIONS = {
    "ja": "確認できる事実を項目別に整理します。",
    "en": "The validated facts are organized by section.",
}


class TextModel(Protocol):
    """Minimal synchronous model boundary used by every provider."""

    provider: str
    model: str

    def invoke(self, prompt: str) -> str: ...


@dataclass(frozen=True, slots=True)
class Fact:
    """One renderer-owned fact exposed to a model by identifier."""

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
    """Canonical fact set derived from one sectioned equity view."""

    instrument: str
    source_profile: str
    facts: tuple[Fact, ...]
    catalog_hash: str

    @classmethod
    def from_view(cls, view: Mapping[str, Any]) -> FactCatalog:
        instrument = _instrument_label(view.get("instrument"))
        source_profile = _required_text(view.get("source_profile"), "source_profile")
        sections = view.get("sections")
        if not isinstance(sections, Mapping):
            raise ValueError("equity view sections must be a mapping")
        facts: list[Fact] = []
        for section in SECTION_ORDER:
            raw_section = sections.get(section)
            if not isinstance(raw_section, Mapping):
                continue
            as_of = _optional_text(raw_section.get("as_of"))
            evidence_id = _optional_text(raw_section.get("evidence_id"))
            values = raw_section.get("values")
            if not isinstance(values, Mapping):
                continue
            for path, value in _leaf_values(values):
                fact_id = f"{section}.{'.'.join(path)}"
                facts.append(
                    Fact(
                        fact_id=fact_id,
                        section=section,
                        label=" / ".join(path),
                        value=_canonical_scalar(value),
                        as_of=as_of,
                        evidence_id=evidence_id,
                    )
                )
        facts.sort(key=lambda fact: fact.fact_id)
        payload = [fact.prompt_document() | {"evidence_id": fact.evidence_id} for fact in facts]
        catalog_hash = _digest(
            {"instrument": instrument, "source_profile": source_profile, "facts": payload}
        )
        return cls(instrument, source_profile, tuple(facts), catalog_hash)

    def prompt_document(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "source_profile": self.source_profile,
            "catalog_hash": self.catalog_hash,
            "facts": [fact.prompt_document() for fact in self.facts],
        }


@dataclass(frozen=True, slots=True)
class SelectedFact:
    fact_id: str
    emphasis: str


@dataclass(frozen=True, slots=True)
class ModelPlan:
    """Strict model-owned selection; it contains no market values."""

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
            "catalog_hash": self.catalog_hash,
            "selected_fact_ids": list(self.selected_fact_ids),
            "fallback_reason": self.fallback_reason,
            "text": self.text,
        }


class FakeModel:
    """Natural deterministic FakeListLLM adapter used by default and in ordinary tests."""

    provider = "fake"
    model = "fake-list-llm"

    def __init__(self, responses: Sequence[str] | None = None) -> None:
        self._responses = tuple(responses) if responses is not None else None

    def invoke(self, prompt: str) -> str:
        catalog = _catalog_from_prompt(prompt)
        response = self._responses[0] if self._responses is not None else _fake_response(catalog)
        with tracing_context(enabled=False):
            return str(FakeListLLM(responses=[response]).invoke(prompt))


def explain(
    view: Mapping[str, Any],
    *,
    model: TextModel | None = None,
    locale: str = "ja",
) -> ExplanationResult:
    """Explain one validated view or return the deterministic safe template."""

    if locale not in DEFAULT_CONNECTIONS:
        raise ValueError("locale must be ja or en")
    catalog = FactCatalog.from_view(view)
    selected_model = model or FakeModel()
    prompt = build_prompt(catalog, locale)
    try:
        raw = selected_model.invoke(prompt)
        plan = parse_plan(raw, catalog)
    except (RuntimeError, TimeoutError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _fallback(catalog, selected_model, locale, _fallback_code(error))
    return ExplanationResult(
        status="model",
        provider=selected_model.provider,
        model=selected_model.model,
        prompt_version=PROMPT_VERSION,
        catalog_hash=catalog.catalog_hash,
        selected_fact_ids=tuple(item.fact_id for item in plan.selected_facts),
        fallback_reason=None,
        text=render(catalog, plan, locale),
    )


def build_prompt(catalog: FactCatalog, locale: str) -> str:
    instructions = {
        "task": "Select only supplied fact IDs for a neutral evidence summary.",
        "output": {
            "section_order": "unique supplied section names",
            "selected_facts": [{"fact_id": "supplied ID", "emphasis": sorted(ALLOWED_EMPHASIS)}],
            "connections": "short text without numbers, dates, symbols, values, advice, or actions",
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
        section not in SECTION_ORDER for section in section_order
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
    lines = [catalog.instrument, plan.connections[0]]
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
    lines.append(DISCLAIMER)
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
        catalog_hash=catalog.catalog_hash,
        selected_fact_ids=tuple(fact.fact_id for fact in selected),
        fallback_reason=reason,
        text=render(catalog, plan, locale),
    )


def _fake_response(catalog: Mapping[str, Any]) -> str:
    facts = catalog.get("facts")
    if not isinstance(facts, list) or not facts:
        return "{}"
    selected = facts[:MAX_SELECTED_FACTS]
    sections = list(dict.fromkeys(str(fact["section"]) for fact in selected))
    return json.dumps(
        {
            "section_order": sections,
            "selected_facts": [
                {"fact_id": fact["fact_id"], "emphasis": "context"} for fact in selected
            ],
            "connections": ["確認できる事実を項目別に整理します。"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _catalog_from_prompt(prompt: str) -> Mapping[str, Any]:
    document = json.loads(prompt)
    catalog = document.get("catalog")
    if not isinstance(catalog, Mapping):
        raise ValueError("prompt does not contain a fact catalog")
    return catalog


def _leaf_values(
    value: Mapping[str, Any], path: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Any]]:
    leaves: list[tuple[tuple[str, ...], Any]] = []
    for key in sorted(value):
        item = value[key]
        next_path = (*path, str(key))
        if isinstance(item, Mapping):
            leaves.extend(_leaf_values(item, next_path))
        elif isinstance(item, list):
            for index, nested in enumerate(item):
                list_path = (*next_path, str(index))
                if isinstance(nested, Mapping):
                    leaves.extend(_leaf_values(nested, list_path))
                elif _is_scalar(nested):
                    leaves.append((list_path, nested))
        elif _is_scalar(item):
            leaves.append((next_path, item))
    return leaves


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _canonical_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not (float("-inf") < value < float("inf")):
        raise ValueError("fact catalog cannot contain non-finite numbers")
    return str(value)


def _instrument_label(value: object) -> str:
    if isinstance(value, str):
        return _required_text(value, "instrument")
    if isinstance(value, Mapping):
        mic = _required_text(value.get("mic"), "instrument.mic")
        symbol = _required_text(value.get("symbol"), "instrument.symbol")
        return f"{mic}:{symbol}"
    raise ValueError("instrument must be a string or mapping")


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return tuple(value)


def _validate_connection(text: str) -> None:
    normalized = text.casefold()
    if (
        len(text) > 160
        or re.search(r"\d", text)
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
