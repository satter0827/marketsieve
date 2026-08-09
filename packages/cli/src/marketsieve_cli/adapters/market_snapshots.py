"""Immutable Market Snapshot storage and deterministic projections."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import cmp_to_key
from pathlib import Path
from typing import Any

from marketsieve.matrix import INDEX_BENCHMARKS, MatrixField, MatrixRow

from .artifacts import ArtifactInventory
from .explorer_v2 import build_snapshot_explorer_data, render_explorer

ARTIFACT_ROLES = {
    "README.md": "Self-contained description of the dataset and files.",
    "manifest.json": "Acquisition, universe, benchmark, artifact, and identity metadata.",
    "definitions.json": "Field and missing-value definitions.",
    "quality-summary.json": "Compact evidence coverage, freshness, and failure summary.",
    "quality-details.jsonl": "Detailed field and segment coverage records.",
    "quality-outliers.jsonl": "Unmodified values flagged by versioned quality rules.",
    "aggregates.jsonl": "Overall, market, index, sector, and industry aggregates.",
    "securities.jsonl": "Authoritative one-security-per-line observations.",
    "failures.jsonl": "Observed source, history, and calculation failures.",
    "market-indicators.jsonl": "Versioned yfinance macro and cross-asset observations.",
    "explorer.html": "Object-local interactive Market Explorer renderer.",
    "explorer-data.json": "Reference-only deterministic Explorer view contract.",
    "summary.md": "Compact neutral projection of market and segment aggregates.",
}

MISSING_REASONS = {
    "benchmark_unavailable": ("source", "The configured benchmark has no usable history."),
    "corporate_action_mismatch": (
        "source",
        "Adjusted prices are inconsistent with a reported stock split.",
    ),
    "currency_mismatch": ("calculation", "Required values use incompatible currencies."),
    "field_absent": ("source", "The provider did not supply the field."),
    "financials_unavailable": ("source", "Financial statements are unavailable."),
    "history_empty": ("history", "No price observations were returned."),
    "insufficient_history": ("history", "Too few observations exist for the calculation."),
    "network_error": ("source", "The provider request failed at the network boundary."),
    "not_applicable": ("expected", "The field does not apply to this security."),
    "not_requested": ("expected", "The evidence domain was not requested for this Snapshot."),
    "provider_error": ("source", "The provider returned an unclassified failure."),
    "rate_limited": ("source", "The provider rate-limited the request."),
    "stale_history": ("history", "The latest observation is older than the market reference."),
    "symbol_not_found": ("source", "The provider symbol was not found."),
    "zero_denominator": ("calculation", "The calculation denominator is zero."),
}


def _missing_reason_documents() -> list[dict[str, str]]:
    return [
        {"code": code, "category": category, "definition": definition}
        for code, (category, definition) in sorted(MISSING_REASONS.items())
    ]


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _request_fingerprint(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _row_document(row: MatrixRow) -> dict[str, Any]:
    instrument = row.security.instrument
    financials = dict(row.security.financials)
    price_as_of = dict(row.values).get("price_as_of")
    financial_period_end = financials.get("_financial_period_end")
    retrieved_date = row.security.retrieved_at.astimezone(UTC).date()
    return {
        "schema": "market-snapshot-security/v1",
        "instrument_id": f"{instrument.mic}:{instrument.symbol}",
        "instrument": {
            "mic": instrument.mic,
            "symbol": instrument.symbol,
            "currency": instrument.currency,
            "exchange_timezone": instrument.exchange_timezone.key,
            "instrument_type": instrument.instrument_type.value,
        },
        "provider_symbol": row.security.provider_symbol,
        "memberships": list(row.security.memberships),
        "retrieved_at": row.security.retrieved_at.isoformat(),
        "temporal": {
            "price_as_of": price_as_of,
            "retrieved_at": row.security.retrieved_at.isoformat(),
            "financial_period_end": financial_period_end,
            "financial_period_type": financials.get("_financial_period_type"),
            "availability_basis": financials.get("_availability_basis", "retrieval"),
            "price_age_days": (
                (retrieved_date - date.fromisoformat(price_as_of)).days
                if price_as_of is not None
                else None
            ),
            "financial_age_days": (
                (retrieved_date - date.fromisoformat(financial_period_end)).days
                if financial_period_end is not None
                else None
            ),
        },
        "evidence_id": row.security.evidence_id,
        "values": dict(row.values),
        "missing": dict(row.missing),
    }


def _field_document(field: MatrixField) -> dict[str, Any]:
    return {
        "name": field.name,
        "group": field.group,
        "data_type": field.data_type,
        "unit": field.unit,
        "source": field.source,
        "definition": field.definition,
        "formula": field.formula,
        "period": field.period,
        "applicable_to": field.applicable_to,
        "comparison_scope": field.comparison_scope,
        "exclusion_conditions": list(field.exclusion_conditions),
        "definition_version": field.definition_version,
    }


def _projection_documents(
    field_documents: tuple[dict[str, Any], ...],
    missing_reason_documents: list[dict[str, str]],
    row_documents: tuple[dict[str, Any], ...],
    summary: dict[str, Any],
    failures: tuple[dict[str, str], ...],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    tuple[dict[str, Any], ...],
    dict[str, Any],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
]:
    definitions = {
        "schema": "market-snapshot-definitions/v4",
        "fields": list(field_documents),
        "missing_reasons": missing_reason_documents,
    }
    groups = summary["groups"]
    market = {
        "schema": "market-snapshot-market/v1",
        "generated_at": summary["generated_at"],
        "coverage": summary["coverage"],
        "price_coverage_gate_passed": summary["price_requirements_met"],
        "markets": {
            "all": groups["all"],
            "jp": groups["market:jp"],
            "us": groups["market:us"],
        },
    }
    segments = tuple(
        {
            "schema": "market-snapshot-segment/v1",
            "segment_type": key.partition(":")[0],
            "segment_value": key.partition(":")[2],
            **value,
        }
        for key, value in sorted(groups.items())
        if key != "all" and not key.startswith("market:")
    )
    fields_by_name = {value["name"]: value for value in field_documents}

    def coverage(selected: tuple[dict[str, Any], ...]) -> dict[str, Any]:
        counts: dict[str, dict[str, int]] = {}
        for row in selected:
            values = row["values"]
            missing = row["missing"]
            for name in fields_by_name:
                current = counts.setdefault(
                    name, {"applicable": 0, "present": 0, "missing": 0, "not_applicable": 0}
                )
                if missing.get(name) == "not_applicable":
                    current["not_applicable"] += 1
                    continue
                current["applicable"] += 1
                current["present" if name in values else "missing"] += 1
        return {
            name: {
                **current,
                "coverage": (
                    str(Decimal(current["present"]) / Decimal(current["applicable"]))
                    if current["applicable"]
                    else None
                ),
            }
            for name, current in sorted(counts.items())
        }

    field_coverage = coverage(row_documents)
    domains: dict[str, dict[str, int]] = {}
    for name, counts in field_coverage.items():
        domain = domains.setdefault(
            fields_by_name[name]["group"],
            {"applicable": 0, "present": 0, "missing": 0, "not_applicable": 0},
        )
        for key in domain:
            domain[key] += counts[key]

    segment_rows: dict[str, tuple[dict[str, Any], ...]] = {
        "market:jp": tuple(row for row in row_documents if row["instrument"]["mic"] == "XTKS"),
        "market:us": tuple(row for row in row_documents if row["instrument"]["mic"] != "XTKS"),
    }
    for membership in sorted({value for row in row_documents for value in row["memberships"]}):
        segment_rows[f"index:{membership}"] = tuple(
            row for row in row_documents if membership in row["memberships"]
        )
    for classification in ("sector", "industry"):
        values = sorted(
            {
                value
                for row in row_documents
                if (value := row["values"].get(classification)) is not None
            }
        )
        for value in values:
            segment_rows[f"{classification}:{value}"] = tuple(
                row for row in row_documents if row["values"].get(classification) == value
            )

    bounded_ratio_fields = {
        name for name, definition in fields_by_name.items() if definition["unit"] == "bounded_ratio"
    }
    ratio_fields = {
        name
        for name, definition in fields_by_name.items()
        if definition["unit"] in {"ratio", "annualized_ratio"}
    }
    multiple_fields = {
        name for name, definition in fields_by_name.items() if definition["unit"] == "multiple"
    }
    unit_issues: list[dict[str, str]] = []
    outlier_candidates: list[dict[str, str]] = []
    for row in row_documents:
        checked_fields = bounded_ratio_fields | ratio_fields | multiple_fields
        for name in checked_fields & row["values"].keys():
            number = Decimal(row["values"][name])
            if not number.is_finite():
                unit_issues.append(
                    {"instrument_id": row["instrument_id"], "field": name, "code": "non_finite"}
                )
            elif (name in bounded_ratio_fields or name == "dividend_yield") and not Decimal(
                0
            ) <= number <= Decimal(1):
                unit_issues.append(
                    {
                        "instrument_id": row["instrument_id"],
                        "field": name,
                        "code": "ratio_out_of_unit_range",
                    }
                )
            elif name in multiple_fields and abs(number) > Decimal(1000):
                outlier_candidates.append(
                    {
                        "rule_id": "multiple_absolute_value_gt_1000",
                        "instrument_id": row["instrument_id"],
                        "field": name,
                        "value": row["values"][name],
                        "market": "jp" if row["instrument"]["mic"] == "XTKS" else "us",
                        "comparison_population": "same_market",
                        "threshold": "1000",
                        "severity": "warning",
                        "value_origin": "securities.jsonl:values",
                    }
                )
            elif name in ratio_fields and abs(number) > Decimal(10):
                outlier_candidates.append(
                    {
                        "rule_id": "ratio_absolute_value_gt_10",
                        "instrument_id": row["instrument_id"],
                        "field": name,
                        "value": row["values"][name],
                        "market": "jp" if row["instrument"]["mic"] == "XTKS" else "us",
                        "comparison_population": "same_market",
                        "threshold": "10",
                        "severity": "warning",
                        "value_origin": "securities.jsonl:values",
                    }
                )
    failure_instruments = {failure["instrument_id"] for failure in failures}
    completely_failed = failure_instruments & {
        row["instrument_id"] for row in row_documents if "close" not in row["values"]
    }
    failure_groups: dict[str, dict[str, int]] = {key: {} for key in ("stage", "reason", "field")}
    for failure in failures:
        for key, target in failure_groups.items():
            value = failure[key]
            target[value] = target.get(value, 0) + 1

    def freshness(values: list[int]) -> dict[str, int | None]:
        if not values:
            return {"observation_count": 0, "median": None, "p95": None, "maximum": None}
        ordered = sorted(values)
        return {
            "observation_count": len(ordered),
            "median": ordered[(len(ordered) - 1) // 2],
            "p95": ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)],
            "maximum": ordered[-1],
        }

    price_ages = [
        row["temporal"]["price_age_days"]
        for row in row_documents
        if row["temporal"]["price_age_days"] is not None
    ]
    financial_ages = [
        row["temporal"]["financial_age_days"]
        for row in row_documents
        if row["temporal"]["financial_age_days"] is not None
    ]
    quality_summary = {
        "schema": "market-snapshot-quality-summary/v4",
        "price_coverage_gate_passed": summary["price_requirements_met"],
        "price_coverage": summary["coverage"],
        "domains": {
            name: {
                **counts,
                "coverage": (
                    str(Decimal(counts["present"]) / Decimal(counts["applicable"]))
                    if counts["applicable"]
                    else None
                ),
            }
            for name, counts in sorted(domains.items())
        },
        "freshness": {
            "price_age_days": freshness(price_ages),
            "financial_age_days": freshness(financial_ages),
        },
        "failures": {
            "record_count": len(failures),
            "affected_security_count": len(failure_instruments),
            "complete_failure_security_count": len(completely_failed),
            "partial_failure_security_count": len(failure_instruments - completely_failed),
            "by_stage": dict(sorted(failure_groups["stage"].items())),
            "by_reason": dict(sorted(failure_groups["reason"].items())),
            "by_field": dict(sorted(failure_groups["field"].items())),
        },
        "temporal_misalignment_count": 0,
        "unit_issue_count": len(unit_issues),
        "outlier_candidate_count": len(outlier_candidates),
    }
    quality_details = (
        tuple(
            {
                "schema": "market-snapshot-quality-detail/v4",
                "scope": "field",
                "name": name,
                **counts,
            }
            for name, counts in sorted(field_coverage.items())
        )
        + tuple(
            {
                "schema": "market-snapshot-quality-detail/v4",
                "scope": "segment_field",
                "name": name,
                "fields": coverage(rows),
            }
            for name, rows in sorted(segment_rows.items())
        )
        + tuple(
            {
                "schema": "market-snapshot-quality-detail/v4",
                "scope": "unit_issue",
                "name": issue["field"],
                **issue,
            }
            for issue in unit_issues
        )
    )
    quality_outliers = tuple(
        {"schema": "market-snapshot-quality-outlier/v4", **candidate}
        for candidate in outlier_candidates
    )
    return (
        definitions,
        market,
        segments,
        quality_summary,
        quality_details,
        quality_outliers,
    )


class MarketSnapshotStore:
    """Persist one complete content-addressed market snapshot object."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / "objects"
        self.runs = root / "runs"
        self.latest_ref = root / "latest.json"

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if len(run_id) != 16 or any(character not in "0123456789abcdef" for character in run_id):
            raise ValueError("market snapshot run ID must be 16 lowercase hexadecimal characters")

    def run_request(self, run_id: str) -> dict[str, Any]:
        self._validate_run_id(run_id)
        self._require_directory(self.runs)
        run_path = self.runs / run_id
        path = run_path / "request.json"
        if run_path.is_symlink() or path.is_symlink() or not path.is_file():
            raise LookupError(f"market snapshot run does not exist: {run_id}")
        raw = path.read_bytes()
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("market snapshot run request is not valid JSON") from error
        if not isinstance(document, dict) or set(document) != {"fingerprint", "request", "status"}:
            raise ValueError("market snapshot run request has an invalid schema")
        if document["status"] != "started" or not isinstance(document["request"], dict):
            raise ValueError("market snapshot run request has an invalid schema")
        if raw != _json_bytes(document):
            raise ValueError("market snapshot run request is not canonical JSON")
        expected_fingerprint = _request_fingerprint(document["request"])
        if document["fingerprint"] != expected_fingerprint:
            raise ValueError("market snapshot run request fingerprint does not match its content")
        return document["request"]

    def begin_run(
        self,
        fingerprint: str,
        request_document: dict[str, Any],
        *,
        resume: str | None,
    ) -> str:
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ValueError("market snapshot fingerprint must be a lowercase SHA-256 digest")
        expected_fingerprint = _request_fingerprint(request_document)
        if fingerprint != expected_fingerprint:
            raise ValueError("market snapshot fingerprint does not match the request content")
        run_id = resume or fingerprint[:16]
        self._validate_run_id(run_id)
        self._ensure_directory(self.runs)
        path = self.runs / run_id
        if resume is not None:
            stored_request = self.run_request(run_id)
            if stored_request != request_document:
                raise ValueError(
                    "market snapshot resume request does not match the stored run fingerprint"
                )
            return run_id
        if path.exists() or path.is_symlink():
            raise ValueError(
                f"market snapshot run already exists: {run_id}; resume it with --resume {run_id}"
            )
        temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=self.runs))
        try:
            request_path = temporary / "request.json"
            with request_path.open("wb") as stream:
                stream.write(
                    _json_bytes(
                        {
                            "fingerprint": fingerprint,
                            "request": request_document,
                            "status": "started",
                        }
                    )
                )
                stream.flush()
                os.fsync(stream.fileno())
            try:
                temporary.rename(path)
            except FileExistsError:
                raise ValueError(
                    "market snapshot run already exists: "
                    f"{run_id}; resume it with --resume {run_id}"
                ) from None
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return run_id

    def put(
        self,
        *,
        run_id: str,
        manifest_body: dict[str, Any],
        fields: tuple[MatrixField, ...],
        rows: tuple[MatrixRow, ...],
        summary: dict[str, Any],
        failures: tuple[dict[str, str], ...],
        market_indicators: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        stored_request = self.run_request(run_id)
        expected_request_evidence = {
            "fingerprint": _request_fingerprint(stored_request),
            **stored_request,
        }
        if manifest_body.get("request") != expected_request_evidence:
            raise ValueError("market snapshot manifest request does not match the persisted run")
        row_documents = tuple(_row_document(row) for row in rows)
        field_documents = tuple(_field_document(field) for field in fields)
        missing_reason_documents = _missing_reason_documents()
        (
            definitions,
            market,
            segments,
            quality_summary,
            quality_details,
            quality_outliers,
        ) = _projection_documents(
            field_documents, missing_reason_documents, row_documents, summary, failures
        )
        unknown_reasons = {
            reason
            for row in row_documents
            for reason in row["missing"].values()
            if reason not in MISSING_REASONS
        }
        if unknown_reasons:
            raise ValueError(
                f"market snapshot rows contain unknown missing reasons: {sorted(unknown_reasons)}"
            )
        if any(failure.get("reason") == "not_applicable" for failure in failures):
            raise ValueError("not_applicable must not be recorded as a snapshot failure")
        if manifest_body.get("failure_count") != len(failures):
            raise ValueError("snapshot failure count does not match failures.jsonl")
        manifest_body = {
            **manifest_body,
            "artifacts": {
                name: {"path": name, "role": role} for name, role in ARTIFACT_ROLES.items()
            },
        }
        aggregates = (market, *segments)
        semantic = {
            **manifest_body,
            "definitions": definitions,
            "row_hashes": [hashlib.sha256(_json_bytes(row)).hexdigest() for row in row_documents],
            "aggregates": aggregates,
            "quality_summary": quality_summary,
            "quality_details": quality_details,
            "quality_outliers": quality_outliers,
            "failures": failures,
            "market_indicators": market_indicators,
        }
        snapshot_id = hashlib.sha256(_json_bytes(semantic)).hexdigest()
        manifest = {
            "schema": "market-snapshot-manifest/v8",
            "snapshot_id": snapshot_id,
            **manifest_body,
        }
        explorer_data = build_snapshot_explorer_data(manifest, field_documents)
        destination = self.objects / snapshot_id
        self._ensure_directory(self.objects)
        if destination.is_dir():
            self._verify_object(destination, snapshot_id)
        else:
            pending = self.objects / f".{snapshot_id}.{os.getpid()}.pending"
            pending.mkdir(parents=False, exist_ok=False)
            try:
                (pending / "manifest.json").write_bytes(_json_bytes(manifest))
                (pending / "definitions.json").write_bytes(_json_bytes(definitions))
                (pending / "quality-summary.json").write_bytes(_json_bytes(quality_summary))
                self._write_jsonl(pending / "quality-details.jsonl", quality_details)
                self._write_jsonl(pending / "quality-outliers.jsonl", quality_outliers)
                self._write_jsonl(pending / "aggregates.jsonl", aggregates)
                self._write_jsonl(pending / "securities.jsonl", row_documents)
                self._write_jsonl(pending / "failures.jsonl", failures)
                self._write_jsonl(pending / "market-indicators.jsonl", market_indicators)
                (pending / "explorer-data.json").write_bytes(_json_bytes(explorer_data))
                (pending / "explorer.html").write_text(
                    render_explorer(explorer_data), encoding="utf-8"
                )
                (pending / "README.md").write_text(
                    self._readme_markdown(manifest), encoding="utf-8"
                )
                (pending / "summary.md").write_text(
                    self._summary_markdown(manifest, summary), encoding="utf-8"
                )
                pending.rename(destination)
            except BaseException:
                shutil.rmtree(pending, ignore_errors=True)
                raise
        self._ensure_directory(self.root)
        temporary = self.root / f".latest.{os.getpid()}.tmp"
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("snapshot latest-reference temporary path already exists")
        run_path = self.runs / run_id
        if run_path.is_symlink() or not run_path.is_dir():
            raise ValueError("market snapshot run path must be a real directory")
        document = self.show(snapshot_id)
        try:
            temporary.write_bytes(
                _json_bytes(
                    {
                        "snapshot_id": snapshot_id,
                        "path": f"objects/{snapshot_id}",
                        "created_at": manifest["created_at"],
                        "price_as_of": {
                            market_name: market["markets"][market_name]["latest_price_date"]
                            for market_name in ("jp", "us")
                        },
                        "price_coverage_gate_passed": manifest["price_coverage_gate_passed"],
                    }
                )
            )
            temporary.replace(self.latest_ref)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        with suppress(OSError):
            shutil.rmtree(run_path, ignore_errors=True)
        return document

    @staticmethod
    def _write_jsonl(path: Path, documents: Iterable[object]) -> None:
        with path.open("wb") as stream:
            for document in documents:
                stream.write(_json_bytes(document))

    @staticmethod
    def _readme_markdown(manifest: dict[str, Any]) -> str:
        benchmarks = ", ".join(
            f"{name}={value['benchmark_symbol']} ({value.get('benchmark_kind', 'index')})"
            for name, value in sorted(manifest["universe_assets"].items())
        )
        lines = [
            "# MarketSieve Market Snapshot",
            "",
            "This directory is one immutable, self-contained broad-market snapshot.",
            "",
            f"- Snapshot ID: `{manifest['snapshot_id']}`",
            f"- Retrieved at: `{manifest['created_at']}`",
            f"- Securities: {manifest['row_count']}",
            f"- Fields: {manifest['field_count']}",
            "- Price coverage gate passed: "
            f"`{str(manifest['price_coverage_gate_passed']).lower()}`",
            f"- Benchmarks: {benchmarks}",
            "",
            "`securities.jsonl` is authoritative. One row represents one security. Every "
            "defined field appears either in `values` or in `missing`.",
            "",
            "`definitions.json` defines fields and missing-value codes. "
            "`quality-summary.json` separates "
            "coverage by evidence domain. `aggregates.jsonl` contains aggregate statistics. "
            "`failures.jsonl` contains observed failures. HTML and Markdown files are "
            "deterministic views.",
            "",
            "Index memberships can overlap, so membership counts must not be summed as unique "
            "security counts. Currency-denominated values must not be aggregated across currencies "
            "without an explicit conversion outside this dataset.",
        ]
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _summary_markdown(manifest: dict[str, Any], summary: dict[str, Any]) -> str:
        lines = [
            "# MarketSieve Market Summary",
            "",
            f"- Snapshot ID: `{manifest['snapshot_id']}`",
            f"- Retrieved at: `{manifest['created_at']}`",
            f"- Securities: {manifest['row_count']}",
            f"- Fields: {manifest['field_count']}",
            f"- Overall price coverage: {summary['coverage']['overall']}",
            f"- Price requirements met: `{str(summary['price_requirements_met']).lower()}`",
            "",
            "| Group | Securities | Price coverage | Advancing | Declining | "
            "Above SMA20 | Above SMA200 | Return 20d median | Volatility 60d median | "
            "PER median | ROE median |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        displayed_groups = {
            name: group
            for name, group in summary["groups"].items()
            if name == "all" or name.startswith(("market:", "index:"))
        }

        def median(group: dict[str, Any], field: str) -> Any:
            return group.get("distributions", {}).get(field, {}).get("median")

        for name, group in sorted(displayed_groups.items()):
            lines.append(
                f"| {name} | {group['security_count']} | {group['price_coverage']} | "
                f"{group['advancing_count']} | {group['declining_count']} | "
                f"{group['above_sma_20_count']} | {group['above_sma_200_count']} | "
                f"{median(group, 'return_20d')} | "
                f"{median(group, 'volatility_60d')} | "
                f"{median(group, 'trailing_pe')} | "
                f"{median(group, 'return_on_equity')} |"
            )
        lines.extend(
            (
                "",
                "## Missing values",
                "",
                "| Group | Reason | Cells |",
                "| --- | --- | ---: |",
            )
        )
        for name, group in sorted(displayed_groups.items()):
            for reason, count in sorted(group["missing"]["reasons"].items()):
                lines.append(f"| {name} | {reason} | {count} |")
        return "\n".join(lines).rstrip() + "\n"

    def resolve_id(self, snapshot_id: str) -> str:
        if snapshot_id != "latest":
            return snapshot_id
        self._require_directory(self.root)
        if self.latest_ref.is_symlink() or not self.latest_ref.is_file():
            raise LookupError("no market snapshot is available")
        raw = self.latest_ref.read_bytes()
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("market snapshot latest reference is invalid") from error
        if (
            not isinstance(value, dict)
            or set(value)
            != {"snapshot_id", "path", "created_at", "price_as_of", "price_coverage_gate_passed"}
            or raw != _json_bytes(value)
            or not isinstance(value["snapshot_id"], str)
            or len(value["snapshot_id"]) != 64
            or any(character not in "0123456789abcdef" for character in value["snapshot_id"])
        ):
            raise ValueError("market snapshot latest reference is invalid")
        return value["snapshot_id"]

    def show(self, snapshot_id: str) -> dict[str, Any]:
        resolved = self.resolve_id(snapshot_id)
        self._require_directory(self.objects)
        path = self.objects / resolved
        self._verify_object(path, resolved)
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        aggregates = tuple(self._read_jsonl(path / "aggregates.jsonl"))
        market = aggregates[0]
        return {
            **manifest,
            "schema": "market-snapshot/v8",
            "market": market,
            "artifacts": {
                name: str(path / name)
                for name in (
                    "README.md",
                    "manifest.json",
                    "definitions.json",
                    "quality-summary.json",
                    "quality-details.jsonl",
                    "quality-outliers.jsonl",
                    "aggregates.jsonl",
                    "securities.jsonl",
                    "failures.jsonl",
                    "market-indicators.jsonl",
                    "explorer-data.json",
                    "explorer.html",
                    "summary.md",
                )
            },
        }

    def list(self) -> dict[str, Any]:
        inventory = ArtifactInventory(
            self.root.parent,
            validators={"snapshot": self._verify_object},
        )
        if not self.objects.exists():
            return {
                "schema": "market-snapshot-list/v3",
                "snapshots": [],
                "inventory_counts": inventory.list(object_type="snapshot")["counts"],
            }
        self._require_directory(self.objects)
        snapshots = []
        for path in self.objects.iterdir():
            if path.name.startswith(".") or path.name == ".DS_Store":
                continue
            manifest_path = path / "manifest.json"
            try:
                valid_manifest_path = (
                    not path.is_symlink()
                    and path.is_dir()
                    and not manifest_path.is_symlink()
                    and manifest_path.is_file()
                )
                if not valid_manifest_path:
                    continue
                candidate = self._read_json(manifest_path)
            except (LookupError, OSError, TypeError, ValueError):
                continue
            if (
                not isinstance(candidate, dict)
                or candidate.get("schema") != "market-snapshot-manifest/v8"
            ):
                continue
            try:
                self._verify_object(path, path.name)
            except (LookupError, OSError, TypeError, ValueError):
                continue
            manifest = candidate
            snapshots.append(
                {
                    "snapshot_id": path.name,
                    "created_at": manifest["created_at"],
                    "row_count": manifest["row_count"],
                    "field_count": manifest["field_count"],
                    "coverage": manifest["coverage"],
                    "price_coverage_gate_passed": manifest["price_coverage_gate_passed"],
                }
            )
        try:
            ordered = sorted(
                snapshots,
                key=lambda value: (
                    datetime.fromisoformat(value["created_at"]),
                    value["snapshot_id"],
                ),
                reverse=True,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("market snapshot creation time is invalid") from error
        if any(
            datetime.fromisoformat(value["created_at"]).utcoffset() is None for value in ordered
        ):
            raise ValueError("market snapshot creation time must include a UTC offset")
        return {
            "schema": "market-snapshot-list/v3",
            "snapshots": ordered,
            "inventory_counts": inventory.list(object_type="snapshot")["counts"],
        }

    def find_by_request_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        if not self.objects.exists():
            return None
        self._require_directory(self.objects)
        for path in sorted(self.objects.iterdir(), key=lambda value: value.name):
            if path.name.startswith(".") or not path.is_dir() or path.is_symlink():
                continue
            manifest_path = path / "manifest.json"
            if not manifest_path.is_file() or manifest_path.is_symlink():
                continue
            manifest = self._read_json(manifest_path)
            if manifest.get("schema") != "market-snapshot-manifest/v8":
                continue
            if manifest.get("request_fingerprint") == fingerprint:
                return self.show(path.name)
        return None

    def query(
        self,
        snapshot_id: str,
        *,
        filters: dict[str, tuple[str, ...]],
        minimums: dict[str, Decimal],
        maximums: dict[str, Decimal],
        present: tuple[str, ...],
        missing: tuple[str, ...],
        fields: tuple[str, ...],
        order: tuple[str, ...] = (),
        limit: int | None = None,
        domains: tuple[str, ...] = (),
        profile: str | None = None,
        budget: Decimal | None = None,
        budget_currency: str | None = None,
        trading_unit: int | None = None,
        use_snapshot_fx: bool = False,
    ) -> dict[str, Any]:
        self._require_directory(self.objects)
        resolved = self.resolve_id(snapshot_id)
        self._verify_object(self.objects / resolved, resolved)
        allowed_filters = {
            "market",
            "index",
            "mic",
            "exchange",
            "country",
            "currency",
            "sector",
            "industry",
        }
        if unknown_filters := set(filters) - allowed_filters:
            raise ValueError(
                f"unknown market snapshot classification filters: {sorted(unknown_filters)}"
            )
        if any(not values for values in filters.values()):
            raise ValueError("market snapshot classification filters cannot be empty")
        if any(len(values) != len(set(values)) for values in filters.values()):
            raise ValueError("market snapshot classification filter values must be unique")
        if invalid_indices := set(filters.get("index", ())) - set(INDEX_BENCHMARKS):
            raise ValueError(f"unknown market snapshot indices: {sorted(invalid_indices)}")
        if any(len(values) != len(set(values)) for values in (present, missing, fields, domains)):
            raise ValueError("market snapshot query field selections must be unique")
        definitions_document = self._read_json(self.objects / resolved / "definitions.json")
        definitions = definitions_document["fields"]
        field_types = {value["name"]: value["data_type"] for value in definitions}
        known = set(field_types)
        order_fields: list[tuple[str, str]] = []
        for item in order:
            name, separator, direction = item.partition(":")
            if not separator or direction not in {"asc", "desc"}:
                raise ValueError("market snapshot order requires FIELD:asc or FIELD:desc")
            order_fields.append((name, direction))
        if len({name for name, _ in order_fields}) != len(order_fields):
            raise ValueError("market snapshot order fields must be unique")
        requested = (
            set(fields)
            | set(minimums)
            | set(maximums)
            | set(present)
            | set(missing)
            | {name for name, _ in order_fields}
        )
        if unknown := requested - known:
            raise ValueError(f"unknown market snapshot fields: {sorted(unknown)}")
        numeric = {name for name, kind in field_types.items() if kind in {"decimal", "integer"}}
        if invalid := (set(minimums) | set(maximums)) - numeric:
            raise ValueError(
                f"market snapshot numeric filters require numeric fields: {sorted(invalid)}"
            )
        if set(present) & set(missing):
            raise ValueError("market snapshot fields cannot be both present and missing")
        if invalid_bounds := {
            name for name in set(minimums) & set(maximums) if minimums[name] > maximums[name]
        }:
            raise ValueError(f"market snapshot minimum exceeds maximum: {sorted(invalid_bounds)}")
        known_domains = {value["group"] for value in definitions} | {"quality"}
        if invalid_domains := set(domains) - known_domains:
            raise ValueError(f"unknown market snapshot domains: {sorted(invalid_domains)}")
        profile_windows = {
            "short-swing": {1, 5, 20, 60},
            "swing": {5, 20, 60, 120},
            "position": {20, 60, 120, 252},
        }
        if profile is not None and profile not in profile_windows:
            raise ValueError(f"unknown market snapshot profile: {profile}")
        selected_by_domain = {value["name"] for value in definitions if value["group"] in domains}
        if "quality" in domains:
            selected_by_domain.update({"price_as_of"})
        selected_source = set(fields) if fields else selected_by_domain or known
        if profile is not None and not fields:
            windows = profile_windows[profile]
            selected_source = {
                name
                for name in selected_source
                if not (match := re.search(r"_(\d+)(?:d)?(?:$|_)", name))
                or int(match.group(1)) in windows
            }
            selected_source.update(
                {"name", "exchange", "country", "currency", "sector", "industry", "close"} & known
            )
        selected = tuple(sorted(selected_source))

        def matches(row: dict[str, Any]) -> bool:
            values = row["values"]
            classification = {
                "market": "jp" if row["instrument"]["mic"] == "XTKS" else "us",
                "index": tuple(row["memberships"]),
                "mic": row["instrument"]["mic"],
                "exchange": values.get("exchange"),
                "country": values.get("country"),
                "currency": values.get("currency", row["instrument"]["currency"]),
                "sector": values.get("sector"),
                "industry": values.get("industry"),
            }
            for name, accepted in filters.items():
                actual = classification[name]
                if name == "index":
                    if not set(accepted) & set(actual):
                        return False
                elif actual not in accepted:
                    return False
            for name, threshold in minimums.items():
                if name not in values or Decimal(values[name]) < threshold:
                    return False
            for name, threshold in maximums.items():
                if name not in values or Decimal(values[name]) > threshold:
                    return False
            return all(name in values for name in present) and all(
                name in row["missing"] for name in missing
            )

        def classification_matches(
            row: dict[str, Any], name: str, accepted: tuple[str, ...]
        ) -> bool:
            values = row["values"]
            actual: Any = {
                "market": "jp" if row["instrument"]["mic"] == "XTKS" else "us",
                "index": tuple(row["memberships"]),
                "mic": row["instrument"]["mic"],
                "exchange": values.get("exchange"),
                "country": values.get("country"),
                "currency": values.get("currency", row["instrument"]["currency"]),
                "sector": values.get("sector"),
                "industry": values.get("industry"),
            }[name]
            return bool(set(accepted) & set(actual)) if name == "index" else actual in accepted

        source_rows = list(self._rows(resolved))
        candidates = source_rows
        funnel: list[dict[str, Any]] = [
            {"condition": "input", "passed_count": len(candidates), "excluded_count": 0}
        ]
        conditions: list[tuple[str, Any]] = []
        for name, accepted in sorted(filters.items()):
            conditions.append(
                (
                    f"{name}={','.join(accepted)}",
                    lambda row, name=name, accepted=accepted: classification_matches(
                        row, name, accepted
                    ),
                )
            )
        for name, threshold in sorted(minimums.items()):
            conditions.append(
                (
                    f"min:{name}={threshold}",
                    lambda row, name=name, threshold=threshold: (
                        name in row["values"] and Decimal(row["values"][name]) >= threshold
                    ),
                )
            )
        for name, threshold in sorted(maximums.items()):
            conditions.append(
                (
                    f"max:{name}={threshold}",
                    lambda row, name=name, threshold=threshold: (
                        name in row["values"] and Decimal(row["values"][name]) <= threshold
                    ),
                )
            )
        conditions.extend(
            (f"present:{name}", lambda row, name=name: name in row["values"])
            for name in sorted(present)
        )
        conditions.extend(
            (f"missing:{name}", lambda row, name=name: name in row["missing"])
            for name in sorted(missing)
        )
        exclusion_reasons: dict[str, int] = {}
        for label, predicate in conditions:
            before = len(candidates)
            candidates = [row for row in candidates if predicate(row)]
            excluded = before - len(candidates)
            funnel.append(
                {"condition": label, "passed_count": len(candidates), "excluded_count": excluded}
            )
            if excluded:
                exclusion_reasons[label] = excluded

        fx = None
        if use_snapshot_fx:
            indicators = tuple(
                self._read_jsonl(self.objects / resolved / "market-indicators.jsonl")
            )
            usd_jpy = next(
                (item for item in indicators if item.get("indicator_id") == "usd_jpy"), None
            )
            if usd_jpy is None or not usd_jpy.get("observations"):
                raise ValueError("Snapshot USD/JPY evidence is unavailable")
            latest_fx = usd_jpy["observations"][-1]
            fx = {
                "value": latest_fx["value"],
                "as_of": latest_fx["date"],
                "retrieved_at": usd_jpy["retrieved_at"],
                "source": "yfinance",
                "unit": "JPY_per_USD",
            }

        rows: list[dict[str, Any]] = []
        for row in candidates:
            values_document = {
                name: row["values"][name] for name in selected if name in row["values"]
            }
            purchase_projection = None
            if budget is not None and budget_currency is not None:
                currency = row["values"].get("currency", row["instrument"]["currency"])
                close = row["values"].get("close")
                unit = trading_unit or 1
                native_purchase = Decimal(close) * unit if close is not None else None
                minimum_purchase = native_purchase
                if native_purchase is not None and currency != budget_currency and fx is not None:
                    rate = Decimal(fx["value"])
                    if currency == "USD" and budget_currency == "JPY":
                        minimum_purchase = native_purchase * rate
                    elif currency == "JPY" and budget_currency == "USD":
                        minimum_purchase = native_purchase / rate
                    else:
                        minimum_purchase = None
                purchase_projection = {
                    "budget": str(budget),
                    "budget_currency": budget_currency,
                    "security_currency": currency,
                    "trading_unit": unit,
                    "minimum_purchase_amount": (
                        str(minimum_purchase) if minimum_purchase is not None else None
                    ),
                    "affordable": (
                        minimum_purchase <= budget if minimum_purchase is not None else None
                    ),
                    "reason": (None if minimum_purchase is not None else "currency_mismatch"),
                    "fx": fx if currency != budget_currency else None,
                }
            rows.append(
                {
                    "instrument_id": row["instrument_id"],
                    "instrument": row["instrument"],
                    "provider_symbol": row["provider_symbol"],
                    "memberships": row["memberships"],
                    "retrieved_at": row["retrieved_at"],
                    "values": values_document,
                    "_order_values": {name: row["values"].get(name) for name, _ in order_fields},
                    "missing": {
                        name: row["missing"][name] for name in selected if name in row["missing"]
                    },
                    **(
                        {"purchase_projection": purchase_projection}
                        if purchase_projection is not None
                        else {}
                    ),
                }
            )

        def compare(left: dict[str, Any], right: dict[str, Any]) -> int:
            for name, direction in order_fields:
                left_value = left["_order_values"].get(name)
                right_value = right["_order_values"].get(name)
                if left_value is None or right_value is None:
                    if left_value is right_value:
                        continue
                    return 1 if left_value is None else -1
                if name in numeric:
                    left_value, right_value = Decimal(left_value), Decimal(right_value)
                if left_value == right_value:
                    continue
                result = -1 if left_value < right_value else 1
                return result if direction == "asc" else -result
            left_id, right_id = str(left["instrument_id"]), str(right["instrument_id"])
            return (left_id > right_id) - (left_id < right_id)

        rows.sort(key=cmp_to_key(compare))
        total_count = len(rows)
        if limit is not None:
            if limit <= 0:
                raise ValueError("market snapshot query limit must be positive")
            rows = rows[:limit]
        for row in rows:
            del row["_order_values"]
        return {
            "schema": "market-snapshot-query-result/v3",
            "snapshot_id": resolved,
            "input_count": len(source_rows),
            "matched_count": len(rows),
            "total_matched_count": total_count,
            "fields": list(selected),
            "profile": profile,
            "domains": list(domains),
            "order": list(order),
            "limit": limit,
            "filters": {
                "classifications": {name: list(values) for name, values in sorted(filters.items())},
                "minimums": {name: str(value) for name, value in sorted(minimums.items())},
                "maximums": {name: str(value) for name, value in sorted(maximums.items())},
                "present": list(sorted(present)),
                "missing": list(sorted(missing)),
            },
            "filter_funnel": funnel,
            "exclusion_reasons": exclusion_reasons,
            "field_definitions_schema": definitions_document["schema"],
            "rows": rows,
        }

    def row(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        resolved = self.resolve_id(snapshot_id)
        self._require_directory(self.objects)
        self._verify_object(self.objects / resolved, resolved)
        for document in self._rows(resolved):
            if document["instrument_id"] == instrument_id:
                return {
                    **document,
                    "schema": "market-snapshot-security-result/v1",
                    "snapshot_id": resolved,
                }
        raise LookupError(f"instrument is not present in Market Snapshot: {instrument_id}")

    def compare(
        self, snapshot_id: str, instrument_ids: tuple[str, ...], fields: tuple[str, ...]
    ) -> dict[str, Any]:
        resolved = self.resolve_id(snapshot_id)
        self._require_directory(self.objects)
        self._verify_object(self.objects / resolved, resolved)
        field_documents = json.loads(
            (self.objects / resolved / "definitions.json").read_text(encoding="utf-8")
        )["fields"]
        available_fields = {value["name"] for value in field_documents}
        if len(fields) != len(set(fields)):
            raise ValueError("market snapshot compare fields must be unique")
        selected = tuple(sorted(fields or tuple(available_fields)))
        if unknown := set(selected) - available_fields:
            raise ValueError(f"unknown market snapshot fields: {sorted(unknown)}")
        rows = {value["instrument_id"]: value for value in self._rows(resolved)}
        missing_ids = [value for value in instrument_ids if value not in rows]
        if missing_ids:
            raise LookupError(f"instruments are not present in Market Snapshot: {missing_ids}")
        comparison_scopes = {value["name"]: value["comparison_scope"] for value in field_documents}
        if any(comparison_scopes[name] == "same_market_and_currency" for name in selected):
            markets = {
                "jp" if rows[instrument_id]["instrument"]["mic"] == "XTKS" else "us"
                for instrument_id in instrument_ids
            }
            currencies = {
                rows[instrument_id]["values"].get(
                    "currency", rows[instrument_id]["instrument"]["currency"]
                )
                for instrument_id in instrument_ids
            }
            if len(markets) != 1 or len(currencies) != 1:
                raise ValueError(
                    "market snapshot comparison requires one market and currency "
                    "for selected fields"
                )
        return {
            "schema": "market-snapshot-comparison/v3",
            "snapshot_id": resolved,
            "fields": list(selected),
            "rows": [
                {
                    "instrument_id": instrument_id,
                    "values": {
                        name: rows[instrument_id]["values"][name]
                        for name in selected
                        if name in rows[instrument_id]["values"]
                    },
                    "missing": {
                        name: rows[instrument_id]["missing"].get(name)
                        for name in selected
                        if name in rows[instrument_id]["missing"]
                    },
                }
                for instrument_id in instrument_ids
            ],
        }

    def research_context(self, snapshot_id: str, instrument_id: str) -> dict[str, Any]:
        resolved = self.resolve_id(snapshot_id)
        path = self.objects / resolved
        self._verify_object(path, resolved)
        security = self.row(resolved, instrument_id)
        aggregates = tuple(self._read_jsonl(path / "aggregates.jsonl"))
        market = aggregates[0]
        values = security["values"]
        market_name = "jp" if security["instrument"]["mic"] == "XTKS" else "us"
        market = {
            **market,
            "markets": {market_name: market["markets"][market_name]},
        }
        selected = []
        for segment in aggregates[1:]:
            segment_type = segment["segment_type"]
            segment_value = segment["segment_value"]
            if (
                (segment_type == "index" and segment_value in security["memberships"])
                or (segment_type == "sector" and segment_value == values.get("sector"))
                or (segment_type == "industry" and segment_value == values.get("industry"))
                or (
                    segment_type == "market-sector"
                    and segment_value == f"{market_name}|{values.get('sector')}"
                )
            ):
                selected.append(segment)
        return {
            "schema": "market-research-context/v1",
            "snapshot_id": resolved,
            "security": security,
            "market": market,
            "segments": selected,
            "definitions": self._read_json(path / "definitions.json"),
        }

    def diff(
        self, left_snapshot_id: str, right_snapshot_id: str, fields: tuple[str, ...]
    ) -> dict[str, Any]:
        left_id = self.resolve_id(left_snapshot_id)
        right_id = self.resolve_id(right_snapshot_id)
        left_path = self.objects / left_id
        right_path = self.objects / right_id
        self._verify_object(left_path, left_id)
        self._verify_object(right_path, right_id)
        left_definitions = {
            item["name"]: item for item in self._read_json(left_path / "definitions.json")["fields"]
        }
        right_definitions = {
            item["name"]: item
            for item in self._read_json(right_path / "definitions.json")["fields"]
        }
        shared_fields = set(left_definitions) & set(right_definitions)
        if fields:
            unknown = set(fields) - shared_fields
            if unknown:
                raise ValueError(f"diff fields are not shared by both snapshots: {sorted(unknown)}")
            shared_fields &= set(fields)
        incompatible = sorted(
            name
            for name in shared_fields
            if any(
                left_definitions[name][key] != right_definitions[name][key]
                for key in ("data_type", "unit", "definition_version")
            )
        )
        comparable = tuple(sorted(shared_fields - set(incompatible)))
        left_rows = {row["instrument_id"]: row for row in self._rows(left_id)}
        right_rows = {row["instrument_id"]: row for row in self._rows(right_id)}
        changes = []
        for instrument_id in sorted(set(left_rows) & set(right_rows)):
            changed = {}
            for name in comparable:
                left_value = left_rows[instrument_id]["values"].get(name)
                right_value = right_rows[instrument_id]["values"].get(name)
                left_missing = left_rows[instrument_id]["missing"].get(name)
                right_missing = right_rows[instrument_id]["missing"].get(name)
                if (left_value, left_missing) != (right_value, right_missing):
                    changed[name] = {
                        "left": left_value,
                        "right": right_value,
                        "left_missing": left_missing,
                        "right_missing": right_missing,
                    }
            if changed:
                changes.append({"instrument_id": instrument_id, "fields": changed})
        return {
            "schema": "market-snapshot-diff/v1",
            "left_snapshot_id": left_id,
            "right_snapshot_id": right_id,
            "added_instruments": sorted(set(right_rows) - set(left_rows)),
            "removed_instruments": sorted(set(left_rows) - set(right_rows)),
            "comparable_fields": list(comparable),
            "incompatible_fields": incompatible,
            "changed_securities": changes,
        }

    def _rows(self, snapshot_id: str) -> Iterable[dict[str, Any]]:
        path = self.objects / snapshot_id / "securities.jsonl"
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)

    @staticmethod
    def _verify_object(path: Path, snapshot_id: str) -> None:
        if path.is_symlink() or not path.is_dir() or path.name != snapshot_id:
            raise LookupError(f"market snapshot does not exist: {snapshot_id}")
        required = {
            "README.md",
            "manifest.json",
            "definitions.json",
            "quality-summary.json",
            "quality-details.jsonl",
            "quality-outliers.jsonl",
            "aggregates.jsonl",
            "securities.jsonl",
            "failures.jsonl",
            "market-indicators.jsonl",
            "explorer-data.json",
            "explorer.html",
            "summary.md",
        }
        artifacts = {value.name: value for value in path.iterdir()}
        if set(artifacts) != required or any(
            artifacts[name].is_symlink() or not artifacts[name].is_file() for name in required
        ):
            raise ValueError("market snapshot object inventory is invalid")
        manifest = MarketSnapshotStore._read_json(path / "manifest.json")
        if (
            manifest.get("snapshot_id") != snapshot_id
            or manifest.get("schema") != "market-snapshot-manifest/v8"
        ):
            raise ValueError("market snapshot manifest identity is invalid")
        definitions = MarketSnapshotStore._read_json(path / "definitions.json")
        fields = definitions["fields"]
        aggregates = tuple(MarketSnapshotStore._read_jsonl(path / "aggregates.jsonl"))
        if not aggregates:
            raise ValueError("market snapshot aggregates are empty")
        market = aggregates[0]
        segments = aggregates[1:]
        quality_summary = MarketSnapshotStore._read_json(path / "quality-summary.json")
        quality_details = tuple(MarketSnapshotStore._read_jsonl(path / "quality-details.jsonl"))
        quality_outliers = tuple(MarketSnapshotStore._read_jsonl(path / "quality-outliers.jsonl"))
        rows = tuple(MarketSnapshotStore._read_jsonl(path / "securities.jsonl"))
        failures = tuple(MarketSnapshotStore._read_jsonl(path / "failures.jsonl"))
        market_indicators = tuple(MarketSnapshotStore._read_jsonl(path / "market-indicators.jsonl"))
        summary = {
            "schema": "market-snapshot-summary/v1",
            "generated_at": market["generated_at"],
            "coverage": market["coverage"],
            "price_requirements_met": market["price_coverage_gate_passed"],
            "groups": {
                "all": market["markets"]["all"],
                "market:jp": market["markets"]["jp"],
                "market:us": market["markets"]["us"],
                **{
                    f"{value['segment_type']}:{value['segment_value']}": {
                        key: item
                        for key, item in value.items()
                        if key not in {"schema", "segment_type", "segment_value"}
                    }
                    for value in segments
                },
            },
        }
        semantic = {
            **{
                key: value
                for key, value in manifest.items()
                if key not in {"schema", "snapshot_id"}
            },
            "definitions": definitions,
            "row_hashes": [hashlib.sha256(_json_bytes(row)).hexdigest() for row in rows],
            "aggregates": aggregates,
            "quality_summary": quality_summary,
            "quality_details": quality_details,
            "quality_outliers": quality_outliers,
            "failures": failures,
            "market_indicators": market_indicators,
        }
        if hashlib.sha256(_json_bytes(semantic)).hexdigest() != snapshot_id:
            raise ValueError("market snapshot content identity is invalid")
        if (path / "README.md").read_text(encoding="utf-8") != MarketSnapshotStore._readme_markdown(
            manifest
        ):
            raise ValueError("market snapshot README projection is invalid")
        if (path / "summary.md").read_text(
            encoding="utf-8"
        ) != MarketSnapshotStore._summary_markdown(
            manifest,
            summary,
        ):
            raise ValueError("market snapshot summary projection is invalid")
        explorer_data = MarketSnapshotStore._read_json(path / "explorer-data.json")
        expected_explorer_data = build_snapshot_explorer_data(manifest, fields)
        if explorer_data != expected_explorer_data:
            raise ValueError("market snapshot Explorer data projection is invalid")
        if (path / "explorer.html").read_text(encoding="utf-8") != render_explorer(explorer_data):
            raise ValueError("market snapshot HTML projection is invalid")

    @staticmethod
    def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
        for line in path.read_bytes().splitlines(keepends=True):
            try:
                document = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"market snapshot JSONL is invalid: {path.name}") from error
            if not isinstance(document, dict) or line != _json_bytes(document):
                raise ValueError(f"market snapshot JSONL is not canonical: {path.name}")
            yield document

    @staticmethod
    def _read_json(path: Path) -> Any:
        raw = path.read_bytes()
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"market snapshot JSON is invalid: {path.name}") from error
        if raw != _json_bytes(document):
            raise ValueError(f"market snapshot JSON is not canonical: {path.name}")
        return document

    def _ensure_directory(self, path: Path) -> None:
        current = self.root
        directories = [self.root.parent, self.root]
        for part in path.relative_to(self.root).parts:
            current /= part
            directories.append(current)
        if any(candidate.is_symlink() for candidate in directories):
            raise ValueError("market snapshot storage path must be a real directory")
        path.mkdir(parents=True, exist_ok=True)
        if any(not candidate.is_dir() for candidate in directories):
            raise ValueError("market snapshot storage path must be a real directory")

    def _require_directory(self, path: Path) -> None:
        current = self.root
        directories = [self.root.parent, self.root]
        for part in path.relative_to(self.root).parts:
            current /= part
            directories.append(current)
        if any(candidate.is_symlink() or not candidate.is_dir() for candidate in directories):
            raise LookupError("market snapshot storage directory does not exist")
