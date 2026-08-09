"""Rich, plain-text, and JSON console projections."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any, TextIO

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from marketsieve_cli.adapters.operations import OperationObserver
from marketsieve_cli.application.diagnostics import DiagnosticCheck
from marketsieve_extension_api import AcquisitionProgress

DOCTOR_SCHEMA_VERSION = "1.0.0"
CAPABILITIES_SCHEMA_VERSION = "1.0.0"
ERROR_SCHEMA_VERSION = "1.0.0"
JA_LABELS = {
    "schema_version": "スキーマ版",
    "instrument": "銘柄",
    "source_profile": "取得元プロファイル",
    "snapshot_id": "スナップショットID",
    "sections": "セクション",
    "price": "価格",
    "technical": "テクニカル",
    "financial": "財務",
    "valuation": "バリュエーション",
    "risk": "リスク",
    "events": "イベント",
    "data_quality": "データ品質",
    "status": "状態",
    "as_of": "基準時点",
    "completeness": "充足率",
    "values": "値",
    "warnings": "警告",
    "missing_reasons": "欠損理由",
    "provenance": "出典",
    "evidence_id": "根拠ID",
    "summary": "概要",
    "disclaimer": "注意事項",
    "available": "利用可能",
    "partial": "一部利用可能",
    "unavailable": "利用不可",
    "invalid": "無効",
    "insufficient_history": "履歴不足",
    "not_present_in_snapshot": "スナップショットにデータがありません",
}
JA_PROGRESS_STATES = {
    "started": "開始",
    "running": "実行中",
    "retrying": "再試行",
    "completed": "完了",
    "heartbeat": "実行中",
}
JA_PROGRESS_PHASES = {
    "price": "価格",
    "company_financials": "企業・財務",
    "market_indicators": "市場指標",
    "research_price": "Research価格",
    "research_company": "Research企業",
    "research_financials": "Research財務",
    "research_events": "Researchイベント",
    "research_benchmarks": "Researchベンチマーク",
}


class OutputMode(StrEnum):
    """Supported console projections."""

    AUTO = "auto"
    RICH = "rich"
    TEXT = "text"
    JSON = "json"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _localized(value: Any, locale: str) -> Any:
    if locale != "ja":
        return value
    if isinstance(value, dict):
        return {
            JA_LABELS.get(str(key), str(key)): _localized(item, locale)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_localized(item, locale) for item in value]
    if isinstance(value, str):
        return JA_LABELS.get(value, value)
    return value


def doctor_document(checks: tuple[DiagnosticCheck, ...]) -> dict[str, Any]:
    """Build the machine-readable diagnostics document."""

    ready = all(check.passed for check in checks)
    return {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "checks": [
            {
                "name": check.name,
                "detail": check.detail,
                "status": "pass" if check.passed else "fail",
                "action": check.action,
            }
            for check in checks
        ],
        "status": "ready" if ready else "not_ready",
    }


class ConsoleOutput:
    """Write application documents without changing their semantics."""

    def __init__(
        self,
        mode: OutputMode,
        *,
        stdout: TextIO,
        stderr: TextIO,
        width: int | None = None,
        locale: str = "ja",
    ) -> None:
        self._requested = mode
        self._mode = self._resolve(mode, stdout)
        self._stdout = stdout
        self._stderr = stderr
        self._locale = locale
        self._console = Console(
            file=stdout,
            width=width,
            force_terminal=self._mode is OutputMode.RICH,
            no_color=None,
            safe_box=True,
        )
        self._error_console = Console(file=stderr, force_terminal=self._mode is OutputMode.RICH)

    @staticmethod
    def _resolve(mode: OutputMode, stream: TextIO) -> OutputMode:
        if mode is not OutputMode.AUTO:
            return mode
        return OutputMode.RICH if stream.isatty() else OutputMode.JSON

    @property
    def mode(self) -> OutputMode:
        return self._mode

    @property
    def operation_observer(self) -> OperationObserver | None:
        """Return TTY-only progress rendering without changing stdout."""

        return self.emit_progress if self._stderr.isatty() else None

    def emit_progress(
        self, event_code: str, progress: AcquisitionProgress, elapsed_seconds: float
    ) -> None:
        if not self._stderr.isatty():
            return
        timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
        state = "heartbeat" if event_code == "heartbeat" else progress.state.value
        if self._locale == "ja":
            rendered_state = JA_PROGRESS_STATES[state]
            phase = JA_PROGRESS_PHASES.get(progress.phase, progress.phase)
            line = (
                f"{timestamp} 状態={rendered_state} 段階={phase} "
                f"完了={progress.completed} 総数={progress.total} "
                f"失敗={progress.failure_count} 経過={elapsed_seconds:.1f}秒"
            )
            if event_code == "retry":
                line += (
                    f" 再試行={progress.attempt}/{progress.max_attempts} "
                    f"待機={progress.retry_after_seconds:.1f}秒"
                )
        else:
            line = (
                f"{timestamp} state={state} phase={progress.phase} "
                f"completed={progress.completed} total={progress.total} "
                f"failures={progress.failure_count} elapsed={elapsed_seconds:.1f}s"
            )
            if event_code == "retry":
                line += (
                    f" attempt={progress.attempt}/{progress.max_attempts} "
                    f"retry_after={progress.retry_after_seconds:.1f}s"
                )
        self._stderr.write(line + "\n")
        self._stderr.flush()

    def emit_landing(self, version: str) -> None:
        if self._locale == "ja":
            description = "再現可能な日本株・米国株分析\n取得済みデータだけを使用します。"
            quick_start = (
                "marketsieve doctor\nmarketsieve market build --all --evidence price "
                "--history-days 1095\nmarketsieve market show latest"
            )
        else:
            description = "Reproducible Japanese and U.S. equity analysis\nOffline by default."
            quick_start = (
                "marketsieve doctor\nmarketsieve market build --all --evidence price "
                "--history-days 1095\nmarketsieve market show latest"
            )
        if self._mode is OutputMode.RICH:
            body = Text(f"{description}\n\n{quick_start}")
            self._console.print(Panel(body, title=f"MarketSieve {version}", border_style="cyan"))
            return
        self._stdout.write(f"MarketSieve {version}\n{description}\n{quick_start}\n")

    def emit_doctor(self, checks: tuple[DiagnosticCheck, ...]) -> None:
        document = doctor_document(checks)
        if self._mode is OutputMode.JSON:
            self._stdout.write(_json(document) + "\n")
            return
        if self._mode is OutputMode.TEXT:
            for check in document["checks"]:
                status = "合格" if check["status"] == "pass" else "不合格"
                self._stdout.write(
                    f"{status if self._locale == 'ja' else check['status'].upper()} "
                    f"{check['name']}: {check['detail']}\n"
                )
                if check["action"]:
                    label = "対応" if self._locale == "ja" else "ACTION"
                    self._stdout.write(f"{label} {check['action']}\n")
            ready = "利用可能" if document["status"] == "ready" else "要対応"
            status = ready if self._locale == "ja" else document["status"].replace("_", " ").title()
            self._stdout.write(f"{'状態' if self._locale == 'ja' else 'STATUS'} {status}\n")
            return
        table = Table(title="Environment diagnostics", box=box.ROUNDED, expand=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Check")
        table.add_column("Detail")
        for check in document["checks"]:
            passed = check["status"] == "pass"
            table.add_row(
                "[bold green]PASS[/]" if passed else "[bold red]FAIL[/]",
                check["name"],
                check["detail"],
            )
            if check["action"]:
                table.add_row("", "Action", check["action"], style="yellow")
        self._console.print(table)
        ready = document["status"] == "ready"
        self._console.print(
            Panel(
                "[bold green]Ready[/]" if ready else "[bold red]Not ready[/]",
                border_style="green" if ready else "red",
            )
        )

    def emit_capabilities(self, payload: dict[str, Any]) -> None:
        if self._mode is OutputMode.JSON:
            self._stdout.write(_json(payload) + "\n")
            return
        if self._mode is OutputMode.TEXT:
            for command in payload["commands"]:
                self._stdout.write(f"{command['name']}: {command['summary']}\n")
            return
        table = Table(title="CLI capabilities", box=box.ROUNDED, expand=True)
        table.add_column("Command")
        table.add_column("Purpose")
        table.add_column("Output schema")
        for command in payload["commands"]:
            table.add_row(command["name"], command["summary"], command["output_schema"] or "-")
        self._console.print(table)

    def emit_document(self, payload: dict[str, Any], *, title: str) -> None:
        """Render a workbench document without changing its machine values."""

        if self._mode is OutputMode.JSON:
            self._stdout.write(_json(payload) + "\n")
            return
        rendered = json.dumps(
            _localized(payload, self._locale), ensure_ascii=False, indent=2, sort_keys=True
        )
        if self._mode is OutputMode.TEXT:
            self._stdout.write(rendered + "\n")
            return
        localized_title = {
            "Equity inspection": "株式情報",
            "Equity comparison": "株式比較",
            "Indicator analysis": "指標分析",
        }.get(title, title)
        self._console.print(
            Panel(
                rendered,
                title=localized_title if self._locale == "ja" else title,
                border_style="cyan",
            )
        )

    def emit_error(self, code: str, message: str) -> None:
        if self._mode is OutputMode.JSON:
            payload = {"schema_version": ERROR_SCHEMA_VERSION, "error": code, "message": message}
            self._stderr.write(_json(payload) + "\n")
            return
        if self._mode is OutputMode.RICH:
            title = "エラー" if self._locale == "ja" else "Error"
            self._error_console.print(Panel(message, title=title, border_style="red"))
            return
        prefix = "エラー" if self._locale == "ja" else "ERROR"
        self._stderr.write(f"{prefix} {code}: {message}\n")

    def emit_warning(self, code: str, message: str) -> None:
        prefix = "警告" if self._locale == "ja" else "WARNING"
        self._stderr.write(f"{prefix} {code}: {message}\n")
