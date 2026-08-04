"""Explicit model provider adapters with injectable transports."""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_OUTPUT_TOKENS = 1200
MAX_RESPONSE_BYTES = 1_048_576
AUTHORIZATION_HEADER = "Authorization"
BEARER_SCHEME = "Bearer"


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> HttpResponse: ...


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class UrlLibTransport:
    """Small production HTTP transport; redirects are never followed."""

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(_RejectRedirects())
        try:
            with opener.open(request, timeout=timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("model response exceeds the configured size limit")
                return HttpResponse(response.status, payload)
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, b"")
        except TimeoutError:
            raise
        except (OSError, urllib.error.URLError) as error:
            raise RuntimeError("model endpoint is unavailable") from error


class LmStudioModel:
    """One-attempt OpenAI-compatible LM Studio chat-completions adapter."""

    provider = "lmstudio"

    def __init__(
        self,
        *,
        model: str,
        endpoint: str = "http://127.0.0.1:1234/v1",
        api_token: str | None = None,
        allow_remote: bool = False,
        transport: HttpTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        if not model.strip():
            raise ValueError("LM Studio model must be configured")
        if timeout <= 0:
            raise ValueError("model timeout must be positive")
        if max_output_tokens <= 0:
            raise ValueError("maximum output tokens must be positive")
        self._endpoint = _validated_endpoint(endpoint, allow_remote=allow_remote)
        self._api_token = api_token
        self._transport = transport or UrlLibTransport()
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens
        self.model = model

    def invoke(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return one JSON object only. Do not call tools or add facts.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": self._max_output_tokens,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_token is not None:
            headers[AUTHORIZATION_HEADER] = f"{BEARER_SCHEME} {self._api_token}"
        response = self._transport.post(
            f"{self._endpoint}/chat/completions",
            headers=headers,
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            timeout=self._timeout,
        )
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"LM Studio request failed with HTTP {response.status}")
        try:
            document = json.loads(response.body)
            content = document["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("LM Studio returned an invalid chat response") from error
        if not isinstance(content, str) or not content:
            raise RuntimeError("LM Studio returned an empty chat response")
        return content


class OpenAIModel:
    """One-attempt OpenAI Responses API adapter with mandatory cloud consent."""

    provider = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        allow_cloud: bool,
        transport: HttpTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        if not allow_cloud:
            raise ValueError("OpenAI requires explicit cloud consent")
        if not model.strip():
            raise ValueError("OpenAI model must be configured")
        if not api_key:
            raise ValueError("OpenAI credential is required")
        if timeout <= 0 or max_output_tokens <= 0:
            raise ValueError("OpenAI request limits must be positive")
        self.model = model
        self._api_key = api_key
        self._transport = transport or UrlLibTransport()
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens

    def invoke(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "instructions": "Return one JSON object only. Do not call tools or add facts.",
            "input": prompt,
            "temperature": 0,
            "max_output_tokens": self._max_output_tokens,
            "tools": [],
            "tool_choice": "none",
            "store": False,
        }
        response = self._transport.post(
            self.endpoint,
            headers={
                "Content-Type": "application/json",
                AUTHORIZATION_HEADER: f"{BEARER_SCHEME} {self._api_key}",
            },
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            timeout=self._timeout,
        )
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"OpenAI request failed with HTTP {response.status}")
        try:
            document = json.loads(response.body)
            output = document["output"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("OpenAI returned an invalid response") from error
        if not isinstance(output, list):
            raise RuntimeError("OpenAI returned an invalid response")
        texts: list[str] = []
        for item in output:
            if (
                not isinstance(item, dict)
                or item.get("type") != "message"
                or item.get("role") != "assistant"
            ):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)
        if len(texts) != 1 or not texts[0]:
            raise RuntimeError("OpenAI returned no single text response")
        return texts[0]


def _validated_endpoint(endpoint: str, *, allow_remote: bool) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("LM Studio endpoint must be an absolute HTTP URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("LM Studio endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("LM Studio endpoint must not contain query parameters or fragments")
    if not allow_remote and not _is_loopback(parsed.hostname):
        raise ValueError("LM Studio endpoint must be loopback unless remote access is allowed")
    return endpoint.rstrip("/")


def _is_loopback(hostname: str) -> bool:
    if hostname.rstrip(".").casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
