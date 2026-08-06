"""Bounded SEC EDGAR submissions and company-facts acquisition."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from marketsieve.domain import Instrument
from marketsieve_extension_api import (
    AvailabilityBasis,
    Consolidation,
    FactFetchRequest,
    FilingDocument,
    FinancialFact,
    FinancialFetcher,
    FinancialPeriod,
    ImportedFinancials,
    ImportedInstrumentUniverse,
    InstrumentUniverseFetcher,
    Revision,
    SourceConfiguration,
    SourceDiagnostic,
    UniverseRequest,
)

SUBMISSIONS_URL = "https://data.sec.gov/submissions"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts"
COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
USER_AGENT_ENV = "SEC_USER_AGENT"
SOURCE_VERSION = "sec-edgar-data-v1"
DEFAULT_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
ALLOWED_FORMS = frozenset(DEFAULT_FORMS)
ALLOWED_SETTINGS = frozenset({"cik", "forms", "timeout_seconds"})
CIK_PATTERN = re.compile(r"^[0-9]{10}$")
ACCESSION_PATTERN = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_SUBMISSION_FILES = 100
MIN_REQUEST_INTERVAL_SECONDS = 0.11

CONCEPTS: Mapping[tuple[str, str], str] = {
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"): "revenue",
    ("us-gaap", "SalesRevenueNet"): "revenue",
    ("us-gaap", "OperatingIncomeLoss"): "operating_income",
    ("us-gaap", "NetIncomeLoss"): "net_income",
    ("us-gaap", "EarningsPerShareDiluted"): "eps",
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"): "operating_cash_flow",
    ("us-gaap", "Assets"): "assets",
    ("us-gaap", "StockholdersEquity"): "equity",
    ("ifrs-full", "Revenue"): "revenue",
    ("ifrs-full", "ProfitLossFromOperatingActivities"): "operating_income",
    ("ifrs-full", "ProfitLoss"): "net_income",
    ("ifrs-full", "DilutedEarningsLossPerShare"): "eps",
    ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"): "operating_cash_flow",
    ("ifrs-full", "Assets"): "assets",
    ("ifrs-full", "Equity"): "equity",
}


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse: ...


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
    """Bounded standard-library transport; contract tests inject a fake."""

    def __init__(self, opener: OpenerDirector | None = None) -> None:
        self._opener = opener or build_opener(_NoRedirect())

    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("SEC response exceeds the configured safety bound")
                return HttpResponse(response.status, body)
        except HTTPError as error:
            return HttpResponse(error.code, error.read(MAX_RESPONSE_BYTES + 1))
        except (TimeoutError, URLError):
            raise RuntimeError("SEC request failed before receiving a response") from None


class SecSource(FinancialFetcher, InstrumentUniverseFetcher):
    """Fetch one explicitly identified SEC filer without authentication or fallback."""

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
                False, "invalid_configuration", str(error), "Fix the SEC source settings."
            )
        try:
            self._user_agent()
        except ValueError as error:
            return SourceDiagnostic(
                False,
                "invalid_user_agent",
                str(error),
                f"Set {USER_AGENT_ENV} to an organization and contact email for this command.",
            )
        return SourceDiagnostic(True, "ready", "SEC source is configured.")

    def fetch_financials(self, request: FactFetchRequest) -> ImportedFinancials:
        cik, forms, timeout = self._settings(request.settings)
        self._validate_instrument(request)
        headers = {"Accept": "application/json", "User-Agent": self._user_agent()}
        bodies: list[bytes] = []

        root = self._get_json(f"{SUBMISSIONS_URL}/CIK{cik}.json", headers, timeout, bodies)
        submission_rows = self._submission_rows(root, cik)
        for name in self._additional_files(root, request):
            page = self._get_json(f"{SUBMISSIONS_URL}/{name}", headers, timeout, bodies)
            submission_rows.extend(self._submission_rows(page, cik, additional=True))
        filings = self._filings(submission_rows, request, forms)

        facts_document = self._get_json(
            f"{COMPANY_FACTS_URL}/CIK{cik}.json", headers, timeout, bodies
        )
        facts = self._facts(facts_document, cik, filings)
        filings = self._filing_accounting_dimensions(filings, facts)
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("source clock must return an offset-aware datetime")
        if any(filing.published_at > retrieved_at for filing in filings):
            raise ValueError("SEC returned a filing published after retrieval")

        digest = hashlib.sha256()
        for body in bodies:
            digest.update(hashlib.sha256(body).digest())
        missing = () if facts else ("no_supported_financial_facts",)
        return ImportedFinancials(
            request,
            "sec",
            SOURCE_VERSION,
            "submissions+api/xbrl/companyfacts",
            retrieved_at,
            facts,
            digest.hexdigest(),
            missing,
            filings,
        )

    def fetch_universe(self, request: UniverseRequest) -> ImportedInstrumentUniverse:
        if request.market != "us":
            raise ValueError("SEC instrument universe supports only the us market")
        timeout = self._universe_timeout(request.settings)
        headers = {"Accept": "application/json", "User-Agent": self._user_agent()}
        bodies: list[bytes] = []
        document = self._get_json(COMPANY_TICKERS_EXCHANGE_URL, headers, timeout, bodies)
        fields = document.get("fields")
        rows = document.get("data")
        if fields != ["cik", "name", "ticker", "exchange"]:
            raise ValueError("SEC company ticker fields do not match the supported contract")
        if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
            raise ValueError("SEC company ticker data must be an array of arrays")
        exchange_mics = {"Nasdaq": "XNAS", "NYSE": "XNYS", "NYSE American": "XASE"}
        instruments: list[Instrument] = []
        skipped = 0
        for row in rows:
            if len(row) != 4 or not isinstance(row[2], str) or not isinstance(row[3], str):
                skipped += 1
                continue
            mic = exchange_mics.get(row[3])
            if mic is None:
                skipped += 1
                continue
            try:
                instruments.append(
                    Instrument.create(
                        symbol=row[2].upper(),
                        mic=mic,
                        currency="USD",
                        exchange_timezone="America/New_York",
                    )
                )
            except ValueError:
                skipped += 1
        ordered = tuple(sorted(instruments, key=lambda item: (item.mic, item.symbol)))
        identities = tuple((item.mic, item.symbol) for item in ordered)
        if len(identities) != len(set(identities)):
            raise ValueError("SEC returned duplicate instrument identities")
        if not ordered:
            raise ValueError("SEC returned no supported US exchange instruments")
        selected = ordered[: request.limit]
        return ImportedInstrumentUniverse(
            request=request,
            source_name="sec",
            source_version=SOURCE_VERSION,
            dataset="company_tickers_exchange",
            retrieved_at=self._clock(),
            instruments=selected,
            source_hash=hashlib.sha256(bodies[0]).hexdigest(),
            provider_total=len(ordered),
            truncated=len(ordered) > len(selected),
            diagnostics=tuple(
                message
                for condition, message in (
                    (skipped > 0, f"unsupported_rows_skipped:{skipped}"),
                    (len(ordered) > len(selected), f"limit_reached:{request.limit}"),
                )
                if condition
            ),
        )

    @staticmethod
    def _universe_timeout(settings: Mapping[str, str]) -> float:
        unknown = set(settings) - {"timeout_seconds"}
        if unknown:
            raise ValueError(f"unsupported SEC universe setting: {sorted(unknown)[0]}")
        try:
            timeout = float(settings.get("timeout_seconds", "10"))
        except ValueError as error:
            raise ValueError("SEC timeout_seconds must be numeric") from error
        if not 0 < timeout <= 60:
            raise ValueError("SEC timeout_seconds must be greater than zero and at most 60")
        return timeout

    @staticmethod
    def _validate_instrument(request: FactFetchRequest) -> None:
        instrument = request.instrument
        if instrument.mic not in {"XNAS", "XNYS"}:
            raise ValueError("SEC source supports XNAS and XNYS instruments only")
        if instrument.currency != "USD":
            raise ValueError("SEC source requires a USD instrument")

    @staticmethod
    def _settings(settings: Mapping[str, str]) -> tuple[str, tuple[str, ...], float]:
        unknown = set(settings) - ALLOWED_SETTINGS
        if unknown:
            raise ValueError(f"unsupported SEC setting: {sorted(unknown)[0]}")
        cik = settings.get("cik", "")
        if not CIK_PATTERN.fullmatch(cik):
            raise ValueError("SEC cik must contain exactly ten digits")
        raw_forms = settings.get("forms", ",".join(DEFAULT_FORMS))
        forms = tuple(part.strip() for part in raw_forms.split(","))
        if not forms or any(not form for form in forms) or len(set(forms)) != len(forms):
            raise ValueError("SEC forms must be a non-empty unique comma-separated list")
        unsupported = set(forms) - ALLOWED_FORMS
        if unsupported:
            raise ValueError(f"unsupported SEC form: {sorted(unsupported)[0]}")
        try:
            timeout = float(settings.get("timeout_seconds", "10"))
        except ValueError as error:
            raise ValueError("SEC timeout_seconds must be numeric") from error
        if not 0 < timeout <= 60:
            raise ValueError("SEC timeout_seconds must be greater than zero and at most 60")
        return cik, forms, timeout

    def _user_agent(self) -> str:
        value = self._environ.get(USER_AGENT_ENV, "").strip()
        if not value or "@" not in value or len(value) > 200 or "\n" in value or "\r" in value:
            raise ValueError(f"{USER_AGENT_ENV} must identify an organization and contact email")
        return value

    def _get_json(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
        bodies: list[bytes],
    ) -> dict[str, Any]:
        if self._request_count:
            self._sleeper(MIN_REQUEST_INTERVAL_SECONDS)
        self._request_count += 1
        response = self._transport.get(url, headers=headers, timeout=timeout)
        if response.status in {301, 302, 303, 307, 308}:
            raise RuntimeError("SEC redirect rejected")
        if response.status == 403:
            raise RuntimeError("SEC fair-access request rejected")
        if response.status == 404:
            raise RuntimeError("SEC filer or data resource was not found")
        if response.status == 429:
            raise RuntimeError("SEC rate limit reached")
        if response.status != 200:
            raise RuntimeError(f"SEC request failed with HTTP status {response.status}")
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("SEC response exceeds the configured safety bound")
        try:
            document = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("SEC response is not valid JSON") from error
        if not isinstance(document, dict):
            raise ValueError("SEC response must be a JSON object")
        bodies.append(response.body)
        return document

    @staticmethod
    def _additional_files(
        document: Mapping[str, Any], request: FactFetchRequest
    ) -> tuple[str, ...]:
        filings = document.get("filings")
        if not isinstance(filings, dict):
            return ()
        files = filings.get("files", [])
        if not isinstance(files, list) or any(not isinstance(item, dict) for item in files):
            raise ValueError("SEC submissions files must be an array of objects")
        if len(files) > MAX_SUBMISSION_FILES:
            raise ValueError("SEC submissions file count exceeds the safety bound")
        names: list[str] = []
        for item in files:
            try:
                name = str(item["name"])
                filing_from = date.fromisoformat(str(item["filingFrom"]))
                filing_to = date.fromisoformat(str(item["filingTo"]))
            except (KeyError, ValueError) as error:
                raise ValueError("SEC submissions file metadata is invalid") from error
            if not re.fullmatch(r"CIK[0-9]{10}-submissions-[0-9]{3}\.json", name):
                raise ValueError("SEC submissions file name is unsafe")
            if filing_from > filing_to:
                raise ValueError("SEC submissions file range must be ascending")
            if filing_from <= request.end and filing_to >= request.start:
                names.append(name)
        if len(set(names)) != len(names):
            raise ValueError("SEC submissions file names must be unique")
        return tuple(names)

    @staticmethod
    def _submission_rows(
        document: Mapping[str, Any], cik: str, *, additional: bool = False
    ) -> list[dict[str, Any]]:
        response_cik = document.get("cik")
        if response_cik is not None and str(response_cik).zfill(10) != cik:
            raise ValueError("SEC returned submissions for a different CIK")
        table: Any = document
        if not additional:
            filings = document.get("filings")
            if not isinstance(filings, dict) or not isinstance(filings.get("recent"), dict):
                raise ValueError("SEC recent submissions table is missing")
            table = filings["recent"]
        if not isinstance(table, dict):
            raise ValueError("SEC submissions table must be an object")
        required = ("accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form")
        columns = [table.get(name) for name in required]
        if any(not isinstance(column, list) for column in columns):
            raise ValueError("SEC submissions columns are missing")
        lengths = {len(column) for column in columns if isinstance(column, list)}
        if len(lengths) != 1:
            raise ValueError("SEC submissions columns have different lengths")
        return [dict(zip(required, values, strict=True)) for values in zip(*columns, strict=True)]

    @classmethod
    def _filings(
        cls,
        rows: Sequence[Mapping[str, Any]],
        request: FactFetchRequest,
        forms: tuple[str, ...],
    ) -> tuple[FilingDocument, ...]:
        parsed: list[FilingDocument] = []
        seen: set[str] = set()
        for row in rows:
            accession = str(row["accessionNumber"])
            if not ACCESSION_PATTERN.fullmatch(accession):
                raise ValueError("SEC accession number is invalid")
            if accession in seen:
                raise ValueError("SEC submissions contain a duplicate accession number")
            seen.add(accession)
            try:
                filed = date.fromisoformat(str(row["filingDate"]))
            except ValueError as error:
                raise ValueError("SEC filing date is invalid") from error
            form = str(row["form"])
            if form not in forms or not request.start <= filed <= request.end:
                continue
            report_raw = str(row.get("reportDate", ""))
            try:
                report_end = date.fromisoformat(report_raw) if report_raw else None
            except ValueError as error:
                raise ValueError("SEC report date is invalid") from error
            published_at = cls._acceptance_datetime(str(row["acceptanceDateTime"]))
            base_form = form.removesuffix("/A")
            period = (
                FinancialPeriod.ANNUAL
                if base_form in {"10-K", "20-F", "40-F"}
                else FinancialPeriod.QUARTERLY
            )
            parsed.append(
                FilingDocument(
                    accession,
                    request.settings["cik"],
                    form,
                    published_at,
                    period,
                    None,
                    report_end,
                    None,
                    Consolidation.UNKNOWN,
                    None,
                )
            )
        parsed.sort(key=lambda filing: (filing.published_at, filing.filing_id))
        by_period: dict[tuple[str, date | None], str] = {}
        linked: list[FilingDocument] = []
        for filing in parsed:
            base_form = filing.document_type.removesuffix("/A")
            key = (base_form, filing.fiscal_period_end)
            amends = by_period.get(key) if filing.document_type.endswith("/A") else None
            linked.append(replace(filing, amends_filing_id=amends))
            if not filing.document_type.endswith("/A"):
                by_period[key] = filing.filing_id
        return tuple(linked)

    @staticmethod
    def _acceptance_datetime(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("SEC acceptance time is invalid") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("SEC acceptance time must include a UTC offset")
        return parsed

    @classmethod
    def _facts(
        cls,
        document: Mapping[str, Any],
        cik: str,
        filings: tuple[FilingDocument, ...],
    ) -> tuple[FinancialFact, ...]:
        if str(document.get("cik", "")).zfill(10) != cik:
            raise ValueError("SEC returned company facts for a different CIK")
        taxonomies = document.get("facts")
        if not isinstance(taxonomies, dict):
            raise ValueError("SEC company facts object is missing")
        filings_by_id = {filing.filing_id: filing for filing in filings}
        facts: list[FinancialFact] = []
        identities: dict[tuple[Any, ...], Decimal] = {}
        for (taxonomy, tag), concept in CONCEPTS.items():
            taxonomy_document = taxonomies.get(taxonomy, {})
            if not isinstance(taxonomy_document, dict):
                raise ValueError("SEC taxonomy facts must be an object")
            concept_document = taxonomy_document.get(tag)
            if concept_document is None:
                continue
            if not isinstance(concept_document, dict) or not isinstance(
                concept_document.get("units"), dict
            ):
                raise ValueError("SEC concept units must be an object")
            for unit, rows in concept_document["units"].items():
                if (
                    not isinstance(unit, str)
                    or not isinstance(rows, list)
                    or any(not isinstance(row, dict) for row in rows)
                ):
                    raise ValueError("SEC company fact unit rows are invalid")
                if unit not in {"USD", "USD/shares"}:
                    continue
                for row in rows:
                    filing = filings_by_id.get(str(row.get("accn", "")))
                    if filing is None:
                        continue
                    if str(row.get("end", "")) != (
                        filing.fiscal_period_end.isoformat()
                        if filing.fiscal_period_end is not None
                        else ""
                    ):
                        continue
                    fact = cls._fact(row, taxonomy, tag, concept, filing)
                    identity = (
                        fact.provider_fact,
                        fact.period,
                        fact.provider_period,
                        fact.fiscal_period_start,
                        fact.fiscal_period_end,
                        fact.filing_id,
                        fact.currency,
                    )
                    previous = identities.get(identity)
                    if previous is not None:
                        if previous != fact.value:
                            raise ValueError(
                                "SEC company facts contain conflicting duplicate values"
                            )
                        continue
                    identities[identity] = fact.value
                    facts.append(fact)
        return tuple(
            sorted(facts, key=lambda fact: (fact.available_at, fact.concept, fact.provider_fact))
        )

    @classmethod
    def _fact(
        cls,
        row: Mapping[str, Any],
        taxonomy: str,
        tag: str,
        concept: str,
        filing: FilingDocument,
    ) -> FinancialFact:
        try:
            period_end = date.fromisoformat(str(row["end"]))
            raw_start = row.get("start")
            period_start = date.fromisoformat(str(raw_start)) if raw_start else None
            value = Decimal(str(row["val"]))
        except (KeyError, ValueError, InvalidOperation) as error:
            raise ValueError("SEC company fact value or period is invalid") from error
        if not value.is_finite():
            raise ValueError("SEC company fact value must be finite")
        form = str(row.get("form", ""))
        if form != filing.document_type:
            raise ValueError("SEC company fact form does not match its filing")
        provider_period = str(row.get("fp", ""))
        period = cls._financial_period(filing, period_start, period_end)
        return FinancialFact(
            concept,
            f"{taxonomy}:{tag}",
            "US-GAAP" if taxonomy == "us-gaap" else "IFRS",
            period,
            provider_period or filing.document_type,
            period_start,
            period_end,
            filing.published_at,
            filing.published_at,
            AvailabilityBasis.PUBLISHED,
            Consolidation.UNKNOWN,
            Revision.RESTATED if filing.document_type.endswith("/A") else Revision.REPORTED,
            "USD",
            1,
            value,
            filing.filing_id,
        )

    @staticmethod
    def _financial_period(
        filing: FilingDocument, period_start: date | None, period_end: date
    ) -> FinancialPeriod:
        if filing.period is FinancialPeriod.ANNUAL:
            return FinancialPeriod.ANNUAL
        if period_start is not None and (period_end - period_start).days > 120:
            return FinancialPeriod.INTERIM_YTD
        return FinancialPeriod.QUARTERLY

    @staticmethod
    def _filing_accounting_dimensions(
        filings: tuple[FilingDocument, ...], facts: tuple[FinancialFact, ...]
    ) -> tuple[FilingDocument, ...]:
        standards: dict[str, set[str]] = {}
        currencies: dict[str, set[str]] = {}
        starts: dict[str, set[date]] = {}
        for fact in facts:
            if fact.filing_id is None:
                continue
            if fact.accounting_standard is not None:
                standards.setdefault(fact.filing_id, set()).add(fact.accounting_standard)
            currencies.setdefault(fact.filing_id, set()).add(fact.currency)
            if fact.fiscal_period_start is not None:
                starts.setdefault(fact.filing_id, set()).add(fact.fiscal_period_start)
        enriched: list[FilingDocument] = []
        for filing in filings:
            filing_standards = standards.get(filing.filing_id, set())
            filing_currencies = currencies.get(filing.filing_id, set())
            filing_starts = starts.get(filing.filing_id, set())
            enriched.append(
                replace(
                    filing,
                    accounting_standard=(
                        next(iter(filing_standards)) if len(filing_standards) == 1 else None
                    ),
                    currency=(
                        next(iter(filing_currencies)) if len(filing_currencies) == 1 else None
                    ),
                    fiscal_period_start=(
                        next(iter(filing_starts)) if len(filing_starts) == 1 else None
                    ),
                )
            )
        return tuple(enriched)
