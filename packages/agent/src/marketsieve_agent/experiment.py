"""Grounded model selection over immutable experiment facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from marketsieve_agent.pipeline import TextModel

PROMPT_VERSION = "experiment-fact-selection-v1"
MAX_SELECTED_FACTS = 16


@dataclass(frozen=True, slots=True)
class ExperimentFact:
    fact_id: str
    label: str
    value: str

    def document(self) -> dict[str, str]:
        return {"fact_id": self.fact_id, "label": self.label, "value": self.value}


@dataclass(frozen=True, slots=True)
class ExperimentFactCatalog:
    run_id: str
    facts: tuple[ExperimentFact, ...]
    catalog_hash: str

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> ExperimentFactCatalog:
        if document.get("schema") != "experiment-run/v1":
            raise ValueError("agent input must be an experiment-run/v1 document")
        run_id = document.get("run_id")
        spec = document.get("spec")
        metrics = document.get("metrics")
        decisions = document.get("decisions")
        if not isinstance(run_id, str) or not isinstance(spec, dict):
            raise ValueError("experiment identity or specification is invalid")
        if not isinstance(metrics, dict) or not isinstance(decisions, list):
            raise ValueError("experiment metrics or decisions are invalid")
        policy = spec["policy"]
        window = spec["window"]
        facts = [
            ExperimentFact(
                "spec.policy",
                "policy",
                f"{policy['name']}@{policy['version']}",
            ),
            ExperimentFact(
                "spec.window",
                "replay window",
                f"{window['start']}..{window['end']}",
            ),
        ]
        for name, value in sorted(policy["settings"].items()):
            facts.append(ExperimentFact(f"policy.setting.{name}", name.replace("_", " "), value))
        for name, data_id in sorted(spec["datasets"].items()):
            facts.append(ExperimentFact(f"dataset.{name}", f"dataset {name}", str(data_id)))
        for name, value in sorted(spec["execution_costs"].items()):
            facts.append(ExperimentFact(f"execution_cost.{name}", name.replace("_", " "), value))
        for name, metric in sorted(metrics.items()):
            facts.append(
                ExperimentFact(
                    f"metric.{name}",
                    name.replace("_", " "),
                    f"{metric['value']} {metric['unit']}",
                )
            )
        latest: dict[str, dict[str, Any]] = {}
        for decision in decisions:
            instrument = decision["instrument"]
            if instrument not in latest or decision["as_of"] > latest[instrument]["as_of"]:
                latest[instrument] = decision
        for instrument, decision in sorted(latest.items()):
            facts.append(
                ExperimentFact(
                    f"decision.{instrument}.latest",
                    f"latest decision {instrument}",
                    f"{decision['action']} / {decision['confidence']} / {decision['as_of']}",
                )
            )
        facts.sort(key=lambda item: item.fact_id)
        catalog_hash = _digest({"run_id": run_id, "facts": [item.document() for item in facts]})
        return cls(run_id, tuple(facts), catalog_hash)

    def document(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "catalog_hash": self.catalog_hash,
            "facts": [item.document() for item in self.facts],
        }


def build_experiment_prompt(catalog: ExperimentFactCatalog, locale: str) -> str:
    if locale not in {"ja", "en"}:
        raise ValueError("locale must be ja or en")
    return json.dumps(
        {
            "prompt_version": PROMPT_VERSION,
            "instructions": {
                "task": "Select supplied fact IDs that best explain this immutable experiment.",
                "output": {"selected_fact_ids": ["supplied fact ID"]},
                "limits": {"selected_fact_ids": MAX_SELECTED_FACTS, "attempts": 1},
                "prohibited": ["new facts", "new calculations", "changed decisions", "advice"],
                "locale": locale,
            },
            "catalog": catalog.document(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def explain_experiment(
    document: dict[str, Any], *, model: TextModel, locale: str
) -> dict[str, Any]:
    catalog = ExperimentFactCatalog.from_document(document)
    prompt = build_experiment_prompt(catalog, locale)
    raw: str | None = None
    reason: str | None = None
    try:
        raw = model.invoke(prompt)
        selected = _parse_selection(raw, catalog)
        status = "accepted"
    except (RuntimeError, TimeoutError, TypeError, ValueError, json.JSONDecodeError) as error:
        selected = tuple(item.fact_id for item in catalog.facts[:MAX_SELECTED_FACTS])
        status = "rejected"
        reason = _fallback_code(error)
    return {
        "status": "model" if status == "accepted" else "template",
        "provider": model.provider,
        "model": model.model,
        "prompt_version": PROMPT_VERSION,
        "run_id": catalog.run_id,
        "catalog_hash": catalog.catalog_hash,
        "selected_fact_ids": list(selected),
        "prompt": {"version": PROMPT_VERSION, "payload": prompt},
        "model_output": raw,
        "validation": {"status": status, "reason": reason},
        "text": _render(catalog, selected, locale),
    }


def _parse_selection(raw: str, catalog: ExperimentFactCatalog) -> tuple[str, ...]:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"selected_fact_ids"}:
        raise ValueError("model response does not match the experiment selection schema")
    selected = value["selected_fact_ids"]
    if (
        not isinstance(selected, list)
        or not 1 <= len(selected) <= MAX_SELECTED_FACTS
        or not all(isinstance(item, str) for item in selected)
        or len(selected) != len(set(selected))
    ):
        raise ValueError("model response contains an invalid fact selection")
    known = {item.fact_id for item in catalog.facts}
    if any(item not in known for item in selected):
        raise ValueError("model response references an unknown experiment fact")
    return tuple(selected)


def _render(catalog: ExperimentFactCatalog, selected: tuple[str, ...], locale: str) -> str:
    known = {item.fact_id: item for item in catalog.facts}
    heading = "実験結果" if locale == "ja" else "Experiment result"
    footer = (
        "数値と判断は保存済み実験から引用し、AIは変更していません。"
        if locale == "ja"
        else "Values and decisions were quoted from the stored experiment and not changed by AI."
    )
    lines = [f"{heading}: {catalog.run_id}"]
    lines.extend(f"- {known[fact_id].label}: {known[fact_id].value}" for fact_id in selected)
    lines.append(footer)
    return "\n".join(lines)


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
