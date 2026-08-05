from __future__ import annotations

import json
from typing import Any

import pytest

from marketsieve_agent import FakeModel, explain


def view() -> dict[str, Any]:
    return {
        "instrument": {"mic": "XTKS", "symbol": "7203"},
        "source_profile": "japan",
        "sections": {
            "price": {
                "status": "available",
                "as_of": "2026-08-03T06:00:00+00:00",
                "values": {"close": "2500", "currency": "JPY"},
                "evidence_id": "price-evidence",
            },
            "risk": {
                "status": "partial",
                "as_of": "2026-08-03T06:00:00+00:00",
                "values": {"maximum_drawdown": {"value": "-0.12"}},
                "evidence_id": "risk-evidence",
            },
        },
    }


def response(*, connection: str = "確認できる事実を整理します。") -> str:
    return json.dumps(
        {
            "section_order": ["price"],
            "selected_facts": [{"fact_id": "price.close", "emphasis": "context"}],
            "connections": [connection],
        },
        ensure_ascii=False,
    )


def test_fake_is_default_and_renderer_owns_values_and_evidence() -> None:
    result = explain(view())

    assert result.status == "model"
    assert result.provider == "fake"
    assert "2500" in result.text
    assert "price-evidence" in result.text
    assert result.catalog_hash


def test_explicit_fake_uses_the_same_parser_and_renderer() -> None:
    result = explain(view(), model=FakeModel([response()]))

    assert result.status == "model"
    assert result.selected_fact_ids == ("price.close",)
    assert result.as_document()["schema_version"] == "1.0.0"


def test_invalid_json_uses_template_without_exposing_model_output() -> None:
    result = explain(view(), model=FakeModel(["not-json"]))

    assert result.status == "template"
    assert result.fallback_reason == "invalid_json"
    assert "not-json" not in result.text


def test_unknown_fact_uses_template() -> None:
    raw = json.loads(response())
    raw["selected_facts"][0]["fact_id"] = "price.unknown"

    result = explain(view(), model=FakeModel([json.dumps(raw)]))

    assert result.status == "template"
    assert result.fallback_reason == "invalid_model_output"


def test_numeric_connection_uses_template() -> None:
    result = explain(view(), model=FakeModel([response(connection="価格は二千五百円です 2500")]))

    assert result.status == "template"
    assert result.fallback_reason == "invalid_model_output"
    assert "価格は" not in result.text


@pytest.mark.parametrize("connection", ["価格は二千五百円です。", "Return is five percent."])
def test_spelled_out_numeric_connection_uses_template(connection: str) -> None:
    result = explain(view(), model=FakeModel([response(connection=connection)]))

    assert result.status == "template"


def test_recommendation_connection_uses_template() -> None:
    result = explain(view(), model=FakeModel([response(connection="買いを推奨します。")]))

    assert result.status == "template"
    assert "買い" not in result.text


class TimeoutModel:
    provider = "fake"
    model = "timeout"

    def invoke(self, prompt: str) -> str:
        raise TimeoutError


def test_timeout_uses_template() -> None:
    result = explain(view(), model=TimeoutModel())

    assert result.status == "template"
    assert result.fallback_reason == "model_timeout"


def test_catalog_hash_and_result_are_deterministic() -> None:
    first = explain(view())
    second = explain(view())

    assert first == second


def test_english_template_supports_scalar_and_list_facts() -> None:
    candidate = view()
    candidate["instrument"] = "XTKS:7203"
    candidate["sections"]["events"] = {
        "values": {"items": [{"kind": "earnings"}, True, None]},
        "as_of": None,
        "evidence_id": None,
    }

    result = explain(candidate, model=FakeModel(["invalid"]), locale="en")

    assert result.status == "template"
    assert "The validated facts" in result.text
    assert "true" in result.text
    assert "null" in result.text


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.update({"extra": True}),
        lambda raw: raw.update({"section_order": ["price", "price"]}),
        lambda raw: raw.update({"section_order": ["unknown"]}),
        lambda raw: raw.update({"selected_facts": []}),
        lambda raw: raw.update({"selected_facts": ["price.close"]}),
        lambda raw: raw["selected_facts"].append(raw["selected_facts"][0]),
        lambda raw: raw.update({"section_order": ["risk"]}),
        lambda raw: raw.update({"connections": []}),
        lambda raw: raw.update({"connections": ["one", "two"]}),
        lambda raw: raw.update({"connections": [""]}),
    ],
)
def test_invalid_plan_shapes_use_template(mutation: Any) -> None:
    raw = json.loads(response())
    mutation(raw)

    result = explain(view(), model=FakeModel([json.dumps(raw)]))

    assert result.status == "template"


@pytest.mark.parametrize(
    "candidate",
    [
        {"instrument": "XTKS:7203", "source_profile": "japan"},
        {"instrument": 1, "source_profile": "japan", "sections": {}},
        {"instrument": "", "source_profile": "japan", "sections": {}},
        {"instrument": "XTKS:7203", "source_profile": "", "sections": {}},
    ],
)
def test_invalid_view_is_rejected_before_model_use(candidate: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        explain(candidate)


def test_non_finite_fact_is_rejected() -> None:
    candidate = view()
    candidate["sections"]["price"]["values"]["close"] = float("inf")

    with pytest.raises(ValueError, match="non-finite"):
        explain(candidate)


def test_invalid_locale_is_rejected() -> None:
    with pytest.raises(ValueError, match="locale"):
        explain(view(), locale="fr")


class UnavailableModel:
    provider = "fake"
    model = "unavailable"

    def invoke(self, prompt: str) -> str:
        raise RuntimeError("not exposed")


def test_unavailable_model_uses_template_without_exception_detail() -> None:
    result = explain(view(), model=UnavailableModel())

    assert result.fallback_reason == "model_unavailable"
    assert "not exposed" not in result.text


def test_empty_catalog_uses_template() -> None:
    candidate = {"instrument": "XTKS:7203", "source_profile": "japan", "sections": {}}

    result = explain(candidate)

    assert result.status == "template"
    assert result.selected_fact_ids == ()
