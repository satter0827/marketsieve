"""Composition root for the public CLI application."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from marketsieve import __version__
from marketsieve_cli.adapters.config import Settings
from marketsieve_cli.adapters.console import ConsoleOutput, OutputMode
from marketsieve_cli.adapters.market_snapshots import MarketSnapshotStore
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
from marketsieve_cli.contracts import PreviewInputs as _PreviewInputs
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
PreviewInputs = _PreviewInputs
ResearchBuildInputs = _ResearchBuildInputs
capabilities_document = _capabilities_document


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


def build_market_service(
    settings_path: Path | None = None, *, state_root: Path = Path(".marketsieve")
) -> MarketService:
    return MarketService(
        SourcePluginRegistry(),
        MarketSnapshotStore(state_root / "market-snapshots"),
        Settings.resolve(settings_path),
    )


def build_market_snapshot(
    settings_path: Path | None,
    inputs: MarketBuildInputs | None,
    *,
    resume: str | None = None,
) -> dict[str, Any]:
    return build_market_service(settings_path).build(inputs, resume=resume)


def show_market_snapshot(settings_path: Path | None, snapshot_id: str) -> dict[str, Any]:
    return build_market_service(settings_path).show(snapshot_id)


def list_market_snapshots(settings_path: Path | None) -> dict[str, Any]:
    return build_market_service(settings_path).list()


def build_market_preview(settings_path: Path | None, request: PreviewInputs) -> ObjectPreviewServer:
    document = show_market_snapshot(settings_path, request.object_id)
    return ObjectPreviewServer(
        Path(document["artifacts"]["explorer.html"]).parent, port=request.port
    )


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
    settings_path: Path | None = None, *, state_root: Path = Path(".marketsieve")
) -> ResearchService:
    return ResearchService(
        SourcePluginRegistry(),
        build_market_service(settings_path, state_root=state_root),
        ResearchStore(state_root / "research"),
        Settings.resolve(settings_path),
    )


def build_security_research(
    settings_path: Path | None, inputs: ResearchBuildInputs
) -> dict[str, Any]:
    return build_research_service(settings_path).build(inputs)


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


def build_research_preview(
    settings_path: Path | None,
    request: PreviewInputs,
    *,
    snapshot_id: str | None,
    instrument_id: str | None,
) -> ObjectPreviewServer:
    document = show_security_research(
        settings_path,
        request.object_id,
        snapshot_id=snapshot_id,
        instrument_id=instrument_id,
    )
    return ObjectPreviewServer(
        Path(document["artifacts"]["explorer.html"]).parent, port=request.port
    )


def sdk_version() -> str:
    return __version__
