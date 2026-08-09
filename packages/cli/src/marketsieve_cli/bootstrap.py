"""Composition root for the public CLI application."""

from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from marketsieve import __version__
from marketsieve_cli.adapters.artifacts import ArtifactInventory
from marketsieve_cli.adapters.config import Settings
from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.adapters.market_snapshots import MarketSnapshotStore
from marketsieve_cli.adapters.operations import OperationObserver, OperationRunStore
from marketsieve_cli.adapters.plugins import SourcePluginRegistry
from marketsieve_cli.adapters.preview import ObjectPreviewServer
from marketsieve_cli.adapters.research import ResearchStore
from marketsieve_cli.application.diagnostics import DiagnosticsService
from marketsieve_cli.application.market import MarketService
from marketsieve_cli.application.research import ResearchService
from marketsieve_cli.contracts import (
    MARKET_EVIDENCE as _MARKET_EVIDENCE,
)
from marketsieve_cli.contracts import (
    MARKET_INDEX_GROUPS as _MARKET_INDEX_GROUPS,
)
from marketsieve_cli.contracts import (
    MARKET_INDICES as _MARKET_INDICES,
)
from marketsieve_cli.contracts import (
    RESEARCH_EVIDENCE as _RESEARCH_EVIDENCE,
)
from marketsieve_cli.contracts import (
    MarketBuildInputs as _MarketBuildInputs,
)
from marketsieve_cli.contracts import MarketCompareInputs as _MarketCompareInputs
from marketsieve_cli.contracts import MarketDiffInputs as _MarketDiffInputs
from marketsieve_cli.contracts import MarketQueryInputs as _MarketQueryInputs
from marketsieve_cli.contracts import (
    ResearchBuildInputs as _ResearchBuildInputs,
)
from marketsieve_cli.contracts import capabilities_document as _capabilities_document
from marketsieve_cli.observability import configure_logger

MARKET_EVIDENCE = _MARKET_EVIDENCE
MARKET_INDEX_GROUPS = _MARKET_INDEX_GROUPS
MARKET_INDICES = _MARKET_INDICES
RESEARCH_EVIDENCE = _RESEARCH_EVIDENCE
MarketBuildInputs = _MarketBuildInputs
MarketQueryInputs = _MarketQueryInputs
MarketCompareInputs = _MarketCompareInputs
MarketDiffInputs = _MarketDiffInputs
ResearchBuildInputs = _ResearchBuildInputs
capabilities_document = _capabilities_document


def state_root() -> Path:
    """Resolve local state once from the process boundary."""

    return Path(os.environ.get("MARKETSIEVE_STATE_DIR", ".marketsieve"))


def _resolved_state_root(explicit: Path | None) -> Path:
    return explicit if explicit is not None else state_root()


def _input_document(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _input_document(asdict(value))
    if isinstance(value, dict):
        return {str(key): _input_document(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_input_document(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def build_console_output(
    mode: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
    width: int | None = None,
    locale: str = "ja",
) -> ConsoleOutput:
    return ConsoleOutput(OutputMode(mode), stdout=stdout, stderr=stderr, width=width, locale=locale)


def build_diagnostics_service(
    *, level: str | None = None, write_log_file: bool = False
) -> DiagnosticsService:
    return DiagnosticsService(logger=configure_logger(level=level, write_file=write_log_file))


def configure_application_logging(*, level: str | None, write_log_file: bool) -> None:
    configure_logger(level=level, write_file=write_log_file, state_dir=state_root())


def build_market_service(
    settings_path: Path | None = None, *, state_root: Path | None = None
) -> MarketService:
    resolved_root = _resolved_state_root(state_root)
    return MarketService(
        SourcePluginRegistry(),
        MarketSnapshotStore(resolved_root / "market-snapshots"),
        Settings.resolve(settings_path),
    )


def build_market_snapshot(
    settings_path: Path | None,
    inputs: MarketBuildInputs | None,
    *,
    resume: str | None = None,
    command: str = "market build",
    observer: OperationObserver | None = None,
) -> dict[str, Any]:
    runs = OperationRunStore(state_root())
    with runs.track(
        command,
        {"inputs": _input_document(inputs), "resume": resume},
        observer=observer,
    ) as operation:
        document = build_market_service(settings_path).build(
            inputs, resume=resume, progress=operation
        )
        snapshot_id = document.get("snapshot_id")
        if isinstance(snapshot_id, str):
            operation.publish(snapshot_id)
        operation.set_metrics(
            acquired_count=document.get("row_count"), coverage=document.get("coverage")
        )
        document["operation_run_id"] = operation.run_id
        return document


def show_market_snapshot(settings_path: Path | None, snapshot_id: str) -> dict[str, Any]:
    return build_market_service(settings_path).show(snapshot_id)


def list_market_snapshots(settings_path: Path | None) -> dict[str, Any]:
    return build_market_service(settings_path).list()


def query_market_snapshot(
    settings_path: Path | None,
    request: MarketQueryInputs,
) -> dict[str, Any]:
    return build_market_service(settings_path).query(request)


def read_market_snapshot_security(
    settings_path: Path | None, snapshot_id: str, instrument_id: str
) -> dict[str, Any]:
    return build_market_service(settings_path).row(snapshot_id, instrument_id)


def compare_market_snapshot_securities(
    settings_path: Path | None,
    request: MarketCompareInputs,
) -> dict[str, Any]:
    return build_market_service(settings_path).compare(request)


def diff_market_snapshots(
    settings_path: Path | None,
    request: MarketDiffInputs,
) -> dict[str, Any]:
    return build_market_service(settings_path).diff(request)


def build_research_service(
    settings_path: Path | None = None, *, state_root: Path | None = None
) -> ResearchService:
    resolved_root = _resolved_state_root(state_root)
    return ResearchService(
        SourcePluginRegistry(),
        build_market_service(settings_path, state_root=resolved_root),
        ResearchStore(resolved_root / "research"),
        Settings.resolve(settings_path),
    )


def build_security_research(
    settings_path: Path | None,
    inputs: ResearchBuildInputs,
    *,
    observer: OperationObserver | None = None,
) -> dict[str, Any]:
    runs = OperationRunStore(state_root())
    with runs.track(
        "research build", {"inputs": _input_document(inputs)}, observer=observer
    ) as operation:
        document = build_research_service(settings_path).build(
            inputs, progress=operation, published=operation.publish
        )
        operation.set_metrics(acquired_count=len(operation.published_object_ids), coverage=None)
        document["operation_run_id"] = operation.run_id
        return document


def show_security_research(
    settings_path: Path | None,
    research_id: str,
    *,
    snapshot_id: str | None = None,
    instrument_id: str | None = None,
) -> dict[str, Any]:
    return build_research_service(settings_path).show(
        research_id, snapshot_id=snapshot_id, instrument_id=instrument_id
    )


def list_security_research(
    settings_path: Path | None,
    *,
    snapshot_id: str | None = None,
    instrument_id: str | None = None,
) -> dict[str, Any]:
    return build_research_service(settings_path).list(
        snapshot_id=snapshot_id, instrument_id=instrument_id
    )


def artifact_inventory(
    *, object_type: str | None = None, status: str | None = None
) -> dict[str, Any]:
    return _artifact_inventory().list(object_type=object_type, status=status)


def artifact_doctor() -> dict[str, Any]:
    return _artifact_inventory().doctor()


def _artifact_inventory() -> ArtifactInventory:
    root = state_root()
    return ArtifactInventory(
        root,
        validators={
            "snapshot": MarketSnapshotStore._verify_object,
            "research": ResearchStore._verify,
        },
    )


def operation_runs() -> OperationRunStore:
    return OperationRunStore(state_root())


def build_preview(
    settings_path: Path | None,
    object_ref: str,
    *,
    security: str | None,
    port: int,
) -> ObjectPreviewServer:
    candidate = Path(object_ref)
    if candidate.is_dir():
        return ObjectPreviewServer(candidate, port=port)
    kind, separator, identifier = object_ref.partition(":")
    if not separator or kind not in {"snapshot", "research"} or not identifier:
        raise ValueError("object reference must be snapshot:ID, research:ID, or an object path")
    if kind == "snapshot":
        if security is not None:
            raise ValueError("--security applies only to research:latest")
        document = show_market_snapshot(settings_path, identifier)
    else:
        if identifier == "latest" and security is None:
            raise ValueError("research:latest requires --security")
        document = show_security_research(
            settings_path,
            identifier,
            snapshot_id="latest" if identifier == "latest" else None,
            instrument_id=security,
        )
    return ObjectPreviewServer(Path(document["artifacts"]["explorer.html"]).parent, port=port)


def sdk_version() -> str:
    return __version__
