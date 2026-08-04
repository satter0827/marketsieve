"""Offline source import and snapshot query use cases."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from marketsieve.analysis.indicators import (
    IndicatorName,
    IndicatorResult,
    IndicatorSpec,
    IndicatorStatus,
    calculate,
)
from marketsieve.data.daily import Adjustment, DailyBar
from marketsieve.domain import Instrument
from marketsieve_extension_api import (
    DailyBarBundleImporter,
    DailyBarFetcher,
    DailyBarFetchRequest,
    DailyBarSourceConfiguration,
    ImportedDailyBars,
)


class InstalledSourceInfo(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def distribution(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def value(self) -> str: ...


class StoredSnapshotInfo(Protocol):
    @property
    def object_id(self) -> str: ...

    @property
    def manifest(self) -> dict[str, Any]: ...


class PluginRegistry(Protocol):
    def installed(self) -> tuple[InstalledSourceInfo, ...]: ...

    def load_daily_bars(self, name: str) -> DailyBarBundleImporter: ...

    def load_fetcher(self, name: str) -> DailyBarFetcher: ...

    def can_fetch(self, name: str) -> bool: ...


class SourceProfileInfo(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def daily_bars_plugin(self) -> str: ...

    @property
    def currency(self) -> str: ...

    @property
    def timezone(self) -> str: ...

    @property
    def settings(self) -> dict[str, str]: ...


class SourceConfiguration(Protocol):
    def source_profile(self, name: str) -> SourceProfileInfo: ...


class SnapshotRepository(Protocol):
    def put_daily_bars(self, imported: ImportedDailyBars) -> StoredSnapshotInfo: ...

    def list(self) -> tuple[StoredSnapshotInfo, ...]: ...

    def show(self, object_id: str) -> StoredSnapshotInfo: ...

    def verify(self, object_id: str) -> StoredSnapshotInfo: ...

    def resolve(self, profile: str, instrument: str) -> StoredSnapshotInfo: ...

    def normalized(self, object_id: str) -> dict[str, Any]: ...

    def daily_bars(self, object_id: str) -> tuple[DailyBar, ...]: ...


DEFAULT_INDICATORS = (
    IndicatorSpec.create(IndicatorName.SMA, period=20),
    IndicatorSpec.create(IndicatorName.EMA, period=20),
    IndicatorSpec.create(IndicatorName.RSI, period=14),
    IndicatorSpec.create(IndicatorName.MACD, fast_period=12, slow_period=26, signal_period=9),
    IndicatorSpec.create(IndicatorName.ATR, period=14),
    IndicatorSpec.create(IndicatorName.PERIOD_RETURN, period=20),
    IndicatorSpec.create(IndicatorName.MAX_DRAWDOWN, period=252),
)


def indicator_document(result: IndicatorResult) -> dict[str, Any]:
    return {
        "name": result.name.value,
        "definition_version": result.definition_version,
        "parameters": dict(result.parameters),
        "status": result.status.value,
        "as_of": result.as_of.isoformat() if result.as_of is not None else None,
        "values": dict(result.values),
        "observation_count": result.observation_count,
        "numeric_policy": result.numeric_policy,
        "evidence_id": result.evidence_id,
    }


class SnapshotService:
    """Coordinate explicit plugin import and offline snapshot reads."""

    def __init__(
        self,
        registry: PluginRegistry,
        repository: SnapshotRepository,
        configuration: SourceConfiguration,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._configuration = configuration

    def sources(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "sources": [
                {
                    "name": item.name,
                    "distribution": item.distribution,
                    "version": item.version,
                    "entry_point": item.value,
                    "loaded": False,
                }
                for item in self._registry.installed()
            ],
        }

    def import_bundle(self, path: Path, plugin: str) -> dict[str, Any]:
        importer = self._registry.load_daily_bars(plugin)
        imported = importer.import_bundle(path)
        stored = self._repository.put_daily_bars(imported)
        return {
            "schema_version": "1.0.0",
            "status": "imported",
            "object_id": stored.object_id,
            "source_profile": imported.source_profile,
            "instrument": f"{imported.instrument.mic}:{imported.instrument.symbol}",
            "kind": "daily_bars",
            "observations": len(imported.bars),
        }

    def doctor_source(self, profile_name: str) -> dict[str, Any]:
        profile = self._configuration.source_profile(profile_name)
        source = self._registry.load_fetcher(profile.daily_bars_plugin)
        result = source.doctor(
            DailyBarSourceConfiguration(profile.currency, profile.timezone, profile.settings)
        )
        return {
            "schema_version": "1.0.0",
            "source_profile": profile.name,
            "plugin": profile.daily_bars_plugin,
            "ready": result.ready,
            "code": result.code,
            "message": result.message,
            "recovery": result.recovery,
        }

    def fetch(
        self,
        profile_name: str,
        instrument_key: str,
        start: date,
        end: date,
        adjustment: str,
    ) -> dict[str, Any]:
        profile = self._configuration.source_profile(profile_name)
        source = self._registry.load_fetcher(profile.daily_bars_plugin)
        mic, separator, symbol = instrument_key.partition(":")
        if not separator:
            raise ValueError("instrument must use MIC:SYMBOL form")
        instrument = Instrument.create(
            symbol=symbol,
            mic=mic,
            currency=profile.currency,
            exchange_timezone=profile.timezone,
        )
        request = DailyBarFetchRequest(
            source_profile=profile.name,
            instrument=instrument,
            start=start,
            end=end,
            adjustment=Adjustment(adjustment),
            settings=profile.settings,
        )
        imported = source.fetch(request)
        if imported.fetch_request != request:
            raise ValueError("source fetch result must preserve the exact request")
        stored = self._repository.put_daily_bars(imported)
        return {
            "schema_version": "1.0.0",
            "status": "fetched",
            "object_id": stored.object_id,
            "source_profile": profile.name,
            "instrument": instrument_key,
            "kind": "daily_bars",
            "observations": len(imported.bars),
            "instrument_profile": imported.instrument_profile is not None,
        }

    def snapshots(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "snapshots": [item.manifest for item in self._repository.list()],
        }

    def _resolve(self, profile: str, instrument: str) -> StoredSnapshotInfo:
        try:
            return self._repository.resolve(profile, instrument)
        except LookupError as original:
            try:
                source_profile = self._configuration.source_profile(profile)
            except LookupError:
                raise original from None
            if self._registry.can_fetch(source_profile.daily_bars_plugin):
                command = f"marketsieve source fetch {profile} {instrument} --start DATE --end DATE"
            else:
                command = "marketsieve source import PATH"
            raise LookupError(f"snapshot not found; run '{command}'") from None

    def show(self, object_id: str) -> dict[str, Any]:
        return {"schema_version": "1.0.0", "snapshot": self._repository.show(object_id).manifest}

    def verify(self, object_id: str) -> dict[str, Any]:
        stored = self._repository.verify(object_id)
        return {"schema_version": "1.0.0", "status": "verified", "object_id": stored.object_id}

    def inspect(self, instrument: str, profile: str) -> dict[str, Any]:
        stored = self._resolve(profile, instrument)
        normalized = self._repository.normalized(stored.object_id)
        daily_bars = self._repository.daily_bars(stored.object_id)
        bars = normalized["bars"]
        latest = bars[-1]
        evidence = hashlib.sha256(
            json.dumps(
                {"object_id": stored.object_id, "section": "price", "value": latest},
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        unavailable: dict[str, Any] = {
            "status": "unavailable",
            "completeness": "0",
            "values": {},
            "warnings": [],
            "missing_reasons": ["not_present_in_snapshot"],
            "provenance": [],
            "evidence_id": None,
        }
        indicators = tuple(calculate(spec, daily_bars) for spec in DEFAULT_INDICATORS)
        available_count = sum(result.status is IndicatorStatus.OK for result in indicators)
        completeness = (
            "0"
            if available_count == 0
            else "1"
            if available_count == len(indicators)
            else f"{available_count / len(indicators):.6f}".rstrip("0")
        )
        technical_evidence = hashlib.sha256(
            json.dumps(
                [result.evidence_id for result in indicators],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        technical = {
            "status": "available" if available_count == len(indicators) else "partial",
            "as_of": latest["available_at"],
            "completeness": completeness,
            "values": {result.name.value: indicator_document(result) for result in indicators},
            "warnings": [],
            "missing_reasons": (
                [] if available_count == len(indicators) else ["insufficient_history"]
            ),
            "provenance": [latest["provenance"]],
            "evidence_id": technical_evidence,
        }
        instrument_document = dict(normalized["instrument"])
        if "instrument_profile" in normalized:
            instrument_document["profile"] = normalized["instrument_profile"]
        return {
            "schema_version": "1.0.0",
            "instrument": instrument_document,
            "source_profile": profile,
            "snapshot_id": stored.object_id,
            "sections": {
                "price": {
                    "status": "available",
                    "as_of": latest["available_at"],
                    "completeness": "1",
                    "values": {
                        "trading_date": latest["trading_date"],
                        "open": latest["open"],
                        "high": latest["high"],
                        "low": latest["low"],
                        "close": latest["close"],
                        "volume": latest["volume"],
                        "adjustment": normalized["adjustment"],
                    },
                    "warnings": [],
                    "missing_reasons": [],
                    "provenance": [latest["provenance"]],
                    "evidence_id": evidence,
                },
                "technical": technical,
                **{
                    section: unavailable
                    for section in (
                        "financial",
                        "valuation",
                        "risk",
                        "events",
                        "data_quality",
                    )
                },
            },
        }

    def analyze(
        self,
        instrument: str,
        profile: str,
        name: IndicatorName | str,
        **parameters: int,
    ) -> dict[str, Any]:
        stored = self._resolve(profile, instrument)
        result = calculate(
            IndicatorSpec.create(name, **parameters),
            self._repository.daily_bars(stored.object_id),
        )
        return {
            "schema_version": "1.0.0",
            "instrument": instrument,
            "source_profile": profile,
            "snapshot_id": stored.object_id,
            "indicator": indicator_document(result),
        }
