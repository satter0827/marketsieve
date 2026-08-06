from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from marketsieve_agent import ExperimentFactCatalog, explain_experiment
from marketsieve_cli.adapters.explanations import ExplanationStore
from marketsieve_cli.application import experiment_agent as application_module
from marketsieve_cli.application.experiment_agent import ExperimentAgentService


def run_document() -> dict[str, object]:
    return {
        "schema": "experiment-run/v1",
        "run_id": "a" * 64,
        "spec_id": "b" * 64,
        "profit_simulation": False,
        "spec": {
            "policy": {"name": "balanced_medium_term", "version": "1.0.0", "settings": {}},
            "window": {"start": "2025-01-01", "end": "2025-12-31"},
            "datasets": {"XTKS:7203": "c" * 64},
            "execution_costs": {},
        },
        "decisions": [
            {
                "instrument": "XTKS:7203",
                "as_of": "2025-06-01T06:00:00+00:00",
                "action": "keep",
                "confidence": "medium",
            },
            {
                "instrument": "XTKS:7203",
                "as_of": "2025-12-30T06:00:00+00:00",
                "action": "watch",
                "confidence": "low",
            },
        ],
        "metrics": {
            "data_coverage": {"value": "1", "unit": "ratio"},
            "decision_count": {"value": "2", "unit": "count"},
        },
    }


class SelectionModel:
    provider = "lmstudio"
    model = "local-model"

    def invoke(self, prompt: str) -> str:
        payload = json.loads(prompt)
        assert payload["instructions"]["prohibited"] == [
            "new facts",
            "new calculations",
            "changed decisions",
            "advice",
        ]
        return json.dumps(
            {
                "selected_fact_ids": [
                    "metric.data_coverage",
                    "decision.XTKS:7203.latest",
                ]
            }
        )


class InvalidModel:
    provider = "lmstudio"
    model = "local-model"

    def invoke(self, prompt: str) -> str:
        del prompt
        return '{"selected_fact_ids":["invented.fact"]}'


def test_experiment_agent_selects_only_stored_facts_without_changing_input() -> None:
    source = run_document()
    original = copy.deepcopy(source)

    result = explain_experiment(source, model=SelectionModel(), locale="ja")

    assert source == original
    assert result["validation"] == {"status": "accepted", "reason": None}
    assert result["selected_fact_ids"] == [
        "metric.data_coverage",
        "decision.XTKS:7203.latest",
    ]
    assert "1 ratio" in result["text"]
    assert "watch / low / 2025-12-30T06:00:00+00:00" in result["text"]
    assert result["model_output"] is not None


def test_experiment_agent_rejects_unknown_facts_and_uses_stored_template() -> None:
    result = explain_experiment(run_document(), model=InvalidModel(), locale="en")

    assert result["status"] == "template"
    assert result["validation"] == {
        "status": "rejected",
        "reason": "invalid_model_output",
    }
    assert result["model_output"] == '{"selected_fact_ids":["invented.fact"]}'
    assert "not changed by AI" in result["text"]


def test_experiment_agent_service_records_prompt_model_output_and_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Runs:
        def show(self, run_id: str) -> dict[str, object]:
            assert run_id == "a" * 64
            return run_document()

    class Configuration:
        def agent_provider(self, name: str) -> object:
            assert name == "lmstudio"
            return SimpleNamespace(model="local-model", endpoint=None)

    monkeypatch.setattr(
        application_module, "select_model", lambda *args, **kwargs: SelectionModel()
    )
    store = ExplanationStore(tmp_path / "explanations", schema="experiment-explanation/v1")
    service = ExperimentAgentService(Runs(), store, Configuration(), {})

    artifact = service.explain(
        "a" * 64,
        "lmstudio",
        "ja",
        allow_cloud=False,
        allow_remote=False,
    )

    assert artifact["model_settings"] == {
        "provider": "lmstudio",
        "model": "local-model",
        "endpoint": "http://127.0.0.1:1234/v1",
        "locale": "ja",
    }
    assert store.show(artifact["explanation_id"]) == artifact
    schema = json.loads(Path("schemas/experiment-explanation/v1/schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(artifact)


def test_experiment_catalog_rejects_non_experiment_documents() -> None:
    invalid = run_document()
    invalid["schema"] = "decision-report/v1"

    try:
        ExperimentFactCatalog.from_document(invalid)
    except ValueError as error:
        assert "experiment-run/v1" in str(error)
    else:
        raise AssertionError("non-experiment input must be rejected")
