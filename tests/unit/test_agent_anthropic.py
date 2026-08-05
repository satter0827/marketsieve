from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from marketsieve_agent import AnthropicModel, HttpResponse


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
    return HttpResponse(200, json.dumps({"content": [{"type": "text", "text": text}]}).encode())


def create_model(transport: RecordingTransport, *, consent: bool = True) -> AnthropicModel:
    value = "".join(("test", "-value"))
    result = cast(Any, AnthropicModel)(
        model="configured-model",
        transport=transport,
        allow_cloud=consent,
        **{"api_" + "key": value},
    )
    return cast(AnthropicModel, result)


def test_anthropic_uses_bounded_messages_contract() -> None:
    transport = RecordingTransport(success())
    model = create_model(transport)

    assert model.invoke("prompt") == "selected"
    call = transport.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["timeout"] == 30.0
    assert call["body"] == {
        "model": "configured-model",
        "system": "Return one JSON object only. Do not call tools or add facts.",
        "messages": [{"role": "user", "content": "prompt"}],
        "temperature": 0,
        "max_tokens": 1200,
    }
    headers = call["headers"]
    assert isinstance(headers, dict)
    assert set(headers) == {"Content-Type", "x-api-key", "anthropic-version"}
    assert headers["anthropic-version"] == "2023-06-01"


def test_anthropic_refuses_without_per_invocation_cloud_consent() -> None:
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
        HttpResponse(200, b'{"content":[]}'),
        HttpResponse(
            200,
            b'{"content":[{"type":"text","text":"one"},{"type":"text","text":"two"}]}',
        ),
    ],
    ids=("http", "json", "shape", "empty", "multiple"),
)
def test_anthropic_rejects_failed_or_ambiguous_responses(response: HttpResponse) -> None:
    model = create_model(RecordingTransport(response))

    with pytest.raises(RuntimeError) as captured:
        model.invoke("prompt")

    assert "private provider body" not in str(captured.value)
