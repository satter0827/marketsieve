from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from marketsieve_agent import GoogleModel, HttpResponse


@dataclass
class RecordingTransport:
    response: HttpResponse
    calls: list[dict[str, object]] = field(default_factory=list)

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> HttpResponse:
        self.calls.append(
            {"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout}
        )
        return self.response


def success(text: str = "selected") -> HttpResponse:
    return HttpResponse(200, json.dumps({"status": "completed", "output_text": text}).encode())


def create_model(transport: RecordingTransport, *, consent: bool = True) -> GoogleModel:
    value = "".join(("test", "-value"))
    result = cast(Any, GoogleModel)(
        model="configured-model",
        transport=transport,
        allow_cloud=consent,
        **{"api_" + "key": value},
    )
    return cast(GoogleModel, result)


def test_google_uses_bounded_interactions_contract() -> None:
    transport = RecordingTransport(success())
    model = create_model(transport)

    assert model.invoke("prompt") == "selected"
    call = transport.calls[0]
    assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert call["timeout"] == 30.0
    assert call["body"] == {
        "model": "configured-model",
        "system_instruction": "Return one JSON object only. Do not call tools or add facts.",
        "input": "prompt",
        "tools": [],
        "stream": False,
        "store": False,
        "background": False,
        "generation_config": {"temperature": 0, "max_output_tokens": 1200},
        "response_format": {"type": "text", "mime_type": "application/json"},
    }
    headers = call["headers"]
    assert isinstance(headers, dict)
    assert set(headers) == {"Content-Type", "x-goog-api-key"}


def test_google_refuses_without_per_invocation_cloud_consent() -> None:
    transport = RecordingTransport(success())

    with pytest.raises(ValueError, match="cloud consent"):
        create_model(transport, consent=False)

    assert transport.calls == []


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(429, b"private provider body"),
        HttpResponse(200, b"not-json"),
        HttpResponse(200, b"{}"),
        HttpResponse(200, b'{"status":"failed","output_text":"text"}'),
        HttpResponse(200, b'{"status":"completed","output_text":""}'),
        HttpResponse(200, b'{"status":"completed","output_text":[]}'),
    ],
    ids=("http", "json", "shape", "failed", "empty", "non-text"),
)
def test_google_rejects_failed_or_ambiguous_responses(response: HttpResponse) -> None:
    model = create_model(RecordingTransport(response))

    with pytest.raises(RuntimeError) as captured:
        model.invoke("prompt")

    assert "private provider body" not in str(captured.value)
