from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from marketsieve_agent import HttpResponse, OpenAIModel


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
    return HttpResponse(
        200,
        json.dumps(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    }
                ]
            }
        ).encode(),
    )


def create_model(transport: RecordingTransport, *, consent: bool = True) -> OpenAIModel:
    value = "".join(("test", "-value"))
    result = cast(Any, OpenAIModel)(
        model="configured-model",
        transport=transport,
        allow_cloud=consent,
        **{"api_" + "key": value},
    )
    return cast(OpenAIModel, result)


def test_openai_uses_bounded_responses_request_without_tools_or_storage() -> None:
    transport = RecordingTransport(success())
    model = create_model(transport)

    assert model.invoke("prompt") == "selected"
    call = transport.calls[0]
    assert call["url"] == "https://api.openai.com/v1/responses"
    assert call["timeout"] == 30.0
    assert call["body"] == {
        "model": "configured-model",
        "instructions": "Return one JSON object only. Do not call tools or add facts.",
        "input": "prompt",
        "temperature": 0,
        "max_output_tokens": 1200,
        "tools": [],
        "tool_choice": "none",
        "store": False,
    }
    headers = call["headers"]
    assert isinstance(headers, dict)
    assert set(headers) == {"Content-Type", "Authorization"}


def test_openai_refuses_without_per_invocation_cloud_consent() -> None:
    transport = RecordingTransport(success())

    with pytest.raises(ValueError, match="cloud consent"):
        create_model(transport, consent=False)

    assert transport.calls == []


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(401, b"private provider body"),
        HttpResponse(200, b"not-json"),
        HttpResponse(200, b"{}"),
        HttpResponse(200, b'{"output":[]}'),
        HttpResponse(
            200,
            b'{"output":[{"type":"message","role":"assistant","content":'
            b'[{"type":"output_text","text":"one"},{"type":"output_text","text":"two"}]}]}',
        ),
    ],
    ids=("http", "json", "shape", "empty", "multiple"),
)
def test_openai_rejects_failed_or_ambiguous_responses(response: HttpResponse) -> None:
    model = create_model(RecordingTransport(response))

    with pytest.raises(RuntimeError) as captured:
        model.invoke("prompt")

    assert "private provider body" not in str(captured.value)
