"""Bounded EDINET v2 filing-list and XBRL-derived TSV acquisition."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener
from zoneinfo import ZoneInfo

from marketsieve_extension_api import (
    AvailabilityBasis,
    Consolidation,
    FactFetchRequest,
    FilingDocument,
    FinancialFact,
    FinancialFetcher,
    FinancialPeriod,
    ImportedFinancials,
    Revision,
    SourceConfiguration,
    SourceDiagnostic,
)

API_ORIGIN = "https://api.edinet-fsa.go.jp/api/v2"
API_KEY_ENV = "EDINET_API_KEY"
SOURCE_VERSION = "edinet-api-v2-xbrl-csv-v1"
DEFAULT_DOCUMENT_TYPES = ("120", "130", "140", "150", "160", "170")
ALLOWED_DOCUMENT_TYPES = frozenset(DEFAULT_DOCUMENT_TYPES)
CORRECTION_TYPES = frozenset({"130", "150", "170"})
ALLOWED_SETTINGS = frozenset(
    {"edinet_code", "document_type_codes", "max_days", "max_documents", "timeout_seconds"}
)
EDINET_CODE_PATTERN = re.compile(r"^E[0-9]{5}$")
DOCUMENT_ID_PATTERN = re.compile(r"^S[0-9A-Z]{7}$")
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_ZIP_MEMBERS = 1000
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MIN_REQUEST_INTERVAL_SECONDS = 0.2
TOKYO = ZoneInfo("Asia/Tokyo")

TSV_HEADERS = (
    "要素ID",
    "項目名",
    "コンテキストID",
    "相対年度",
    "連結・個別",
    "期間・時点",
    "ユニットID",
    "単位",
    "値",
)

CONCEPTS: Mapping[str, str] = {
    "jppfs_cor:NetSales": "revenue",
    "jppfs_cor:Revenue": "revenue",
    "jppfs_cor:OperatingIncome": "operating_income",
    "jppfs_cor:ProfitLossAttributableToOwnersOfParent": "net_income",
    "jppfs_cor:NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "jppfs_cor:Assets": "assets",
    "jppfs_cor:Equity": "equity",
    "jppfs_cor:BasicEarningsLossPerShare": "eps",
    "ifrs-full:Revenue": "revenue",
    "ifrs-full:OperatingProfitLoss": "operating_income",
    "ifrs-full:ProfitLossAttributableToOwnersOfParent": "net_income",
    "ifrs-full:CashFlowsFromUsedInOperatingActivities": "operating_cash_flow",
    "ifrs-full:Assets": "assets",
    "ifrs-full:Equity": "equity",
    "ifrs-full:BasicEarningsLossPerShare": "eps",
    "us-gaap:Revenues": "revenue",
    "us-gaap:OperatingIncomeLoss": "operating_income",
    "us-gaap:NetIncomeLoss": "net_income",
    "us-gaap:NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "us-gaap:Assets": "assets",
    "us-gaap:StockholdersEquity": "equity",
    "us-gaap:EarningsPerShareBasic": "eps",
}


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
                    raise RuntimeError("EDINET response exceeds the configured safety bound")
                return HttpResponse(response.status, body)
        except HTTPError as error:
            return HttpResponse(error.code, error.read(MAX_RESPONSE_BYTES + 1))
        except (TimeoutError, URLError):
            raise RuntimeError("EDINET request failed before receiving a response") from None


@dataclass(frozen=True, slots=True)
class _SelectedDocument:
    filing: FilingDocument
    document_type_code: str


class EdinetSource(FinancialFetcher):
    """Fetch explicitly identified Japanese filings and standard XBRL-derived facts."""

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._transport = transport or UrllibTransport()
        self._environ = environ if environ is not None else os.environ
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper or time.sleep
        self._request_count = 0

    def doctor_financials(self, configuration: SourceConfiguration) -> SourceDiagnostic:
        try:
            self._settings(configuration.settings)
        except ValueError as error:
            return SourceDiagnostic(
                False, "invalid_configuration", str(error), "Fix the EDINET source settings."
            )
        try:
            self._credential()
        except ValueError as error:
            return SourceDiagnostic(
                False,
                "invalid_credential",
                str(error),
                f"Set a valid {API_KEY_ENV} value for this command.",
            )
        return SourceDiagnostic(True, "ready", "EDINET source is configured.")

    def fetch_financials(self, request: FactFetchRequest) -> ImportedFinancials:
        edinet_code, document_types, max_days, max_documents, timeout = self._settings(
            request.settings
        )
        self._validate_instrument(request)
        if (request.end - request.start).days + 1 > max_days:
            raise ValueError("EDINET requested date range exceeds max_days")
        credential = self._credential()
        headers = {"Accept": "application/json, application/zip"}
        bodies: list[bytes] = []
        selected: dict[str, _SelectedDocument] = {}

        current = request.start
        while current <= request.end:
            document = self._get_json(
                f"{API_ORIGIN}/documents.json",
                {"date": current.isoformat(), "type": "2", "Subscription-Key": credential},
                headers,
                timeout,
                bodies,
            )
            for item in self._select_documents(document, edinet_code, document_types, request):
                selected[item.filing.filing_id] = item
            current += timedelta(days=1)
        documents = tuple(
            sorted(
                selected.values(),
                key=lambda item: (item.filing.published_at, item.filing.filing_id),
            )
        )
        if len(documents) > max_documents:
            raise ValueError("EDINET matching document count exceeds max_documents")

        facts: list[FinancialFact] = []
        for item in documents:
            body = self._get_bytes(
                f"{API_ORIGIN}/documents/{item.filing.filing_id}",
                {"type": "5", "Subscription-Key": credential},
                headers,
                timeout,
                bodies,
            )
            facts.extend(self._facts_from_zip(body, item))
        normalized_facts = self._unique_facts(facts)
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("source clock must return an offset-aware datetime")
        filings = tuple(item.filing for item in documents)
        if any(filing.published_at > retrieved_at for filing in filings):
            raise ValueError("EDINET returned a filing published after retrieval")

        digest = hashlib.sha256()
        for body in bodies:
            digest.update(hashlib.sha256(body).digest())
        missing = () if normalized_facts else ("no_supported_financial_facts",)
        return ImportedFinancials(
            request,
            "edinet",
            SOURCE_VERSION,
            "documents-list+xbrl-derived-csv",
            retrieved_at,
            normalized_facts,
            digest.hexdigest(),
            missing,
            filings,
        )

    @staticmethod
    def _validate_instrument(request: FactFetchRequest) -> None:
        instrument = request.instrument
        if instrument.mic != "XTKS":
            raise ValueError("EDINET source supports XTKS instruments only")
        if instrument.currency != "JPY":
            raise ValueError("EDINET source requires a JPY instrument")

    @staticmethod
    def _settings(
        settings: Mapping[str, str],
    ) -> tuple[str, tuple[str, ...], int, int, float]:
        unknown = set(settings) - ALLOWED_SETTINGS
        if unknown:
            raise ValueError(f"unsupported EDINET setting: {sorted(unknown)[0]}")
        edinet_code = settings.get("edinet_code", "")
        if not EDINET_CODE_PATTERN.fullmatch(edinet_code):
            raise ValueError("EDINET edinet_code must use E followed by five digits")
        raw_types = settings.get("document_type_codes", ",".join(DEFAULT_DOCUMENT_TYPES))
        document_types = tuple(part.strip() for part in raw_types.split(","))
        if (
            not document_types
            or any(not item for item in document_types)
            or len(set(document_types)) != len(document_types)
        ):
            raise ValueError("EDINET document type codes must be non-empty and unique")
        unsupported = set(document_types) - ALLOWED_DOCUMENT_TYPES
        if unsupported:
            raise ValueError(f"unsupported EDINET document type code: {sorted(unsupported)[0]}")
        try:
            max_days = int(settings.get("max_days", "31"))
            max_documents = int(settings.get("max_documents", "20"))
            timeout = float(settings.get("timeout_seconds", "10"))
        except ValueError as error:
            raise ValueError("EDINET numeric settings are invalid") from error
        if not 1 <= max_days <= 31:
            raise ValueError("EDINET max_days must be between 1 and 31")
        if not 1 <= max_documents <= 100:
            raise ValueError("EDINET max_documents must be between 1 and 100")
        if not 0 < timeout <= 60:
            raise ValueError("EDINET timeout_seconds must be greater than zero and at most 60")
        return edinet_code, document_types, max_days, max_documents, timeout

    def _credential(self) -> str:
        value = self._environ.get(API_KEY_ENV, "").strip()
        if not value or len(value) > 256 or any(character.isspace() for character in value):
            raise ValueError(f"{API_KEY_ENV} must contain one non-whitespace API key")
        return value

    def _request(
        self, url: str, query: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        if self._request_count:
            self._sleeper(MIN_REQUEST_INTERVAL_SECONDS)
        self._request_count += 1
        response = self._transport.get(url, query=query, headers=headers, timeout=timeout)
        if response.status in {301, 302, 303, 307, 308}:
            raise RuntimeError("EDINET redirect rejected")
        if response.status in {401, 403}:
            raise RuntimeError("EDINET credential or authorization rejected")
        if response.status == 404:
            raise RuntimeError("EDINET document or endpoint was not found")
        if response.status == 429:
            raise RuntimeError("EDINET rate limit reached")
        if response.status != 200:
            raise RuntimeError(f"EDINET request failed with HTTP status {response.status}")
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("EDINET response exceeds the configured safety bound")
        return response

    def _get_json(
        self,
        url: str,
        query: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float,
        bodies: list[bytes],
    ) -> dict[str, Any]:
        response = self._request(url, query, headers, timeout)
        try:
            document = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("EDINET response is not valid JSON") from error
        if not isinstance(document, dict):
            raise ValueError("EDINET response must be a JSON object")
        metadata = document.get("metadata")
        if not isinstance(metadata, dict) or str(metadata.get("status")) != "200":
            raise RuntimeError("EDINET API reported an application error")
        bodies.append(response.body)
        return document

    def _get_bytes(
        self,
        url: str,
        query: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float,
        bodies: list[bytes],
    ) -> bytes:
        response = self._request(url, query, headers, timeout)
        if response.body.lstrip().startswith(b"{"):
            raise RuntimeError("EDINET document API reported an application error")
        bodies.append(response.body)
        return response.body

    @classmethod
    def _select_documents(
        cls,
        document: Mapping[str, Any],
        edinet_code: str,
        document_types: tuple[str, ...],
        request: FactFetchRequest,
    ) -> tuple[_SelectedDocument, ...]:
        results = document.get("results")
        if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
            raise ValueError("EDINET document results must be an array of objects")
        selected: list[_SelectedDocument] = []
        for row in results:
            if str(row.get("edinetCode", "")) != edinet_code:
                continue
            document_type = str(row.get("docTypeCode", ""))
            if document_type not in document_types:
                continue
            if str(row.get("csvFlag", "")) != "1" or str(row.get("xbrlFlag", "")) != "1":
                continue
            if str(row.get("withdrawalStatus", "0")) != "0":
                continue
            if str(row.get("legalStatus", "1")) not in {"1", "2"}:
                continue
            document_id = str(row.get("docID", ""))
            if not DOCUMENT_ID_PATTERN.fullmatch(document_id):
                raise ValueError("EDINET document ID is invalid")
            security_code = row.get("secCode")
            if security_code not in (None, "", f"{request.instrument.symbol}0"):
                raise ValueError("EDINET returned a document for a different security")
            try:
                period_start = cls._optional_date(row.get("periodStart"))
                period_end = cls._optional_date(row.get("periodEnd"))
                submitted = datetime.strptime(str(row["submitDateTime"]), "%Y-%m-%d %H:%M").replace(
                    tzinfo=TOKYO
                )
            except (KeyError, ValueError) as error:
                raise ValueError("EDINET document period or submission time is invalid") from error
            parent = row.get("parentDocID")
            parent_id = str(parent) if parent not in (None, "") else None
            if parent_id is not None and not DOCUMENT_ID_PATTERN.fullmatch(parent_id):
                raise ValueError("EDINET parent document ID is invalid")
            period = {
                "120": FinancialPeriod.ANNUAL,
                "130": FinancialPeriod.ANNUAL,
                "140": FinancialPeriod.QUARTERLY,
                "150": FinancialPeriod.QUARTERLY,
                "160": FinancialPeriod.INTERIM_YTD,
                "170": FinancialPeriod.INTERIM_YTD,
            }[document_type]
            selected.append(
                _SelectedDocument(
                    FilingDocument(
                        document_id,
                        edinet_code,
                        document_type,
                        submitted,
                        period,
                        period_start,
                        period_end,
                        None,
                        Consolidation.UNKNOWN,
                        "JPY",
                        parent_id if document_type in CORRECTION_TYPES else None,
                    ),
                    document_type,
                )
            )
        return tuple(selected)

    @staticmethod
    def _optional_date(value: Any) -> date | None:
        return None if value in (None, "") else date.fromisoformat(str(value))

    @classmethod
    def _facts_from_zip(cls, body: bytes, selected: _SelectedDocument) -> tuple[FinancialFact, ...]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile as error:
            raise ValueError("EDINET document response is not a valid ZIP") from error
        with archive:
            members = archive.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise ValueError("EDINET ZIP member count exceeds the safety bound")
            total_size = 0
            facts: list[FinancialFact] = []
            for member in members:
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("EDINET ZIP contains an unsafe path")
                total_size += member.file_size
                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("EDINET ZIP expands beyond the safety bound")
                if member.is_dir() or path.suffix.lower() != ".csv":
                    continue
                try:
                    text = archive.read(member).decode("utf-16")
                except UnicodeError as error:
                    raise ValueError("EDINET XBRL-derived CSV must use UTF-16") from error
                facts.extend(cls._facts_from_tsv(text, selected))
        return tuple(facts)

    @classmethod
    def _facts_from_tsv(cls, text: str, selected: _SelectedDocument) -> tuple[FinancialFact, ...]:
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        if reader.fieldnames is None or tuple(reader.fieldnames) != TSV_HEADERS:
            raise ValueError("EDINET XBRL-derived CSV headers are unsupported")
        facts: list[FinancialFact] = []
        for row in reader:
            element_id = row["要素ID"]
            concept = CONCEPTS.get(element_id)
            if concept is None or not row["相対年度"].startswith("当期"):
                continue
            consolidation = cls._consolidation(row["連結・個別"])
            period = selected.filing.period
            if period is None or selected.filing.fiscal_period_end is None:
                continue
            is_instant = row["期間・時点"] == "時点"
            period_start = None if is_instant else selected.filing.fiscal_period_start
            try:
                value = cls._decimal(row["値"])
            except InvalidOperation as error:
                raise ValueError("EDINET financial value is invalid") from error
            facts.append(
                FinancialFact(
                    concept,
                    element_id,
                    cls._accounting_standard(element_id),
                    period,
                    selected.document_type_code,
                    period_start,
                    selected.filing.fiscal_period_end,
                    selected.filing.published_at,
                    selected.filing.published_at,
                    AvailabilityBasis.PUBLISHED,
                    consolidation,
                    Revision.RESTATED
                    if selected.document_type_code in CORRECTION_TYPES
                    else Revision.REPORTED,
                    "JPY",
                    1,
                    value,
                    selected.filing.filing_id,
                )
            )
        return tuple(facts)

    @staticmethod
    def _consolidation(value: str) -> Consolidation:
        if value == "連結":
            return Consolidation.CONSOLIDATED
        if value == "個別":
            return Consolidation.NON_CONSOLIDATED
        return Consolidation.UNKNOWN

    @staticmethod
    def _accounting_standard(element_id: str) -> str | None:
        if element_id.startswith(("jppfs_cor:", "jpcrp_cor:")):
            return "J-GAAP"
        if element_id.startswith("ifrs-full:"):
            return "IFRS"
        if element_id.startswith("us-gaap:"):
            return "US-GAAP"
        return None

    @staticmethod
    def _decimal(value: str) -> Decimal:
        normalized = value.strip().replace(",", "")
        if normalized.startswith("△"):
            normalized = f"-{normalized[1:]}"
        decimal = Decimal(normalized)
        if not decimal.is_finite():
            raise InvalidOperation
        return decimal

    @staticmethod
    def _unique_facts(facts: list[FinancialFact]) -> tuple[FinancialFact, ...]:
        unique: dict[tuple[Any, ...], FinancialFact] = {}
        for fact in facts:
            identity = (
                fact.provider_fact,
                fact.period,
                fact.fiscal_period_start,
                fact.fiscal_period_end,
                fact.consolidation,
                fact.filing_id,
            )
            previous = unique.get(identity)
            if previous is not None and previous.value != fact.value:
                raise ValueError("EDINET financial facts contain conflicting duplicate values")
            unique[identity] = fact
        return tuple(
            sorted(
                unique.values(),
                key=lambda fact: (
                    fact.available_at,
                    fact.concept,
                    fact.provider_fact,
                    fact.consolidation,
                ),
            )
        )
