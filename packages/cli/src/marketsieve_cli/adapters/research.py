"""Immutable self-contained security research storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from marketsieve_extension_api import ImportedSecurityResearch

from .explorer_v2 import build_research_explorer_data, render_explorer

ARTIFACTS = (
    "README.md",
    "manifest.json",
    "definitions.json",
    "company.json",
    "market-context.json",
    "prices.jsonl",
    "benchmarks.jsonl",
    "financials.jsonl",
    "events.jsonl",
    "failures.jsonl",
    "quality.json",
    "summary.md",
    "explorer-data.json",
    "explorer.html",
)

COMPANY_TEXT_FIELDS = (
    "country",
    "currency",
    "exchange",
    "exchange_name",
    "financial_currency",
    "industry",
    "long_name",
    "name",
    "quote_type",
    "sector",
)
COMPANY_NUMERIC_FIELDS = {
    "current_ratio": ("ratio", "Current assets divided by current liabilities."),
    "debt_to_equity": ("ratio", "Debt divided by equity; provider percentage points normalized."),
    "dividend_yield": ("ratio", "Indicated annual dividend divided by price."),
    "earnings_growth": ("ratio", "Provider-reported earnings growth."),
    "earnings_quarterly_growth": ("ratio", "Provider-reported quarterly earnings growth."),
    "ebitda_ttm": ("financial_currency", "Trailing twelve-month EBITDA."),
    "enterprise_to_ebitda": ("multiple", "Enterprise value divided by EBITDA."),
    "enterprise_to_revenue": ("multiple", "Enterprise value divided by revenue."),
    "enterprise_value": ("instrument_currency", "Provider-reported enterprise value."),
    "forward_eps": ("instrument_currency_per_share", "Provider forward earnings per share."),
    "forward_pe": ("multiple", "Price divided by provider forward earnings per share."),
    "free_cash_flow_ttm": ("financial_currency", "Trailing twelve-month free cash flow."),
    "gross_margin": ("ratio", "Gross profit divided by revenue."),
    "market_cap": ("instrument_currency", "Price multiplied by shares outstanding."),
    "net_income_ttm": ("financial_currency", "Trailing twelve-month common net income."),
    "net_margin": ("ratio", "Net income divided by revenue."),
    "operating_cash_flow_ttm": ("financial_currency", "Trailing operating cash flow."),
    "operating_income_ttm": ("financial_currency", "Trailing operating income."),
    "operating_margin": ("ratio", "Operating income divided by revenue."),
    "payout_ratio": ("ratio", "Dividends divided by earnings."),
    "price_to_book": ("multiple", "Price divided by book value per share."),
    "price_to_sales": ("multiple", "Market value divided by trailing revenue."),
    "quick_ratio": ("ratio", "Liquid current assets divided by current liabilities."),
    "return_on_assets": ("ratio", "Provider-reported return on assets."),
    "return_on_equity": ("ratio", "Provider-reported return on equity."),
    "revenue_growth": ("ratio", "Provider-reported revenue growth."),
    "revenue_ttm": ("financial_currency", "Trailing twelve-month revenue."),
    "shares_outstanding": ("shares", "Provider-reported shares outstanding."),
    "total_cash": ("financial_currency", "Provider-reported cash and equivalents."),
    "total_debt": ("financial_currency", "Provider-reported total debt."),
    "trailing_eps": ("instrument_currency_per_share", "Trailing earnings per share."),
    "trailing_pe": ("multiple", "Price divided by trailing earnings per share."),
}
FINANCIAL_CONCEPTS = {
    "income": (
        "diluted_eps",
        "ebitda",
        "gross_profit",
        "net_income",
        "operating_income",
        "pretax_income",
        "revenue",
    ),
    "balance_sheet": (
        "accounts_receivable",
        "cash_and_short_term_investments",
        "current_assets",
        "current_liabilities",
        "inventory",
        "stockholders_equity",
        "total_assets",
        "total_debt",
    ),
    "cash_flow": (
        "capital_expenditure",
        "debt_issuance",
        "debt_repayment",
        "dividends_paid",
        "free_cash_flow",
        "operating_cash_flow",
        "share_issuance",
        "share_repurchases",
    ),
}
PRICE_FIELDS = (
    ("date", "date", "trading_date"),
    ("open", "decimal", "instrument_currency"),
    ("high", "decimal", "instrument_currency"),
    ("low", "decimal", "instrument_currency"),
    ("close", "decimal", "instrument_currency"),
    ("volume", "integer", "split_adjusted_shares"),
    ("adjustment", "string", "adjusted"),
)
EVENT_FIELDS = {
    "dividend": (("amount", "decimal", "event_currency"), ("currency", "string", "ISO_4217")),
    "earnings": (
        ("estimated_eps", "decimal", "provider_reported_currency_per_share"),
        ("reported_eps", "decimal", "provider_reported_currency_per_share"),
        ("surprise_percent", "decimal", "percent"),
    ),
    "split": (("ratio", "decimal", "new_shares_per_old_share"),),
}

EVIDENCE_STATES = (
    "available",
    "none_observed",
    "not_requested",
    "acquisition_failed",
)


def _evidence_statuses(
    requested: set[str],
    *,
    prices: tuple[dict[str, Any], ...],
    company: Mapping[str, Any],
    financials: tuple[dict[str, Any], ...],
    events: tuple[dict[str, Any], ...],
    benchmarks: tuple[dict[str, Any], ...],
    failures: tuple[dict[str, Any], ...],
) -> dict[str, str]:
    """Classify each independently retrievable evidence domain."""

    failed_fields = {str(value["field"]) for value in failures if value["stage"] != "benchmark"}

    def status(request: str, available: bool, failed: bool) -> str:
        if request not in requested:
            return "not_requested"
        if available:
            return "available"
        if failed:
            return "acquisition_failed"
        return "none_observed"

    annual_failures = {
        "income_yearly",
        "balance_sheet_yearly",
        "cash_flow_yearly",
        "annual_income",
    }
    quarterly_failures = {
        "income_quarterly",
        "balance_sheet_quarterly",
        "cash_flow_quarterly",
        "quarterly_income",
        "quarterly_cash_flow",
        "balance_sheet",
    }
    has_action_failure = "actions" in failed_fields
    values = cast(Mapping[str, Any], company.get("values", {}))
    result = {
        "price": status("price", bool(prices), bool(failed_fields & {"price", "history"})),
        "company": status("company", bool(values), "company" in failed_fields),
        "annual_financials": status(
            "financials",
            any(value["period"] == "annual" for value in financials),
            bool(failed_fields & annual_failures) or "company_financials" in failed_fields,
        ),
        "quarterly_financials": status(
            "financials",
            any(value["period"] == "quarterly" for value in financials),
            bool(failed_fields & quarterly_failures) or "company_financials" in failed_fields,
        ),
        "earnings": status(
            "events",
            any(value["event_type"] == "earnings" for value in events),
            "earnings" in failed_fields,
        ),
        "dividends": status(
            "events",
            any(value["event_type"] == "dividend" for value in events),
            has_action_failure,
        ),
        "splits": status(
            "events",
            any(value["event_type"] == "split" for value in events),
            has_action_failure,
        ),
        "benchmarks": status(
            "benchmarks",
            bool(benchmarks),
            any(value["stage"] == "benchmark" for value in failures),
        ),
    }
    if any(value not in EVIDENCE_STATES for value in result.values()):
        raise AssertionError("unsupported evidence state")
    return result


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _write_jsonl(path: Path, documents: Iterable[object]) -> None:
    with path.open("wb") as stream:
        for document in documents:
            stream.write(_json_bytes(document))


class ResearchStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / "objects"

    def put(
        self,
        imported: ImportedSecurityResearch,
        context: dict[str, Any],
        *,
        minimum_price_observations: int,
        runtime_settings: dict[str, Any],
        runtime_settings_hash: str,
        benchmarks: Any | None,
    ) -> dict[str, Any]:
        instrument_id = f"{imported.request.instrument.mic}:{imported.request.instrument.symbol}"
        snapshot_definitions = context.get("definitions")
        if not isinstance(snapshot_definitions, dict):
            raise ValueError("market research context must include Snapshot definitions")
        market_context = {key: value for key, value in context.items() if key != "definitions"}
        company = {
            "schema": "security-research-company/v1",
            "instrument_id": instrument_id,
            "provider_symbol": imported.request.provider_symbol,
            "retrieved_at": imported.retrieved_at.isoformat(),
            "availability_basis": "retrieval",
            "values": dict(imported.company),
        }
        prices = tuple(
            {
                "schema": "security-research-price/v1",
                "date": bar.trading_date.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": bar.volume if bar.volume != 0 else None,
                "adjustment": bar.adjustment.value,
                "missing": {"volume": "field_absent"} if bar.volume == 0 else {},
            }
            for bar in imported.bars
        )
        benchmark_prices = tuple(
            {
                "schema": "security-research-benchmark-price/v1",
                "benchmark": observation.requested.memberships[0],
                "provider_symbol": observation.requested.provider_symbol,
                "date": bar.trading_date.isoformat(),
                "close": str(bar.close),
                "adjustment": bar.adjustment.value,
            }
            for observation in (() if benchmarks is None else benchmarks.observations)
            for bar in observation.bars
        )
        financials = tuple(
            {
                "schema": "security-research-financial/v1",
                "concept": fact.concept,
                "statement": fact.statement,
                "period": fact.period,
                "fiscal_period_end": fact.fiscal_period_end.isoformat(),
                "currency": fact.currency,
                "value": str(fact.value),
                "available_at": imported.retrieved_at.isoformat(),
                "availability_basis": "retrieval",
            }
            for fact in imported.financials
        )
        events = tuple(
            {
                "schema": "security-research-event/v1",
                "event_type": event.event_type,
                "effective_date": event.effective_date.isoformat(),
                "values": dict(event.values),
                "available_at": imported.retrieved_at.isoformat(),
                "availability_basis": "retrieval",
            }
            for event in imported.events
        )
        failures = tuple(
            {
                "schema": "security-research-failure/v1",
                "instrument_id": instrument_id,
                "stage": failure.stage,
                "field": failure.field,
                "reason": failure.reason,
            }
            for failure in imported.failures
        ) + tuple(
            {
                "schema": "security-research-failure/v1",
                "instrument_id": (f"{failure.instrument.mic}:{failure.instrument.symbol}"),
                "stage": "benchmark",
                "field": failure.field,
                "reason": failure.reason,
            }
            for failure in (() if benchmarks is None else benchmarks.failures)
        )
        price_requested = "price" in imported.request.evidence
        requirements_met = (not price_requested) or len(prices) >= minimum_price_observations
        failures_by_reason: dict[str, int] = {}
        failures_by_stage: dict[str, int] = {}
        for failure in failures:
            failures_by_reason[failure["reason"]] = failures_by_reason.get(failure["reason"], 0) + 1
            failures_by_stage[failure["stage"]] = failures_by_stage.get(failure["stage"], 0) + 1
        requested = set(imported.request.evidence)
        evidence_statuses = _evidence_statuses(
            requested,
            prices=prices,
            company=company,
            financials=financials,
            events=events,
            benchmarks=benchmark_prices,
            failures=failures,
        )
        financial_dates = [value["fiscal_period_end"] for value in financials]
        retrieved_date = imported.retrieved_at.date()
        company_values = cast(dict[str, str], company["values"])
        ratio_unit_issues = [
            name
            for name, value in company_values.items()
            if name == "dividend_yield" and not Decimal(0) <= Decimal(value) <= Decimal(1)
        ]
        quality = {
            "schema": "security-research-quality/v3",
            "requested_evidence": list(imported.request.evidence),
            "minimum_price_observations": minimum_price_observations,
            "price_observations": len(prices),
            "price_requirements_met": requirements_met,
            "company_fields": len(company["values"]),
            "financial_facts": len(financials),
            "financial_facts_by_period": {
                period: sum(value["period"] == period for value in financials)
                for period in ("annual", "quarterly")
            },
            "events": len(events),
            "evidence_statuses": evidence_statuses,
            "benchmark_observations": len(benchmark_prices),
            "failures": len(failures),
            "failures_by_reason": dict(sorted(failures_by_reason.items())),
            "failures_by_stage": dict(sorted(failures_by_stage.items())),
            "price_date_range": {
                "start": prices[0]["date"] if prices else None,
                "end": prices[-1]["date"] if prices else None,
            },
            "freshness": {
                "price_age_days": (
                    (retrieved_date - date.fromisoformat(str(prices[-1]["date"]))).days
                    if prices
                    else None
                ),
                "financial_age_days": (
                    (
                        retrieved_date - max(date.fromisoformat(value) for value in financial_dates)
                    ).days
                    if financial_dates
                    else None
                ),
            },
            "unit_checks": {
                "issue_count": len(ratio_unit_issues),
                "fields": ratio_unit_issues,
            },
        }
        definitions = {
            "schema": "security-research-definitions/v3",
            "availability_basis": {
                "retrieval": (
                    "The provider did not expose publication time; "
                    "the value is known only at retrieval."
                )
            },
            "periods": {"annual": "Annual statement", "quarterly": "Quarterly statement"},
            "company_fields": [
                {
                    "name": name,
                    "data_type": "string",
                    "availability_basis": "retrieval",
                    "source": "yfinance company information",
                }
                for name in COMPANY_TEXT_FIELDS
            ]
            + [
                {
                    "name": name,
                    "data_type": "decimal",
                    "storage_type": "string",
                    "unit": unit,
                    "definition": definition,
                    "availability_basis": "retrieval",
                    "source": "yfinance company information",
                }
                for name, (unit, definition) in COMPANY_NUMERIC_FIELDS.items()
            ],
            "financial_concepts": [
                {
                    "concept": concept,
                    "statement": statement,
                    "data_type": "decimal",
                    "unit": "reporting_currency_per_share"
                    if concept == "diluted_eps"
                    else "reporting_currency",
                    "availability_basis": "retrieval",
                    "source": "yfinance financial statement",
                }
                for statement, concepts in FINANCIAL_CONCEPTS.items()
                for concept in concepts
            ],
            "price_fields": [
                {
                    "name": name,
                    "data_type": data_type,
                    "unit": unit,
                    "nullable": name == "volume",
                    **(
                        {"missing_reason": "field_absent when yfinance zero-fills missing volume"}
                        if name == "volume"
                        else {}
                    ),
                }
                for name, data_type, unit in PRICE_FIELDS
            ],
            "event_types": [
                {
                    "name": event_type,
                    "fields": [
                        {"name": name, "data_type": data_type, "unit": unit}
                        for name, data_type, unit in fields
                    ],
                }
                for event_type, fields in EVENT_FIELDS.items()
            ],
            "market_context": {
                "security": "The selected Snapshot security row.",
                "market": "The selected Snapshot all, JP, and US aggregates.",
                "segments": "Matching index, sector, and industry aggregates.",
                "snapshot_definitions": snapshot_definitions,
            },
            "missing_policy": "Missing provider values are not imputed or replaced.",
        }
        manifest_body = {
            "created_at": imported.retrieved_at.isoformat(),
            "snapshot_id": context["snapshot_id"],
            "instrument_id": instrument_id,
            "provider_symbol": imported.request.provider_symbol,
            "source": {
                "name": imported.source_name,
                "version": imported.source_version,
                "response_hash": imported.response_hash,
            },
            "inputs": {
                "start": imported.request.start.isoformat(),
                "end": imported.request.end.isoformat(),
                "adjustment": imported.request.adjustment.value,
                "evidence": list(imported.request.evidence),
            },
            "runtime_settings": runtime_settings,
            "runtime_settings_hash": runtime_settings_hash,
            "price_requirements_met": requirements_met,
            "artifacts": {name: name for name in ARTIFACTS},
        }
        semantic = {
            **manifest_body,
            "definitions": definitions,
            "company": company,
            "market_context": market_context,
            "prices": prices,
            "benchmarks": benchmark_prices,
            "financials": financials,
            "events": events,
            "failures": failures,
            "quality": quality,
        }
        research_id = hashlib.sha256(_json_bytes(semantic)).hexdigest()
        manifest = {
            "schema": "security-research-manifest/v6",
            "research_id": research_id,
            **manifest_body,
        }
        explorer_data = build_research_explorer_data(manifest, definitions)
        self._ensure_directory(self.objects)
        destination = self.objects / research_id
        if destination.is_symlink():
            raise ValueError("security research object path must be a real directory")
        if not destination.exists():
            pending = self.objects / f".{research_id}.{os.getpid()}.pending"
            if pending.exists() or pending.is_symlink():
                raise ValueError("security research pending path already exists")
            pending.mkdir()
            try:
                (pending / "manifest.json").write_bytes(_json_bytes(manifest))
                (pending / "definitions.json").write_bytes(_json_bytes(definitions))
                (pending / "company.json").write_bytes(_json_bytes(company))
                (pending / "market-context.json").write_bytes(_json_bytes(market_context))
                _write_jsonl(pending / "prices.jsonl", prices)
                _write_jsonl(pending / "benchmarks.jsonl", benchmark_prices)
                _write_jsonl(pending / "financials.jsonl", financials)
                _write_jsonl(pending / "events.jsonl", events)
                _write_jsonl(pending / "failures.jsonl", failures)
                (pending / "quality.json").write_bytes(_json_bytes(quality))
                (pending / "README.md").write_text(self._readme(manifest), encoding="utf-8")
                (pending / "summary.md").write_text(
                    self._summary(manifest, quality), encoding="utf-8"
                )
                (pending / "explorer-data.json").write_bytes(_json_bytes(explorer_data))
                (pending / "explorer.html").write_text(
                    render_explorer(explorer_data),
                    encoding="utf-8",
                )
                pending.rename(destination)
            except BaseException:
                shutil.rmtree(pending, ignore_errors=True)
                raise
        self._verify(destination, research_id)
        return self.show(research_id)

    def show(self, research_id: str) -> dict[str, Any]:
        if len(research_id) != 64 or any(
            character not in "0123456789abcdef" for character in research_id
        ):
            raise LookupError(f"security research does not exist: {research_id}")
        self._require_directory(self.objects)
        path = self.objects / research_id
        self._verify(path, research_id)
        manifest = self._read_json(path / "manifest.json")
        return {
            **manifest,
            "schema": "security-research/v6",
            "quality": self._read_json(path / "quality.json"),
            "artifacts": {name: str(path / name) for name in ARTIFACTS},
        }

    def latest(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        matches = [
            item
            for item in self.list(snapshot_id=snapshot_id, instrument_id=instrument_id)["research"]
        ]
        if not matches:
            raise LookupError(f"security research does not exist: {instrument_id}")
        return self.show(matches[0]["research_id"])

    def list(
        self, *, snapshot_id: str | None = None, instrument_id: str | None = None
    ) -> dict[str, Any]:
        if not self.objects.exists():
            return {"schema": "security-research-list/v2", "research": []}
        self._require_directory(self.objects)
        items = []
        for path in self.objects.iterdir():
            if path.name.startswith("."):
                continue
            self._verify(path, path.name)
            manifest = self._read_json(path / "manifest.json")
            if snapshot_id is not None and manifest["snapshot_id"] != snapshot_id:
                continue
            if instrument_id is not None and manifest["instrument_id"] != instrument_id:
                continue
            items.append(
                {
                    "research_id": path.name,
                    "snapshot_id": manifest["snapshot_id"],
                    "instrument_id": manifest["instrument_id"],
                    "created_at": manifest["created_at"],
                    "price_requirements_met": manifest["price_requirements_met"],
                }
            )
        items.sort(
            key=lambda item: (datetime.fromisoformat(item["created_at"]), item["research_id"]),
            reverse=True,
        )
        return {"schema": "security-research-list/v2", "research": items}

    @staticmethod
    def _readme(manifest: dict[str, Any]) -> str:
        return (
            "# MarketSieve Security Research Pack\n\n"
            "This directory contains retrieval-time evidence for one security. "
            "It contains no score, recommendation, or AI conclusion.\n\n"
            f"- Research ID: `{manifest['research_id']}`\n"
            f"- Market Snapshot ID: `{manifest['snapshot_id']}`\n"
            f"- Security: `{manifest['instrument_id']}`\n"
            f"- Retrieved at: `{manifest['created_at']}`\n\n"
            "`prices.jsonl`, `financials.jsonl`, and `events.jsonl` are authoritative "
            "time-series evidence. `company.json` contains retrieval-time company facts. "
            "`quality.json` and `failures.jsonl` describe limitations.\n"
        )

    @staticmethod
    def _summary(manifest: dict[str, Any], quality: dict[str, Any]) -> str:
        return (
            "# Security Research Summary\n\n"
            f"- Security: `{manifest['instrument_id']}`\n"
            f"- Snapshot ID: `{manifest['snapshot_id']}`\n"
            f"- Price observations: {quality['price_observations']}\n"
            f"- Company fields: {quality['company_fields']}\n"
            f"- Financial facts: {quality['financial_facts']}\n"
            f"- Events: {quality['events']}\n"
            f"- Failures: {quality['failures']}\n"
            f"- Price requirements met: `{str(quality['price_requirements_met']).lower()}`\n"
        )

    @classmethod
    def _verify(cls, path: Path, research_id: str) -> None:
        if path.is_symlink() or not path.is_dir() or path.name != research_id:
            raise LookupError(f"security research does not exist: {research_id}")
        if {item.name for item in path.iterdir()} != set(ARTIFACTS):
            raise ValueError("security research object inventory is invalid")
        if any(not (path / name).is_file() or (path / name).is_symlink() for name in ARTIFACTS):
            raise ValueError("security research object is incomplete")
        manifest = cls._read_json(path / "manifest.json")
        if (
            manifest.get("schema") != "security-research-manifest/v6"
            or manifest.get("research_id") != research_id
        ):
            raise ValueError("security research manifest identity is invalid")
        semantic = {
            **{
                key: value
                for key, value in manifest.items()
                if key not in {"schema", "research_id"}
            },
            "definitions": cls._read_json(path / "definitions.json"),
            "company": cls._read_json(path / "company.json"),
            "market_context": cls._read_json(path / "market-context.json"),
            "prices": tuple(cls._read_jsonl(path / "prices.jsonl")),
            "benchmarks": tuple(cls._read_jsonl(path / "benchmarks.jsonl")),
            "financials": tuple(cls._read_jsonl(path / "financials.jsonl")),
            "events": tuple(cls._read_jsonl(path / "events.jsonl")),
            "failures": tuple(cls._read_jsonl(path / "failures.jsonl")),
            "quality": cls._read_json(path / "quality.json"),
        }
        if hashlib.sha256(_json_bytes(semantic)).hexdigest() != research_id:
            raise ValueError("security research content identity is invalid")
        quality = semantic["quality"]
        if (path / "README.md").read_text(encoding="utf-8") != cls._readme(manifest):
            raise ValueError("security research README projection is invalid")
        if (path / "summary.md").read_text(encoding="utf-8") != cls._summary(manifest, quality):
            raise ValueError("security research summary projection is invalid")
        explorer_data = cls._read_json(path / "explorer-data.json")
        expected_explorer_data = build_research_explorer_data(manifest, semantic["definitions"])
        if explorer_data != expected_explorer_data:
            raise ValueError("security research Explorer data projection is invalid")
        if (path / "explorer.html").read_text(encoding="utf-8") != render_explorer(explorer_data):
            raise ValueError("security research HTML projection is invalid")

    @staticmethod
    def _read_json(path: Path) -> Any:
        raw = path.read_bytes()
        value = json.loads(raw)
        if raw != _json_bytes(value):
            raise ValueError(f"security research JSON is not canonical: {path.name}")
        return value

    @staticmethod
    def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
        for line in path.read_bytes().splitlines(keepends=True):
            value = json.loads(line)
            if line != _json_bytes(value):
                raise ValueError(f"security research JSONL is not canonical: {path.name}")
            yield value

    def _ensure_directory(self, path: Path) -> None:
        current = self.root
        directories = [self.root.parent, self.root]
        for part in path.relative_to(self.root).parts:
            current /= part
            directories.append(current)
        if any(candidate.is_symlink() for candidate in directories):
            raise ValueError("security research storage path must be a real directory")
        path.mkdir(parents=True, exist_ok=True)
        if any(not candidate.is_dir() for candidate in directories):
            raise ValueError("security research storage path must be a real directory")

    def _require_directory(self, path: Path) -> None:
        current = self.root
        directories = [self.root.parent, self.root]
        for part in path.relative_to(self.root).parts:
            current /= part
            directories.append(current)
        if any(candidate.is_symlink() or not candidate.is_dir() for candidate in directories):
            raise LookupError("security research storage directory does not exist")
