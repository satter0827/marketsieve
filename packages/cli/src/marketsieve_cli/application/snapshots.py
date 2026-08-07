"""Offline source import and snapshot query use cases."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Protocol

from marketsieve.analysis.indicators import CONTEXT, canonical_decimal
from marketsieve.data.daily import Adjustment, DailyBar
from marketsieve.domain import Instrument
from marketsieve.financial import (
    FinancialObservation,
    FinancialTrendReport,
    analyze_financial_history,
)
from marketsieve_extension_api import (
    DailyBarBundleImporter,
    DailyBarFetcher,
    DailyBarFetchRequest,
    DailyBarSourceConfiguration,
    EventFetcher,
    FactFetchRequest,
    FinancialFetcher,
    ImportedDailyBars,
    ImportedEvents,
    ImportedFinancials,
)
from marketsieve_extension_api import (
    SourceConfiguration as FactSourceConfiguration,
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

    @property
    def data_kinds(self) -> tuple[str, ...]: ...


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

    def load_financial_fetcher(self, name: str) -> FinancialFetcher: ...

    def load_event_fetcher(self, name: str) -> EventFetcher: ...


class SourceBindingInfo(Protocol):
    @property
    def plugin(self) -> str: ...

    @property
    def settings(self) -> dict[str, str]: ...


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

    def binding(self, kind: str) -> SourceBindingInfo: ...


class SourceConfiguration(Protocol):
    def source_profile(self, name: str) -> SourceProfileInfo: ...


class SnapshotRepository(Protocol):
    def put_daily_bars(self, imported: ImportedDailyBars) -> StoredSnapshotInfo: ...

    def list(self) -> tuple[StoredSnapshotInfo, ...]: ...

    def show(self, object_id: str) -> StoredSnapshotInfo: ...

    def verify(self, object_id: str) -> StoredSnapshotInfo: ...

    def put_financials(self, imported: ImportedFinancials) -> StoredSnapshotInfo: ...

    def put_events(self, imported: ImportedEvents) -> StoredSnapshotInfo: ...

    def resolve(
        self, profile: str, instrument: str, kind: str = "daily_bars"
    ) -> StoredSnapshotInfo: ...

    def normalized(self, object_id: str) -> dict[str, Any]: ...

    def daily_bars(self, object_id: str) -> tuple[DailyBar, ...]: ...


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
                    "data_kinds": list(item.data_kinds),
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

    def doctor_source(self, profile_name: str, kind: str = "daily_bars") -> dict[str, Any]:
        if kind not in {"daily_bars", "financials", "events"}:
            raise ValueError("source kind is not supported")
        profile = self._configuration.source_profile(profile_name)
        binding = profile.binding(kind)
        if kind == "daily_bars":
            source = self._registry.load_fetcher(binding.plugin)
            result = source.doctor(
                DailyBarSourceConfiguration(profile.currency, profile.timezone, binding.settings)
            )
        elif kind == "financials":
            financial_source = self._registry.load_financial_fetcher(binding.plugin)
            result = financial_source.doctor_financials(
                FactSourceConfiguration(profile.currency, profile.timezone, binding.settings)
            )
        else:
            event_source = self._registry.load_event_fetcher(binding.plugin)
            result = event_source.doctor_events(
                FactSourceConfiguration(profile.currency, profile.timezone, binding.settings)
            )
        return {
            "schema_version": "1.0.0",
            "source_profile": profile.name,
            "plugin": binding.plugin,
            "kind": kind,
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
        kind: str = "daily_bars",
    ) -> dict[str, Any]:
        if kind not in {"daily_bars", "financials", "events"}:
            raise ValueError("source kind is not supported")
        profile = self._configuration.source_profile(profile_name)
        binding = profile.binding(kind)
        mic, separator, symbol = instrument_key.partition(":")
        if not separator:
            raise ValueError("instrument must use MIC:SYMBOL form")
        instrument = Instrument.create(
            symbol=symbol,
            mic=mic,
            currency=profile.currency,
            exchange_timezone=profile.timezone,
        )
        instrument_profile = False
        if kind == "daily_bars":
            source = self._registry.load_fetcher(binding.plugin)
            request = DailyBarFetchRequest(
                source_profile=profile.name,
                instrument=instrument,
                start=start,
                end=end,
                adjustment=Adjustment(adjustment),
                settings=binding.settings,
            )
            imported = source.fetch(request)
            if imported.fetch_request != request:
                raise ValueError("source fetch result must preserve the exact request")
            stored = self._repository.put_daily_bars(imported)
            observations = len(imported.bars)
            instrument_profile = imported.instrument_profile is not None
        else:
            fact_request = FactFetchRequest(profile.name, instrument, start, end, binding.settings)
            if kind == "financials":
                financial_source = self._registry.load_financial_fetcher(binding.plugin)
                financials = financial_source.fetch_financials(fact_request)
                if financials.request != fact_request:
                    raise ValueError("source fetch result must preserve the exact request")
                stored = self._repository.put_financials(financials)
                observations = len(financials.facts)
            else:
                event_source = self._registry.load_event_fetcher(binding.plugin)
                events = event_source.fetch_events(fact_request)
                if events.request != fact_request:
                    raise ValueError("source fetch result must preserve the exact request")
                stored = self._repository.put_events(events)
                observations = len(events.events)
        document = {
            "schema_version": "1.0.0",
            "status": "fetched",
            "object_id": stored.object_id,
            "source_profile": profile.name,
            "instrument": instrument_key,
            "kind": kind,
            "observations": observations,
        }
        if kind == "daily_bars":
            document["instrument_profile"] = instrument_profile
        return document

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

    def bars(self, profile: str, instrument: str) -> tuple[DailyBar, ...]:
        """Read verified daily bars for a routine after explicit acquisition."""

        stored = self._repository.resolve(profile, instrument)
        self._repository.verify(stored.object_id)
        return self._repository.daily_bars(stored.object_id)

    def financial_trend(
        self, profile: str, instrument: str, as_of: datetime
    ) -> FinancialTrendReport:
        """Rebuild a knowledge-time-correct financial trend from a verified snapshot."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a UTC offset")
        stored = self._repository.resolve(profile, instrument, "financials")
        self._repository.verify(stored.object_id)
        document = self._repository.normalized(stored.object_id)
        observations = tuple(
            FinancialObservation(
                item["concept"],
                Decimal(item["value"]),
                item["scale"],
                item["period"],
                date.fromisoformat(item["fiscal_period_start"])
                if item["fiscal_period_start"]
                else None,
                date.fromisoformat(item["fiscal_period_end"]),
                item["accounting_standard"],
                item["consolidation"],
                item["revision"],
                item["currency"],
                datetime.fromisoformat(item["available_at"]),
                f"{stored.object_id}:fact:{index}",
            )
            for index, item in enumerate(document["facts"])
        )
        return analyze_financial_history(observations, as_of)

    def next_earnings_date(self, profile: str, instrument: str, as_of: datetime) -> date | None:
        """Return the nearest known future earnings event from a verified snapshot."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a UTC offset")
        stored = self._repository.resolve(profile, instrument, "events")
        self._repository.verify(stored.object_id)
        document = self._repository.normalized(stored.object_id)
        local_date = as_of.astimezone(
            Instrument.create(
                symbol=document["instrument"]["symbol"],
                mic=document["instrument"]["mic"],
                currency=document["instrument"]["currency"],
                exchange_timezone=document["instrument"]["timezone"],
            ).exchange_timezone
        ).date()
        candidates = tuple(
            date.fromisoformat(item["effective_date"])
            for item in document["events"]
            if item["type"] == "earnings"
            and datetime.fromisoformat(item["available_at"]).astimezone(UTC)
            <= as_of.astimezone(UTC)
            and date.fromisoformat(item["effective_date"]) >= local_date
        )
        return min(candidates, default=None)

    def valuation_history(
        self, profile: str, instrument: str, as_of: datetime
    ) -> tuple[tuple[str, str], ...]:
        """Compare current valuation facts with explicitly acquired company history."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a UTC offset")
        observations: dict[str, dict[datetime, tuple[str, Decimal]]] = {}
        for stored in self._repository.list():
            manifest = stored.manifest
            identity = manifest.get("instrument", {})
            source = manifest.get("source", {})
            if (
                manifest.get("kind") != "daily_bars"
                or source.get("profile") != profile
                or f"{identity.get('mic')}:{identity.get('symbol')}" != instrument
            ):
                continue
            self._repository.verify(stored.object_id)
            document = self._repository.normalized(stored.object_id)
            raw_profile = document.get("instrument_profile")
            if not isinstance(raw_profile, dict):
                continue
            available_at = datetime.fromisoformat(str(raw_profile["available_at"]))
            if available_at.astimezone(UTC) > as_of.astimezone(UTC):
                continue
            attributes = raw_profile.get("attributes", {})
            if not isinstance(attributes, dict):
                continue
            for name, provider_name in (
                ("dividend_yield", "dividend_yield"),
                ("pbr", "price_to_book"),
                ("psr", "price_to_sales_ttm"),
                ("trailing_per", "trailing_per"),
            ):
                try:
                    value = Decimal(str(attributes[provider_name]))
                except (KeyError, InvalidOperation, TypeError, ValueError):
                    continue
                if value.is_finite():
                    prior = observations.setdefault(name, {}).get(available_at)
                    if prior is not None and prior[1] != value:
                        raise ValueError("valuation history contains conflicting observations")
                    if prior is None or stored.object_id < prior[0]:
                        observations[name][available_at] = (stored.object_id, value)
        values: list[tuple[str, str]] = []
        for name, items in sorted(observations.items()):
            ordered = sorted(
                ((available_at, *item) for available_at, item in items.items()),
                key=lambda item: (item[0], item[1]),
            )
            current = ordered[-1][2]
            history = sorted(item[2] for item in ordered)
            values.append((f"{name}.current", canonical_decimal(current)))
            values.append((f"{name}.history_count", str(len(history))))
            if len(history) >= 2:
                values.extend(
                    (
                        (f"{name}.history_max", canonical_decimal(history[-1])),
                        (f"{name}.history_median", canonical_decimal(_median(history))),
                        (f"{name}.history_min", canonical_decimal(history[0])),
                    )
                )
        return tuple(sorted(values))

    def fundamental_changes(
        self, profile: str, instrument: str, as_of: datetime
    ) -> tuple[tuple[str, str], ...]:
        """Describe the latest known filing and any explicit amendment."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a UTC offset")
        stored = self._repository.resolve(profile, instrument, "financials")
        self._repository.verify(stored.object_id)
        document = self._repository.normalized(stored.object_id)
        filings = sorted(
            (
                item
                for item in document["filings"]
                if datetime.fromisoformat(item["published_at"]).astimezone(UTC)
                <= as_of.astimezone(UTC)
            ),
            key=lambda item: (item["published_at"], item["filing_id"]),
        )
        if not filings:
            return ()
        latest = filings[-1]
        values = {
            "change_type": "amendment" if latest["amends_filing_id"] else "new_filing",
            "latest_filing_id": latest["filing_id"],
            "latest_filing_published_at": latest["published_at"],
            "latest_filing_type": latest["document_type"],
        }
        if latest["fiscal_period_end"]:
            values["latest_period_end"] = latest["fiscal_period_end"]
        amended_id = latest["amends_filing_id"]
        if amended_id:
            values["amends_filing_id"] = amended_id
            by_filing: dict[str, dict[str, Decimal]] = {}
            for fact in document["facts"]:
                if fact["filing_id"] not in {latest["filing_id"], amended_id}:
                    continue
                if datetime.fromisoformat(fact["available_at"]).astimezone(UTC) > as_of.astimezone(
                    UTC
                ):
                    continue
                by_filing.setdefault(fact["filing_id"], {})[fact["concept"]] = Decimal(
                    fact["value"]
                ) * Decimal(fact["scale"])
            current = by_filing.get(latest["filing_id"], {})
            previous = by_filing.get(amended_id, {})
            changed = sorted(
                concept
                for concept in current.keys() & previous.keys()
                if current[concept] != previous[concept]
            )
            if changed:
                values["restated_concepts"] = ",".join(changed)
        return tuple(sorted(values.items()))


def _median(values: list[Decimal]) -> Decimal:
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    with localcontext(CONTEXT):
        return +(values[middle - 1] + values[middle]) / Decimal(2)
