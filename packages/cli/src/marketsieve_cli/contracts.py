"""Typed invocation inputs and stable runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from marketsieve_cli.market_catalog import INDEX_RUNTIME_CATALOG

MARKET_EVIDENCE = ("benchmarks", "company", "financials", "price")
RESEARCH_EVIDENCE = ("benchmarks", "company", "events", "financials", "price")
MARKET_INDICES = tuple(INDEX_RUNTIME_CATALOG)
ANALYSIS_PROFILES = {
    "short-swing": {"holding_days": (2, 10), "windows": (1, 5, 20, 60)},
    "swing": {"holding_days": (10, 40), "windows": (5, 20, 60, 120)},
    "position": {"holding_days": (40, 120), "windows": (20, 60, 120, 252)},
}
QUERY_DOMAINS = (
    "identity",
    "price",
    "return",
    "trend",
    "momentum",
    "risk",
    "liquidity",
    "relative",
    "financial",
    "fundamental",
    "profitability",
    "safety",
    "valuation",
    "quality",
)


@dataclass(frozen=True, slots=True)
class CommandCapability:
    name: str
    summary: str
    result_mode: str
    result_schema: str | None
    external_network: bool = False
    loopback_server: bool = False
    writes: tuple[str, ...] = ()


COMMAND_CAPABILITIES = (
    CommandCapability(
        "market build",
        "Acquire one explicitly scoped Market Snapshot.",
        "document",
        "market-snapshot/v9",
        True,
        False,
        ("market_snapshot", "operation_run"),
    ),
    CommandCapability(
        "market capture",
        "Capture one selected market close.",
        "document",
        "market-snapshot/v9",
        True,
        False,
        ("market_snapshot", "operation_run"),
    ),
    CommandCapability(
        "market reconstruct",
        "Reconstruct historical price evidence.",
        "document",
        "market-snapshot/v9",
        True,
        False,
        ("market_snapshot", "operation_run"),
    ),
    CommandCapability(
        "market list", "List verified Market Snapshots.", "document", "market-snapshot-list/v3"
    ),
    CommandCapability(
        "market show", "Show one verified Market Snapshot.", "document", "market-snapshot/v9"
    ),
    CommandCapability(
        "market query",
        "Filter saved Snapshot evidence.",
        "document",
        "market-snapshot-query-result/v3",
    ),
    CommandCapability(
        "market security",
        "Show one security from a saved Snapshot.",
        "document",
        "market-snapshot-security-result/v1",
    ),
    CommandCapability(
        "market compare",
        "Compare compatible saved security fields.",
        "document",
        "market-snapshot-comparison/v3",
    ),
    CommandCapability(
        "market diff",
        "Compare two compatible Market Snapshots.",
        "document",
        "market-snapshot-diff/v1",
    ),
    CommandCapability(
        "market preview",
        "Preview one verified Market Snapshot.",
        "loopback_server",
        None,
        False,
        True,
    ),
    CommandCapability(
        "research build",
        "Acquire focused evidence for Snapshot securities.",
        "document",
        "security-research-batch/v1",
        True,
        False,
        ("security_research", "operation_run"),
    ),
    CommandCapability(
        "research list",
        "List verified Security Research packs.",
        "document",
        "security-research-list/v3",
    ),
    CommandCapability(
        "research show",
        "Show one verified Security Research pack.",
        "document",
        "security-research/v9",
    ),
    CommandCapability(
        "research preview",
        "Preview one verified Security Research pack.",
        "loopback_server",
        None,
        False,
        True,
    ),
    CommandCapability(
        "operations artifacts list", "List evidence object health.", "document", "artifact-list/v1"
    ),
    CommandCapability(
        "operations artifacts doctor",
        "Diagnose evidence object health.",
        "document",
        "artifact-doctor/v1",
    ),
    CommandCapability(
        "operations run list",
        "List structured generation runs.",
        "document",
        "operation-run-list/v2",
    ),
    CommandCapability(
        "operations run show", "Show one structured generation run.", "document", "operation-run/v2"
    ),
    CommandCapability(
        "operations run events",
        "List events for one generation run.",
        "document",
        "operation-events/v2",
    ),
    CommandCapability(
        "operations run prune",
        "Preview or apply generation-run cleanup.",
        "document",
        "operation-prune/v1",
        writes=("operation_run",),
    ),
    CommandCapability(
        "doctor",
        "Check the installed runtime and source.",
        "document",
        "doctor-result/v1",
        writes=("log_file",),
    ),
    CommandCapability(
        "capabilities",
        "Describe commands, schemas, and side effects.",
        "document",
        "capabilities-result/v13",
    ),
)


def capabilities_document(version: str) -> dict[str, object]:
    """Return the transport-independent public operation contract."""

    return {
        "schema": "capabilities-result/v13",
        "version": version,
        "commands": [
            {
                "name": capability.name,
                "summary": capability.summary,
                "result": {
                    "mode": capability.result_mode,
                    "schema": capability.result_schema,
                },
                "effects": {
                    "external_network": capability.external_network,
                    "loopback_server": capability.loopback_server,
                    "secrets": False,
                    "writes": list(capability.writes),
                },
            }
            for capability in COMMAND_CAPABILITIES
        ],
    }


@dataclass(frozen=True, slots=True)
class YFinanceSettings:
    batch_size: int = 50
    company_workers: int = 2
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_base_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class MarketQualitySettings:
    minimum_overall_price_coverage: Decimal = Decimal("0.95")
    minimum_index_price_coverage: Decimal = Decimal("0.90")


@dataclass(frozen=True, slots=True)
class ResearchQualitySettings:
    minimum_price_observations: int = 252


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    yfinance: YFinanceSettings = YFinanceSettings()
    market_quality: MarketQualitySettings = MarketQualitySettings()
    research_quality: ResearchQualitySettings = ResearchQualitySettings()


@dataclass(frozen=True, slots=True)
class MarketBuildInputs:
    indices: tuple[str, ...]
    evidence: tuple[str, ...]
    history_days: int | None
    as_of: date | None = None
    mode: str = "current"
    session: str | None = None

    def __post_init__(self) -> None:
        if not self.indices or self.indices != tuple(sorted(set(self.indices))):
            raise ValueError("market indices must be a unique sorted non-empty tuple")
        if set(self.indices) - set(MARKET_INDICES):
            raise ValueError("market indices contain an unsupported index")
        if not self.evidence or self.evidence != tuple(sorted(set(self.evidence))):
            raise ValueError("market evidence must be a unique sorted non-empty tuple")
        if set(self.evidence) - set(MARKET_EVIDENCE):
            raise ValueError("market evidence contains an unsupported domain")
        needs_history = bool({"price", "benchmarks"} & set(self.evidence))
        if "benchmarks" in self.evidence and "price" not in self.evidence:
            raise ValueError("market benchmark evidence requires price evidence")
        if needs_history and self.history_days is None:
            raise ValueError("market price evidence requires --history-days")
        if self.history_days is not None and not 30 <= self.history_days <= 3653:
            raise ValueError("market history days must be from 30 through 3653")
        if self.mode not in {"current", "historical_price_reconstruction"}:
            raise ValueError("market build mode is unsupported")
        if self.mode == "current" and self.as_of is not None:
            raise ValueError("current market build cannot set an historical as-of date")
        if self.mode == "historical_price_reconstruction":
            if self.as_of is None:
                raise ValueError("historical reconstruction requires an as-of date")
            if set(self.evidence) != {"benchmarks", "price"}:
                raise ValueError("historical reconstruction permits only price and benchmarks")
        if self.session is not None and self.session != "close":
            raise ValueError("only the close capture session is supported")


@dataclass(frozen=True, slots=True)
class ResearchBuildInputs:
    snapshot_id: str
    instrument_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    history_days: int | None

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.instrument_ids:
            raise ValueError("research snapshot and instruments are required")
        if self.instrument_ids != tuple(dict.fromkeys(self.instrument_ids)):
            raise ValueError("research instruments must be unique")
        if not self.evidence or self.evidence != tuple(sorted(set(self.evidence))):
            raise ValueError("research evidence must be a unique sorted non-empty tuple")
        if set(self.evidence) - set(RESEARCH_EVIDENCE):
            raise ValueError("research evidence contains an unsupported domain")
        needs_history = bool({"price", "benchmarks", "events"} & set(self.evidence))
        if "benchmarks" in self.evidence and "price" not in self.evidence:
            raise ValueError("research benchmark evidence requires price evidence")
        if needs_history and self.history_days is None:
            raise ValueError("research time-series evidence requires --history-days")
        if self.history_days is not None and not 30 <= self.history_days <= 3653:
            raise ValueError("research history days must be from 30 through 3653")


@dataclass(frozen=True, slots=True)
class MarketQueryInputs:
    snapshot_id: str
    filters: dict[str, tuple[str, ...]]
    minimums: dict[str, Decimal]
    maximums: dict[str, Decimal]
    present: tuple[str, ...]
    missing: tuple[str, ...]
    fields: tuple[str, ...]
    order: tuple[str, ...] = ()
    limit: int | None = None
    domains: tuple[str, ...] = ()
    profile: str | None = None
    budget: Decimal | None = None
    budget_currency: str | None = None
    trading_unit: int | None = None
    use_snapshot_fx: bool = False

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("market query snapshot is required")
        if self.limit is not None and self.limit <= 0:
            raise ValueError("market query limit must be positive")
        if self.domains != tuple(dict.fromkeys(self.domains)) or set(self.domains) - set(
            QUERY_DOMAINS
        ):
            raise ValueError("market query domains must be unique and supported")
        if self.profile is not None and self.profile not in ANALYSIS_PROFILES:
            raise ValueError("market query profile is unsupported")
        if self.budget is not None and (not self.budget.is_finite() or self.budget < 0):
            raise ValueError("market query budget must be finite and non-negative")
        if (self.budget is None) != (self.budget_currency is None):
            raise ValueError("market query budget and currency must be provided together")
        if self.trading_unit is not None and self.trading_unit <= 0:
            raise ValueError("market query trading unit must be positive")
        if self.use_snapshot_fx and self.budget is None:
            raise ValueError("snapshot FX requires a budget")


@dataclass(frozen=True, slots=True)
class MarketCompareInputs:
    snapshot_id: str
    instrument_ids: tuple[str, ...]
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("market compare snapshot is required")
        if len(self.instrument_ids) < 2:
            raise ValueError("market snapshot compare requires at least two instruments")
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            raise ValueError("market snapshot compare instruments must be unique")


@dataclass(frozen=True, slots=True)
class MarketDiffInputs:
    left_snapshot_id: str
    right_snapshot_id: str
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.left_snapshot_id or not self.right_snapshot_id:
            raise ValueError("market diff snapshot IDs are required")
