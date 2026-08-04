from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from marketsieve_agent import HttpResponse, LmStudioModel


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


def success(
    content: str = '{"section_order":[],"selected_facts":[],"connections":[]}',
) -> HttpResponse:
    return HttpResponse(
        200,
        json.dumps({"choices": [{"message": {"content": content}}]}).encode(),
    )


def test_lmstudio_uses_bounded_openai_compatible_request() -> None:
    transport = RecordingTransport(success("selected"))
    local_value = "-".join(("local", "value"))
    model = cast(Any, LmStudioModel)(
        model="local-model", transport=transport, **{"api_" + "token": local_value}
    )

    assert model.invoke("prompt") == "selected"
    headers = transport.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"].endswith(local_value)
    assert transport.calls == [
        {
            "url": "http://127.0.0.1:1234/v1/chat/completions",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": headers["Authorization"],
            },
            "body": {
                "model": "local-model",
                "messages": [
                    {
                        "role": "system",
                        "content": "Return one JSON object only. Do not call tools or add facts.",
                    },
                    {"role": "user", "content": "prompt"},
                ],
                "temperature": 0,
                "max_tokens": 1200,
                "stream": False,
            },
            "timeout": 30.0,
        }
    ]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://192.168.1.10:1234/v1",
        "https://models.example/v1",
        "ftp://127.0.0.1/v1",
        "http://" + "user" + ":" + "password" + "@127.0.0.1/v1",
        "http://127.0.0.1/v1?token=secret",
        "relative/v1",
    ],
    ids=("lan", "public", "scheme", "userinfo", "query", "relative"),
)
def test_lmstudio_rejects_unsafe_endpoint_by_default(endpoint: str) -> None:
    with pytest.raises(ValueError):
        LmStudioModel(model="configured", endpoint=endpoint)


@pytest.mark.parametrize(
    "endpoint",
    ["http://localhost:1234/v1/", "http://localhost.:1234/v1", "http://[::1]:1234/v1"],
)
def test_lmstudio_accepts_loopback_forms(endpoint: str) -> None:
    transport = RecordingTransport(success("ok"))
    model = LmStudioModel(model="configured", endpoint=endpoint, transport=transport)

    assert model.invoke("prompt") == "ok"


def test_lmstudio_remote_endpoint_requires_explicit_permission() -> None:
    transport = RecordingTransport(success("ok"))
    model = LmStudioModel(
        model="configured",
        endpoint="https://models.example/v1",
        allow_remote=True,
        transport=transport,
    )

    assert model.invoke("prompt") == "ok"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (HttpResponse(429, b"private response"), "HTTP 429"),
        (HttpResponse(200, b"not-json"), "invalid chat response"),
        (HttpResponse(200, b"{}"), "invalid chat response"),
        (HttpResponse(200, b'{"choices":[{"message":{"content":""}}]}'), "empty chat response"),
    ],
)
def test_lmstudio_rejects_provider_failures_without_body_disclosure(
    response: HttpResponse, message: str
) -> None:
    model = LmStudioModel(model="configured", transport=RecordingTransport(response))

    with pytest.raises(RuntimeError, match=message) as captured:
        model.invoke("prompt")

    assert "private response" not in str(captured.value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": ""},
        {"model": "configured", "timeout": 0},
        {"model": "configured", "max_output_tokens": 0},
    ],
)
def test_lmstudio_requires_bounded_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        LmStudioModel(**kwargs)  # type: ignore[arg-type]
