"""Canonical decision-report serialization, rendering, and persistence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from marketsieve import (
    DecisionAction,
    DecisionConfidence,
    DecisionEvidence,
    DecisionReport,
    EvidenceDirection,
    Holding,
    InstrumentDecision,
    MarketSession,
    PortfolioSnapshot,
    WatchItem,
)
from marketsieve.domain import Instrument, InstrumentType

REPORT_SCHEMA = "decision-report/v1"
REF_NAMES = {
    MarketSession.JP_CLOSE: "jp-latest",
    MarketSession.US_CLOSE: "us-latest",
    MarketSession.WEEKLY: "weekly-latest",
}
ACTION_LABELS = {
    DecisionAction.BUY_CANDIDATE: "買い候補",
    DecisionAction.WAIT_FOR_PULLBACK: "押し目待ち",
    DecisionAction.WAIT_FOR_EARNINGS: "決算待ち",
    DecisionAction.PASS: "見送り",
    DecisionAction.KEEP: "保有継続",
    DecisionAction.WATCH: "警戒",
    DecisionAction.REDUCE_REVIEW: "縮小検討",
    DecisionAction.SELL_REVIEW: "売却検討",
    DecisionAction.INDETERMINATE: "判定不能",
}
CONFIDENCE_LABELS = {
    DecisionConfidence.HIGH: "高",
    DecisionConfidence.MEDIUM: "中",
    DecisionConfidence.LOW: "低",
}


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _instrument_document(instrument: Instrument) -> dict[str, str]:
    return {
        "symbol": instrument.symbol,
        "mic": instrument.mic,
        "currency": instrument.currency,
        "timezone": instrument.exchange_timezone.key,
        "type": instrument.instrument_type.value,
    }


def _holding_document(holding: Holding) -> dict[str, object]:
    return {
        "instrument": _instrument_document(holding.instrument),
        "quantity": _decimal_text(holding.quantity),
        "average_acquisition_price": _decimal_text(holding.average_acquisition_price),
        "account_type": holding.account_type,
    }


def _evidence_document(evidence: DecisionEvidence) -> dict[str, object]:
    return {
        "code": evidence.code,
        "direction": evidence.direction.value,
        "value": evidence.value,
        "threshold": evidence.threshold,
        "evidence_ids": list(evidence.evidence_ids),
    }


def _decision_document(decision: InstrumentDecision) -> dict[str, object]:
    return {
        "instrument": _instrument_document(decision.instrument),
        "held": decision.held,
        "action": decision.action.value,
        "confidence": decision.confidence.value,
        "evidence": [_evidence_document(item) for item in decision.evidence],
        "next_earnings_date": (
            decision.next_earnings_date.isoformat() if decision.next_earnings_date else None
        ),
        "revenue_growth": _decimal_text(decision.revenue_growth)
        if decision.revenue_growth is not None
        else None,
        "eps_growth": _decimal_text(decision.eps_growth)
        if decision.eps_growth is not None
        else None,
        "free_cash_flow": _decimal_text(decision.free_cash_flow)
        if decision.free_cash_flow is not None
        else None,
        "valuation": dict(decision.valuation),
        "fundamentals": dict(decision.fundamentals),
        "invalidation_conditions": list(decision.invalidation_conditions),
        "next_action": decision.next_action,
        "policy": {
            "name": decision.policy_name,
            "version": decision.policy_version,
            "settings": dict(decision.policy_settings),
        },
    }


def semantic_document(
    session: MarketSession,
    as_of: datetime,
    portfolio: PortfolioSnapshot,
    decisions: tuple[InstrumentDecision, ...],
    diagnostics: tuple[str, ...],
    previous_report_id: str | None,
    input_report_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build canonical semantic content without its derived ID."""

    if not decisions:
        raise ValueError("a decision report requires at least one decision")
    first = decisions[0]
    return {
        "schema": REPORT_SCHEMA,
        "session": session.value,
        "as_of": as_of.isoformat(),
        "portfolio": {
            "as_of": portfolio.as_of.isoformat(),
            "source": portfolio.source,
            "holdings": [_holding_document(item) for item in portfolio.holdings],
            "watch_items": [
                {"instrument": _instrument_document(item.instrument)}
                for item in portfolio.watch_items
            ],
        },
        "policy": {
            "name": first.policy_name,
            "version": first.policy_version,
            "settings": dict(first.policy_settings),
        },
        "decisions": [_decision_document(item) for item in decisions],
        "diagnostics": list(diagnostics),
        "previous_report_id": previous_report_id,
        "input_report_ids": list(input_report_ids),
    }


def create_report(
    session: MarketSession,
    as_of: datetime,
    portfolio: PortfolioSnapshot,
    decisions: tuple[InstrumentDecision, ...],
    *,
    diagnostics: tuple[str, ...] = (),
    previous_report_id: str | None = None,
    input_report_ids: tuple[str, ...] = (),
) -> DecisionReport:
    """Create a report whose ID is the digest of its canonical semantic content."""

    semantic = semantic_document(
        session,
        as_of,
        portfolio,
        decisions,
        diagnostics,
        previous_report_id,
        input_report_ids,
    )
    report_id = hashlib.sha256(_json_bytes(semantic)).hexdigest()
    first = decisions[0]
    return DecisionReport(
        report_id,
        REPORT_SCHEMA,
        session,
        as_of,
        portfolio,
        first.policy_name,
        first.policy_version,
        first.policy_settings,
        decisions,
        diagnostics,
        previous_report_id,
        input_report_ids,
    )


def report_document(report: DecisionReport) -> dict[str, object]:
    semantic = semantic_document(
        report.session,
        report.as_of,
        report.portfolio,
        report.decisions,
        report.diagnostics,
        report.previous_report_id,
        report.input_report_ids,
    )
    expected = hashlib.sha256(_json_bytes(semantic)).hexdigest()
    if expected != report.report_id:
        raise ValueError("report ID does not match canonical semantic content")
    return {"report_id": report.report_id, **semantic}


def render_markdown(report: DecisionReport, previous_report: DecisionReport | None = None) -> str:
    """Render one stable Japanese Close Brief projection."""

    if report.previous_report_id is None and previous_report is not None:
        raise ValueError("a first report must not receive a previous report")
    if report.previous_report_id is not None and (
        previous_report is None or previous_report.report_id != report.previous_report_id
    ):
        raise ValueError("the exact previous report is required for change projection")

    counts = {action: 0 for action in DecisionAction}
    for decision in report.decisions:
        counts[decision.action] += 1
    attention = tuple(
        item
        for item in report.decisions
        if item.action
        not in {DecisionAction.KEEP, DecisionAction.PASS, DecisionAction.INDETERMINATE}
    )
    changed, unchanged, removed = _decision_changes(report, previous_report)
    title = "週末作戦会議" if report.session is MarketSession.WEEKLY else "Close Brief"
    conclusion = _conclusion(counts)
    lines = [
        f"# {title}",
        "",
        "## 1. 今日の結論",
        "",
        conclusion,
        "",
        "## 2. 今日見るべきもの",
        "",
        *_decision_lines(attention, empty="該当なし"),
        "",
        "## 3. 前回からの変化",
        "",
        *_change_lines(changed, removed),
        "",
        "## 4. 変化なし",
        "",
        *_decision_lines(unchanged, empty="該当なし"),
        "",
        "## 5. 次の一手",
        "",
        *(f"- {_instrument_key(item.instrument)}: {item.next_action}" for item in report.decisions),
        "",
        "## 6. データ上の制約",
        "",
        *(f"- {item}" for item in report.diagnostics),
    ]
    if not report.diagnostics:
        lines.append("- なし")
    lines.extend(("", "## 7. 詳細と根拠", ""))
    for decision in report.decisions:
        lines.extend(
            (
                f"### {_instrument_key(decision.instrument)}",
                "",
                f"- 判断: {ACTION_LABELS[decision.action]}",
                f"- 確信度: {CONFIDENCE_LABELS[decision.confidence]}",
                *_context_lines("財務", decision.fundamentals),
                *_context_lines("評価", decision.valuation),
                *(f"- 根拠: {item.code}" for item in decision.evidence),
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _decision_changes(
    report: DecisionReport, previous: DecisionReport | None
) -> tuple[
    tuple[tuple[InstrumentDecision, InstrumentDecision | None], ...],
    tuple[InstrumentDecision, ...],
    tuple[InstrumentDecision, ...],
]:
    previous_by_instrument = (
        {}
        if previous is None
        else {(item.instrument.mic, item.instrument.symbol): item for item in previous.decisions}
    )
    current_ids: set[tuple[str, str]] = set()
    changed: list[tuple[InstrumentDecision, InstrumentDecision | None]] = []
    unchanged: list[InstrumentDecision] = []
    for current in report.decisions:
        identity = (current.instrument.mic, current.instrument.symbol)
        current_ids.add(identity)
        old = previous_by_instrument.get(identity)
        if old is not None and (old.action, old.confidence) == (
            current.action,
            current.confidence,
        ):
            unchanged.append(current)
        else:
            changed.append((current, old))
    removed = tuple(
        item
        for identity, item in sorted(previous_by_instrument.items())
        if identity not in current_ids
    )
    return tuple(changed), tuple(unchanged), removed


def _change_lines(
    changed: tuple[tuple[InstrumentDecision, InstrumentDecision | None], ...],
    removed: tuple[InstrumentDecision, ...],
) -> tuple[str, ...]:
    lines: list[str] = []
    for current, previous in changed:
        if previous is None:
            change = (
                f"新規 → {ACTION_LABELS[current.action]}"
                f" (確信度 {CONFIDENCE_LABELS[current.confidence]})"
            )
        else:
            change = (
                f"{ACTION_LABELS[previous.action]} ({CONFIDENCE_LABELS[previous.confidence]})"
                f" → {ACTION_LABELS[current.action]} ({CONFIDENCE_LABELS[current.confidence]})"
            )
        lines.append(f"- {_instrument_key(current.instrument)}: {change}")
    lines.extend(
        f"- {_instrument_key(item.instrument)}: 対象外 (前回 {ACTION_LABELS[item.action]})"
        for item in removed
    )
    return tuple(lines) or ("該当なし",)


def _conclusion(counts: dict[DecisionAction, int]) -> str:
    if counts[DecisionAction.SELL_REVIEW] or counts[DecisionAction.REDUCE_REVIEW]:
        return "保有銘柄に見直し候補があります。"
    if counts[DecisionAction.BUY_CANDIDATE]:
        return "新しい買い候補があります。"
    if counts[DecisionAction.INDETERMINATE]:
        return "判断に必要なデータが不足しています。"
    return "大きな変更はありません。"


def _decision_lines(decisions: tuple[InstrumentDecision, ...], *, empty: str) -> tuple[str, ...]:
    if not decisions:
        return (empty,)
    return tuple(
        f"- {_instrument_key(item.instrument)}: {ACTION_LABELS[item.action]}" for item in decisions
    )


def _instrument_key(instrument: Instrument) -> str:
    return f"{instrument.mic}:{instrument.symbol}"


def _context_lines(label: str, values: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(f"- {label}: {name}={value}" for name, value in values)


class ReportStore:
    """Persist immutable reports, deterministic Markdown, and atomic latest references."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._objects = root / "objects"
        self._rendered = root / "rendered"
        self._refs = root / "refs"

    def put(self, report: DecisionReport) -> DecisionReport:
        document = report_document(report)
        payload = _json_bytes(document)
        previous = self.show(report.previous_report_id) if report.previous_report_id else None
        markdown = render_markdown(report, previous).encode("utf-8")
        for directory in (self._objects, self._rendered, self._refs):
            self._ensure_directory(directory)
        self._write_immutable(self._objects / f"{report.report_id}.json", payload)
        self._write_immutable(self._rendered / f"{report.report_id}.md", markdown)
        if any(item.action is not DecisionAction.INDETERMINATE for item in report.decisions):
            self._write_atomic(
                self._refs / f"{REF_NAMES[report.session]}.json",
                _json_bytes({"report_id": report.report_id}),
            )
        return self.show(report.report_id)

    def list(self) -> tuple[DecisionReport, ...]:
        if not self._root.exists() or not self._objects.exists():
            return ()
        self._require_real_directory(self._objects)
        return tuple(
            self.show(path.stem)
            for path in sorted(self._objects.glob("*.json"))
            if not path.is_symlink()
        )

    def show(self, report_id: str) -> DecisionReport:
        self._validate_id(report_id)
        self._require_real_directory(self._objects)
        path = self._objects / f"{report_id}.json"
        if path.is_symlink() or not path.is_file():
            raise LookupError(f"decision report {report_id} does not exist")
        document = json.loads(path.read_bytes())
        report = _parse_report(document)
        if (
            report.report_id != report_id
            or _json_bytes(report_document(report)) != path.read_bytes()
        ):
            raise ValueError("stored decision report is not canonical")
        return report

    def latest(self, session: MarketSession) -> DecisionReport:
        self._require_real_directory(self._refs)
        path = self._refs / f"{REF_NAMES[session]}.json"
        if path.is_symlink() or not path.is_file():
            raise LookupError(f"latest report does not exist for {session.value}")
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict) or set(value) != {"report_id"}:
            raise ValueError("latest report reference is invalid")
        if _json_bytes(value) != path.read_bytes():
            raise ValueError("latest report reference is not canonical")
        report_id = value["report_id"]
        if not isinstance(report_id, str):
            raise ValueError("latest report reference is invalid")
        return self.show(report_id)

    def resolve(self, report_id: str) -> DecisionReport:
        """Resolve an exact ID or the newest report across explicit sessions."""

        if report_id != "latest":
            return self.show(report_id)
        reports = self.list()
        if not reports:
            raise LookupError("no decision report exists")
        return max(reports, key=lambda report: (report.as_of.timestamp(), report.report_id))

    def markdown(self, report_id: str) -> str:
        report = self.show(report_id)
        self._require_real_directory(self._rendered)
        path = self._rendered / f"{report_id}.md"
        if path.is_symlink() or not path.is_file():
            raise LookupError(f"rendered report {report_id} does not exist")
        previous = self.show(report.previous_report_id) if report.previous_report_id else None
        expected = render_markdown(report, previous)
        if path.read_text(encoding="utf-8") != expected:
            raise ValueError("rendered report does not match canonical JSON")
        return expected

    def _write_immutable(self, path: Path, payload: bytes) -> None:
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ValueError("immutable report artifact conflicts with existing content")
            return
        self._write_atomic(path, payload)

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        if path.is_symlink():
            raise ValueError("report path must not be a symbolic link")
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _ensure_directory(self, path: Path) -> None:
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise ValueError("report root must be a real directory")
        self._root.mkdir(parents=True, exist_ok=True)
        if path.exists() and (path.is_symlink() or not path.is_dir()):
            raise ValueError("report storage path must be a real directory")
        path.mkdir(exist_ok=True)

    def _require_real_directory(self, path: Path) -> None:
        if (
            not self._root.is_dir()
            or self._root.is_symlink()
            or not path.is_dir()
            or path.is_symlink()
        ):
            raise LookupError("report storage directory does not exist")

    @staticmethod
    def _validate_id(report_id: str) -> None:
        if len(report_id) != 64 or any(value not in "0123456789abcdef" for value in report_id):
            raise ValueError("report ID must be a lowercase SHA-256 digest")


def _parse_instrument(value: dict[str, Any]) -> Instrument:
    return Instrument.create(
        symbol=value["symbol"],
        mic=value["mic"],
        currency=value["currency"],
        exchange_timezone=value["timezone"],
        instrument_type=InstrumentType(value["type"]),
    )


def _optional_decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _pairs(value: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(item)) for key, item in value.items()))


def _parse_report(value: dict[str, Any]) -> DecisionReport:
    portfolio_value = value["portfolio"]
    holdings = tuple(
        Holding(
            _parse_instrument(item["instrument"]),
            Decimal(item["quantity"]),
            Decimal(item["average_acquisition_price"]),
            item["account_type"],
        )
        for item in portfolio_value["holdings"]
    )
    watch_items = tuple(
        WatchItem(_parse_instrument(item["instrument"])) for item in portfolio_value["watch_items"]
    )
    portfolio = PortfolioSnapshot(
        datetime.fromisoformat(portfolio_value["as_of"]),
        holdings,
        watch_items,
        portfolio_value["source"],
    )
    decisions = tuple(_parse_decision(item) for item in value["decisions"])
    return DecisionReport(
        value["report_id"],
        value["schema"],
        MarketSession(value["session"]),
        datetime.fromisoformat(value["as_of"]),
        portfolio,
        value["policy"]["name"],
        value["policy"]["version"],
        _pairs(value["policy"]["settings"]),
        decisions,
        tuple(value["diagnostics"]),
        value["previous_report_id"],
        tuple(value["input_report_ids"]),
    )


def _parse_decision(value: dict[str, Any]) -> InstrumentDecision:
    policy = value["policy"]
    return InstrumentDecision(
        _parse_instrument(value["instrument"]),
        value["held"],
        DecisionAction(value["action"]),
        DecisionConfidence(value["confidence"]),
        tuple(
            DecisionEvidence(
                item["code"],
                EvidenceDirection(item["direction"]),
                item["value"],
                item["threshold"],
                tuple(item["evidence_ids"]),
            )
            for item in value["evidence"]
        ),
        date.fromisoformat(value["next_earnings_date"]) if value["next_earnings_date"] else None,
        _optional_decimal(value["revenue_growth"]),
        _optional_decimal(value["eps_growth"]),
        _optional_decimal(value["free_cash_flow"]),
        _pairs(value["valuation"]),
        _pairs(value["fundamentals"]),
        tuple(value["invalidation_conditions"]),
        value["next_action"],
        policy["name"],
        policy["version"],
        _pairs(policy["settings"]),
    )
