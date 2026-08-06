"""Deterministic, privacy-bounded workspace for external analysis tools."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from marketsieve import DecisionReport, MarketSession, ScreeningReport
from marketsieve_cli.adapters.reports import _decision_document, _parse_decision
from marketsieve_cli.adapters.screening import screening_document
from marketsieve_cli.adapters.watchlists import instrument_key

ANALYSIS_SCHEMA = "analysis-context/v1"
README_TEXT = """# MarketSieve Analysis Workspace

This directory is a deterministic projection of verified MarketSieve artifacts.

- Read `context.json` for machine-readable evidence, provenance, history, and diagnostics.
- Read `analysis.md` for the corresponding static human-readable view.
- Treat `buy_candidate` and other actions as research states, not trade instructions.
- Research news and external claims independently and cite their sources in the discussion.
- Do not write research, conversations, credentials, or orders back into this directory.
"""


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def _instrument_document(instrument: Any) -> dict[str, str]:
    return {
        "key": instrument_key(instrument),
        "mic": instrument.mic,
        "symbol": instrument.symbol,
        "currency": instrument.currency,
        "timezone": instrument.exchange_timezone.key,
        "type": instrument.instrument_type.value,
    }


class AnalysisWorkspace:
    """Build one stable workspace from immutable portfolio, watchlist, and report stores."""

    def __init__(
        self,
        root: Path,
        portfolios: Any,
        watchlists: Any,
        reports: Any,
        screening: Any,
    ) -> None:
        self._root = root
        self._portfolios = portfolios
        self._watchlists = watchlists
        self._reports = reports
        self._screening = screening

    def build(self) -> dict[str, Any]:
        portfolio_id, imported = self._portfolios.latest()
        watch_history = self._watchlists.history()
        decision_reports = self._latest_decision_reports()
        screening_reports = self._latest_screening_reports()
        timestamps = [imported.snapshot.as_of]
        timestamps.extend(report.as_of for report in decision_reports)
        timestamps.extend(report.as_of for report in screening_reports)
        timestamps.extend(
            datetime.fromisoformat(item["as_of"]) for item in watch_history if item["as_of"]
        )
        missing = [
            f"decision_report:{session.value}"
            for session in (MarketSession.JP_CLOSE, MarketSession.US_CLOSE, MarketSession.WEEKLY)
            if not any(report.session is session for report in decision_reports)
        ]
        missing.extend(
            f"screening_report:{market}"
            for market in ("jp", "us")
            if not any(self._screen_market(report) == market for report in screening_reports)
        )
        semantic: dict[str, Any] = {
            "schema": ANALYSIS_SCHEMA,
            "as_of": max(value.astimezone(UTC) for value in timestamps).isoformat(),
            "portfolio": {
                "object_id": portfolio_id,
                "as_of": imported.snapshot.as_of.isoformat(),
                "source": imported.snapshot.source,
                "source_name": imported.source_name,
                "dataset": imported.dataset,
                "diagnostics": [],
                "holdings": [
                    _instrument_document(item.instrument) for item in imported.snapshot.holdings
                ],
            },
            "watchlist": {
                "latest_id": watch_history[-1]["watchlist_id"] if watch_history else None,
                "items": watch_history[-1]["items"] if watch_history else [],
                "history": list(watch_history),
            },
            "decision_reports": [self._decision_context(item) for item in decision_reports],
            "screening_reports": [screening_document(item) for item in screening_reports],
            "previous_deltas": [
                self._previous_delta(item)
                for item in decision_reports
                if item.previous_report_id is not None
            ],
            "input_artifact_ids": self._input_artifact_ids(
                portfolio_id,
                watch_history,
                decision_reports,
                screening_reports,
            ),
            "missing": sorted(missing),
            "diagnostics": sorted(
                {
                    *(value for item in decision_reports for value in item.diagnostics),
                    *(value for item in screening_reports for value in item.diagnostics),
                    *(
                        (f"portfolio_import_diagnostics_omitted:{len(imported.diagnostics)}",)
                        if imported.diagnostics
                        else ()
                    ),
                }
            ),
            "constraints": [
                "static_evidence_only",
                "external_research_not_persisted",
                "no_order_generation",
                "candidate_actions_are_not_trade_instructions",
            ],
        }
        context_id = hashlib.sha256(_json_bytes(semantic)).hexdigest()
        document = {"context_id": context_id, **semantic}
        markdown = render_analysis(document)
        self._ensure_root()
        self._atomic_write(self._root / "README.md", README_TEXT.encode("utf-8"))
        self._atomic_write(self._root / "context.json", _json_bytes(document))
        self._atomic_write(self._root / "analysis.md", markdown.encode("utf-8"))
        return document

    def show(self) -> tuple[dict[str, Any], str]:
        context_path = self._root / "context.json"
        analysis_path = self._root / "analysis.md"
        readme_path = self._root / "README.md"
        if any(
            path.is_symlink() or not path.is_file()
            for path in (context_path, analysis_path, readme_path)
        ):
            raise LookupError("analysis workspace does not exist; run 'marketsieve analysis build'")
        try:
            document = json.loads(context_path.read_bytes())
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("analysis context is invalid") from error
        if not isinstance(document, dict) or document.get("schema") != ANALYSIS_SCHEMA:
            raise ValueError("analysis context schema is unsupported")
        _validate_analysis_document(document)
        semantic = {key: value for key, value in document.items() if key != "context_id"}
        if hashlib.sha256(_json_bytes(semantic)).hexdigest() != document.get("context_id"):
            raise ValueError("analysis context ID does not match semantic content")
        if _json_bytes(document) != context_path.read_bytes():
            raise ValueError("analysis context is not canonical")
        markdown = render_analysis(document)
        if analysis_path.read_text(encoding="utf-8") != markdown:
            raise ValueError("analysis Markdown does not match context.json")
        if readme_path.read_text(encoding="utf-8") != README_TEXT:
            raise ValueError("analysis README is invalid")
        return document, markdown

    def _latest_decision_reports(self) -> tuple[DecisionReport, ...]:
        values: list[DecisionReport] = []
        for session in (MarketSession.JP_CLOSE, MarketSession.US_CLOSE, MarketSession.WEEKLY):
            with suppress(LookupError):
                values.append(self._reports.latest(session))
        return tuple(values)

    def _latest_screening_reports(self) -> tuple[ScreeningReport, ...]:
        values: list[ScreeningReport] = []
        for market in ("jp", "us"):
            with suppress(LookupError):
                values.append(self._screening.latest_report(market))
        return tuple(values)

    def _decision_context(self, report: DecisionReport) -> dict[str, Any]:
        return {
            "report_id": report.report_id,
            "session": report.session.value,
            "as_of": report.as_of.isoformat(),
            "policy": {
                "name": report.policy_name,
                "version": report.policy_version,
                "settings": dict(report.policy_settings),
            },
            "decisions": [_decision_document(item) for item in report.decisions],
            "candidate_decisions": [
                _decision_document(item) for item in report.candidate_decisions
            ],
            "previous_report_id": report.previous_report_id,
            "input_report_ids": list(report.input_report_ids),
            "screening_report_ids": list(report.screening_report_ids),
            "diagnostics": list(report.diagnostics),
        }

    def _previous_delta(self, report: DecisionReport) -> dict[str, Any]:
        assert report.previous_report_id is not None
        previous = self._reports.show(report.previous_report_id)
        old = {
            instrument_key(item.instrument): (item.action.value, item.confidence.value)
            for item in (*previous.decisions, *previous.candidate_decisions)
        }
        current = {
            instrument_key(item.instrument): (item.action.value, item.confidence.value)
            for item in (*report.decisions, *report.candidate_decisions)
        }
        keys = sorted(set(old) | set(current))
        return {
            "session": report.session.value,
            "current_report_id": report.report_id,
            "previous_report_id": previous.report_id,
            "changes": [
                {
                    "instrument": key,
                    "previous": list(old[key]) if key in old else None,
                    "current": list(current[key]) if key in current else None,
                }
                for key in keys
                if old.get(key) != current.get(key)
            ],
        }

    @staticmethod
    def _input_artifact_ids(
        portfolio_id: str,
        watch_history: tuple[dict[str, Any], ...],
        decision_reports: tuple[DecisionReport, ...],
        screening_reports: tuple[ScreeningReport, ...],
    ) -> list[str]:
        values = {portfolio_id}
        for revision in watch_history:
            values.add(revision["watchlist_id"])
            if revision["previous_watchlist_id"] is not None:
                values.add(revision["previous_watchlist_id"])
            values.update(
                item["source_screen_report_id"]
                for item in revision["items"]
                if item["source_screen_report_id"] is not None
            )
        for decision_report in decision_reports:
            values.add(decision_report.report_id)
            if decision_report.previous_report_id is not None:
                values.add(decision_report.previous_report_id)
            values.update(decision_report.input_report_ids)
            values.update(decision_report.screening_report_ids)
            for decision in (
                *decision_report.decisions,
                *decision_report.candidate_decisions,
            ):
                for evidence in decision.evidence:
                    values.update(evidence.evidence_ids)
        for screening_report in screening_reports:
            values.update((screening_report.report_id, screening_report.universe_id))
            for candidate in screening_report.candidates:
                for evidence in candidate.decision.evidence:
                    values.update(evidence.evidence_ids)
        return sorted(values)

    def _screen_market(self, report: ScreeningReport) -> str:
        return cast(str, self._screening.show_universe(report.universe_id).market)

    def _ensure_root(self) -> None:
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise ValueError("analysis workspace root must be a real directory")
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        if path.is_symlink():
            raise ValueError("analysis workspace path must not be a symbolic link")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def render_analysis(document: dict[str, Any]) -> str:
    """Render the static analysis view from context only."""

    lines = [
        "# MarketSieve Static Analysis",
        "",
        f"- Context ID: `{document['context_id']}`",
        f"- Evidence as of: `{document['as_of']}`",
        "",
        "## Current decisions",
        "",
    ]
    decisions = [
        (report["session"], decision)
        for report in document["decision_reports"]
        for decision in report["decisions"]
    ]
    if decisions:
        for session, decision in decisions:
            instrument = decision["instrument"]
            key = f"{instrument['mic']}:{instrument['symbol']}"
            lines.append(f"- {key} ({session}): {decision['action']} / {decision['confidence']}")
            lines.append(f"  - Next action: {decision['next_action']}")
            for condition in decision["invalidation_conditions"]:
                lines.append(f"  - Invalidation: {condition}")
    else:
        lines.append("- No decision report is available.")
    lines.extend(("", "## Screening candidates", ""))
    candidates = [
        item["decision"]
        for report in document["screening_reports"]
        for item in report["candidates"]
    ]
    if candidates:
        for decision in candidates:
            instrument = decision["instrument"]
            lines.append(
                f"- {instrument['mic']}:{instrument['symbol']}: "
                f"{decision['action']} / {decision['confidence']}"
            )
    else:
        lines.append("- No screening candidate is available.")
    lines.extend(("", "## Changes from exact previous reports", ""))
    changes = [item for delta in document["previous_deltas"] for item in delta["changes"]]
    if changes:
        for item in changes:
            lines.append(f"- {item['instrument']}: {item['previous']} -> {item['current']}")
    else:
        lines.append("- No recorded decision change is available.")
    lines.extend(("", "## Missing inputs and diagnostics", ""))
    for value in [*document["missing"], *document["diagnostics"]]:
        lines.append(f"- {value}")
    if not document["missing"] and not document["diagnostics"]:
        lines.append("- None.")
    lines.extend(
        (
            "",
            "## External research discussion",
            "",
            "Use the identifiers and evidence above to research current news and primary sources. "
            "Keep external findings and the human discussion outside MarketSieve's canonical "
            "artifacts.",
            "",
        )
    )
    return "\n".join(lines)


def _validate_analysis_document(document: dict[str, Any]) -> None:
    required = {
        "context_id",
        "schema",
        "as_of",
        "portfolio",
        "watchlist",
        "decision_reports",
        "screening_reports",
        "previous_deltas",
        "input_artifact_ids",
        "missing",
        "diagnostics",
        "constraints",
    }
    if set(document) != required:
        raise ValueError("analysis context structure is invalid")
    _validate_digest(document["context_id"], "analysis context ID")
    _validate_datetime(document["as_of"], "analysis as_of")
    portfolio = document["portfolio"]
    if not isinstance(portfolio, dict) or set(portfolio) != {
        "object_id",
        "as_of",
        "source",
        "source_name",
        "dataset",
        "diagnostics",
        "holdings",
    }:
        raise ValueError("analysis portfolio structure is invalid")
    _validate_digest(portfolio["object_id"], "analysis portfolio object ID")
    _validate_datetime(portfolio["as_of"], "analysis portfolio as_of")
    if any(not isinstance(portfolio[key], str) for key in ("source", "source_name", "dataset")):
        raise ValueError("analysis portfolio identity is invalid")
    _validate_string_list(portfolio["diagnostics"], "analysis portfolio diagnostics")
    if not isinstance(portfolio["holdings"], list):
        raise ValueError("analysis portfolio holdings are invalid")
    for instrument in portfolio["holdings"]:
        _validate_instrument(instrument)
    _validate_watchlist(document["watchlist"])
    _validate_object_list(
        document["decision_reports"], "decision reports", _validate_decision_report
    )
    _validate_object_list(
        document["screening_reports"], "screening reports", _validate_screening_report
    )
    _validate_object_list(document["previous_deltas"], "previous deltas", _validate_delta)
    artifact_ids = document["input_artifact_ids"]
    if not isinstance(artifact_ids, list):
        raise ValueError("analysis input artifact IDs are invalid")
    for value in artifact_ids:
        _validate_digest(value, "analysis input artifact ID")
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("analysis input artifact IDs must be unique")
    for key in ("missing", "diagnostics", "constraints"):
        _validate_string_list(document[key], f"analysis {key}", unique=True)


def _validate_instrument(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "key",
        "mic",
        "symbol",
        "currency",
        "timezone",
        "type",
    }:
        raise ValueError("analysis instrument is invalid")
    if any(not isinstance(value[key], str) for key in value) or value["type"] != "equity":
        raise ValueError("analysis instrument is invalid")


def _validate_watchlist(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"latest_id", "items", "history"}:
        raise ValueError("analysis watchlist is invalid")
    latest_id = value["latest_id"]
    if latest_id is not None:
        _validate_digest(latest_id, "analysis watchlist latest ID")
    history = value["history"]
    if not isinstance(history, list):
        raise ValueError("analysis watchlist history is invalid")
    for revision in history:
        _validate_watchlist_revision(revision)
    expected_id = history[-1]["watchlist_id"] if history else None
    expected_items = history[-1]["items"] if history else []
    if latest_id != expected_id or value["items"] != expected_items:
        raise ValueError("analysis watchlist latest projection is invalid")


def _validate_watchlist_revision(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "watchlist_id",
        "schema",
        "as_of",
        "previous_watchlist_id",
        "change",
        "items",
    }:
        raise ValueError("analysis watchlist revision is invalid")
    _validate_digest(value["watchlist_id"], "analysis watchlist revision ID")
    if value["schema"] != "watchlist-result/v1":
        raise ValueError("analysis watchlist revision schema is invalid")
    _validate_datetime(value["as_of"], "analysis watchlist revision as_of")
    if value["previous_watchlist_id"] is not None:
        _validate_digest(value["previous_watchlist_id"], "analysis previous watchlist ID")
    change = value["change"]
    if (
        not isinstance(change, dict)
        or set(change) != {"operation", "instrument"}
        or change["operation"] not in {"add", "remove", "add_provenance"}
        or not isinstance(change["instrument"], str)
    ):
        raise ValueError("analysis watchlist change is invalid")
    items = value["items"]
    if not isinstance(items, list):
        raise ValueError("analysis watchlist items are invalid")
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "key",
            "instrument",
            "source_screen_report_id",
        }:
            raise ValueError("analysis watchlist item is invalid")
        if not isinstance(item["key"], str):
            raise ValueError("analysis watchlist item key is invalid")
        _validate_watch_instrument(item["instrument"])
        if item["source_screen_report_id"] is not None:
            _validate_digest(item["source_screen_report_id"], "analysis source screening report ID")


def _validate_watch_instrument(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "mic",
        "symbol",
        "currency",
        "timezone",
        "type",
    }:
        raise ValueError("analysis watchlist instrument is invalid")
    if any(not isinstance(value[key], str) for key in value) or value["type"] != "equity":
        raise ValueError("analysis watchlist instrument is invalid")


def _validate_object_list(value: object, name: str, validator: Any) -> None:
    if not isinstance(value, list):
        raise ValueError(f"analysis {name} are invalid")
    for item in value:
        validator(item)


def _validate_decision_report(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "report_id",
        "session",
        "as_of",
        "policy",
        "decisions",
        "candidate_decisions",
        "previous_report_id",
        "input_report_ids",
        "screening_report_ids",
        "diagnostics",
    }:
        raise ValueError("analysis decision report is invalid")
    _validate_digest(value["report_id"], "analysis decision report ID")
    if value["session"] not in {item.value for item in MarketSession}:
        raise ValueError("analysis decision report session is invalid")
    _validate_datetime(value["as_of"], "analysis decision report as_of")
    policy = value["policy"]
    if not isinstance(policy, dict) or set(policy) != {"name", "version", "settings"}:
        raise ValueError("analysis decision report policy is invalid")
    if (
        not isinstance(policy["name"], str)
        or not isinstance(policy["version"], str)
        or not isinstance(policy["settings"], dict)
    ):
        raise ValueError("analysis decision report policy is invalid")
    for key in ("decisions", "candidate_decisions"):
        decisions = value[key]
        if not isinstance(decisions, list):
            raise ValueError("analysis decisions are invalid")
        for decision in decisions:
            _validate_decision(decision)
    if value["previous_report_id"] is not None:
        _validate_digest(value["previous_report_id"], "analysis previous report ID")
    for key in ("input_report_ids", "screening_report_ids"):
        _validate_digest_list(value[key], f"analysis {key}")
    _validate_string_list(value["diagnostics"], "analysis decision diagnostics")


def _validate_decision(value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError("analysis decision is invalid")
    try:
        parsed = _parse_decision(value)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("analysis decision is invalid") from error
    if _decision_document(parsed) != value:
        raise ValueError("analysis decision is not canonical")


def _validate_screening_report(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "report_id",
        "universe_id",
        "as_of",
        "policy",
        "processed_count",
        "eligible_count",
        "candidates",
        "diagnostics",
    }:
        raise ValueError("analysis screening report is invalid")
    if value["schema"] != "screening-report/v1":
        raise ValueError("analysis screening report schema is invalid")
    _validate_digest(value["report_id"], "analysis screening report ID")
    _validate_digest(value["universe_id"], "analysis screening universe ID")
    _validate_datetime(value["as_of"], "analysis screening report as_of")
    policy = value["policy"]
    if (
        not isinstance(policy, dict)
        or set(policy) != {"name", "version"}
        or any(not isinstance(item, str) for item in policy.values())
    ):
        raise ValueError("analysis screening policy is invalid")
    if any(
        not isinstance(value[key], int) or isinstance(value[key], bool) or value[key] < 0
        for key in ("processed_count", "eligible_count")
    ):
        raise ValueError("analysis screening counts are invalid")
    candidates = value["candidates"]
    if not isinstance(candidates, list):
        raise ValueError("analysis screening candidates are invalid")
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {
            "decision",
            "supporting_evidence_count",
        }:
            raise ValueError("analysis screening candidate is invalid")
        _validate_decision(candidate["decision"])
        count = candidate["supporting_evidence_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("analysis screening evidence count is invalid")
    _validate_string_list(value["diagnostics"], "analysis screening diagnostics")


def _validate_delta(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "session",
        "current_report_id",
        "previous_report_id",
        "changes",
    }:
        raise ValueError("analysis previous delta is invalid")
    if value["session"] not in {item.value for item in MarketSession}:
        raise ValueError("analysis delta session is invalid")
    _validate_digest(value["current_report_id"], "analysis current report ID")
    _validate_digest(value["previous_report_id"], "analysis delta previous report ID")
    changes = value["changes"]
    if not isinstance(changes, list):
        raise ValueError("analysis delta changes are invalid")
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"instrument", "previous", "current"}:
            raise ValueError("analysis delta change is invalid")
        if not isinstance(change["instrument"], str):
            raise ValueError("analysis delta instrument is invalid")
        for key in ("previous", "current"):
            state = change[key]
            if state is not None and (
                not isinstance(state, list)
                or len(state) != 2
                or any(not isinstance(item, str) for item in state)
            ):
                raise ValueError("analysis delta state is invalid")


def _validate_digest_list(value: object, name: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{name} are invalid")
    for item in value:
        _validate_digest(item, name)
    if len(value) != len(set(value)):
        raise ValueError(f"{name} must be unique")


def _validate_datetime(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} is invalid")


def _validate_digest(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _validate_string_list(value: object, name: str, *, unique: bool = False) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} are invalid")
    if unique and len(value) != len(set(value)):
        raise ValueError(f"{name} must be unique")
