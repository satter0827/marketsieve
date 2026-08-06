"""Credential-safe FRED economic-series acquisition."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from marketsieve import EconomicObservation, EconomicSeries
from marketsieve_extension_api import (
    EconomicSeriesFetcher,
    EconomicSeriesFetchRequest,
    EconomicSeriesSourceConfiguration,
    ImportedEconomicSeries,
    SourceDiagnostic,
)

API_URL = "https://api.stlouisfed.org/fred/series/observations"
API_KEY_ENV = "FRED_API_KEY"
SOURCE_VERSION = "fred-series-observations-v1"
API_KEY = re.compile(r"^[a-z0-9]{32}$")
ALLOWED_SETTINGS = frozenset({"page_size", "timeout_seconds"})
MAX_PAGES = 1000
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def get(
        self, url: str, *, query: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> HttpResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibTransport:
    """Bounded standard-library transport; tests inject a deterministic fake."""

    def __init__(self, opener: OpenerDirector | None = None) -> None:
        self._opener = opener or build_opener(_NoRedirect())

    def get(
        self, url: str, *, query: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        request = Request(f"{url}?{urlencode(query)}", headers=dict(headers), method="GET")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("FRED response exceeds the configured safety bound")
                return HttpResponse(response.status, body)
        except HTTPError as error:
            return HttpResponse(error.code, error.read(MAX_RESPONSE_BYTES + 1))
        except (TimeoutError, URLError):
            raise RuntimeError("FRED request failed before receiving a response") from None


class FredSource(EconomicSeriesFetcher):
    """Fetch an exact FRED series vintage without fallback or transformation."""

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or UrllibTransport()
        self._environ = environ if environ is not None else os.environ
        self._clock = clock or (lambda: datetime.now(UTC))

    def doctor_economic_series(
        self, configuration: EconomicSeriesSourceConfiguration
    ) -> SourceDiagnostic:
        try:
            self._settings(configuration.settings)
        except ValueError as error:
            return SourceDiagnostic(
                False,
                "invalid_configuration",
                str(error),
                "Fix the FRED source settings.",
            )
        try:
            credential = self._credential()
        except ValueError as error:
            return SourceDiagnostic(
                False,
                "invalid_credential",
                str(error),
                f"Set a valid {API_KEY_ENV} value for this command.",
            )
        if credential is None:
            return SourceDiagnostic(
                False,
                "missing_credential",
                f"Environment variable {API_KEY_ENV} is not set.",
                f"Set {API_KEY_ENV} for this command without writing it to a file.",
            )
        return SourceDiagnostic(True, "ready", "FRED source is configured.")

    def fetch_economic_series(self, request: EconomicSeriesFetchRequest) -> ImportedEconomicSeries:
        timeout, page_size = self._settings(request.settings)
        try:
            credential = self._credential()
        except ValueError as error:
            raise RuntimeError(str(error)) from None
        if credential is None:
            raise RuntimeError(f"missing credential; set {API_KEY_ENV}")
        base_query = {
            "api_key": credential,
            "file_type": "json",
            "series_id": request.series_id,
            "observation_start": request.observation_start.isoformat(),
            "observation_end": request.observation_end.isoformat(),
            "realtime_start": request.knowledge_date.isoformat(),
            "realtime_end": request.knowledge_date.isoformat(),
            "output_type": "1",
            "units": "lin",
            "sort_order": "asc",
            "limit": str(page_size),
        }
        rows, bodies = self._pages(base_query, timeout)
        observations, missing_dates = self._observations(rows, request)
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("source clock must return an offset-aware datetime")
        series = EconomicSeries(
            request.series_id,
            request.knowledge_date,
            observations,
            missing_dates,
        )
        digest = hashlib.sha256()
        for body in bodies:
            digest.update(hashlib.sha256(body).digest())
        return ImportedEconomicSeries(
            request,
            "fred",
            SOURCE_VERSION,
            "fred/series/observations:output_type=1:units=lin",
            retrieved_at,
            series,
            digest.hexdigest(),
        )

    def _pages(
        self, base_query: Mapping[str, str], timeout: float
    ) -> tuple[tuple[dict[str, Any], ...], tuple[bytes, ...]]:
        rows: list[dict[str, Any]] = []
        bodies: list[bytes] = []
        offset = 0
        expected_count: int | None = None
        for _ in range(MAX_PAGES):
            response = self._transport.get(
                API_URL,
                query={**base_query, "offset": str(offset)},
                headers={"Accept": "application/json"},
                timeout=timeout,
            )
            self._raise_for_status(response.status)
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise RuntimeError("FRED response exceeds the configured safety bound")
            document = self._document(response.body)
            count = self._integer(document, "count")
            response_offset = self._integer(document, "offset")
            response_limit = self._integer(document, "limit")
            if response_offset != offset or response_limit < 1:
                raise ValueError("FRED pagination metadata does not match the request")
            if expected_count is None:
                expected_count = count
            elif count != expected_count:
                raise ValueError("FRED result count changed during pagination")
            page = document.get("observations")
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise ValueError("FRED observations must be a JSON array of objects")
            page_rows = list(page)
            rows.extend(page_rows)
            bodies.append(response.body)
            if offset + len(page_rows) >= count:
                if len(rows) != count:
                    raise ValueError("FRED result count does not match returned observations")
                return tuple(rows), tuple(bodies)
            if not page_rows:
                raise ValueError("FRED pagination made no progress")
            offset += len(page_rows)
        raise RuntimeError("FRED pagination exceeded the safety limit")

    @staticmethod
    def _observations(
        rows: tuple[dict[str, Any], ...], request: EconomicSeriesFetchRequest
    ) -> tuple[tuple[EconomicObservation, ...], tuple[date, ...]]:
        observations: list[EconomicObservation] = []
        missing: list[date] = []
        seen: set[date] = set()
        row_dates: list[date] = []
        for row in rows:
            try:
                observation_date = date.fromisoformat(str(row["date"]))
                realtime_start = date.fromisoformat(str(row["realtime_start"]))
                realtime_end = date.fromisoformat(str(row["realtime_end"]))
                raw_value = row["value"]
            except (KeyError, ValueError, TypeError):
                raise ValueError("FRED returned a malformed observation") from None
            if observation_date in seen:
                raise ValueError("FRED returned a duplicate observation date")
            seen.add(observation_date)
            row_dates.append(observation_date)
            if not request.observation_start <= observation_date <= request.observation_end:
                raise ValueError("FRED returned an observation outside the requested range")
            if not realtime_start <= request.knowledge_date <= realtime_end:
                raise ValueError("FRED returned a revision outside the requested knowledge date")
            if raw_value == ".":
                missing.append(observation_date)
                continue
            if not isinstance(raw_value, str):
                raise ValueError("FRED returned a non-string observation value")
            try:
                value = Decimal(raw_value)
            except (InvalidOperation, ValueError):
                raise ValueError("FRED returned a non-decimal observation value") from None
            observations.append(
                EconomicObservation(observation_date, value, realtime_start, realtime_end)
            )
        if tuple(row_dates) != tuple(sorted(row_dates)):
            raise ValueError("FRED observations must be in ascending date order")
        return tuple(observations), tuple(missing)

    @staticmethod
    def _document(body: bytes) -> dict[str, Any]:
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("FRED returned invalid JSON") from None
        if not isinstance(value, dict):
            raise ValueError("FRED response must be a JSON object")
        return value

    @staticmethod
    def _integer(document: Mapping[str, Any], name: str) -> int:
        value = document.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"FRED {name} must be a non-negative integer")
        return value

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status == 200:
            return
        if status == 401:
            raise RuntimeError("FRED rejected the API credential")
        if status == 429:
            raise RuntimeError("FRED rate limit was exceeded")
        if 300 <= status < 400:
            raise RuntimeError("FRED redirect was rejected")
        raise RuntimeError(f"FRED request failed with HTTP status {status}")

    def _credential(self) -> str | None:
        value = self._environ.get(API_KEY_ENV)
        if value is None or value == "":
            return None
        if API_KEY.fullmatch(value) is None:
            raise ValueError(f"{API_KEY_ENV} must be 32 lowercase letters or digits")
        return value

    @staticmethod
    def _settings(settings: Mapping[str, str]) -> tuple[float, int]:
        unknown = set(settings) - ALLOWED_SETTINGS
        if unknown:
            raise ValueError(f"unsupported FRED setting: {sorted(unknown)[0]}")
        try:
            timeout = float(settings.get("timeout_seconds", "30"))
            page_size = int(settings.get("page_size", "100000"))
        except ValueError:
            raise ValueError("FRED timeout_seconds and page_size must be numeric") from None
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("FRED timeout_seconds must be greater than 0 and at most 120")
        if not 1 <= page_size <= 100000:
            raise ValueError("FRED page_size must be between 1 and 100000")
        return timeout, page_size
