"""Independent content-addressed watchlist history."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from marketsieve import PortfolioSnapshot, WatchItem
from marketsieve.domain import Instrument, InstrumentType

WATCHLIST_SCHEMA = "watchlist-result/v1"
MIC_DEFINITIONS = {
    "XTKS": ("JPY", "Asia/Tokyo"),
    "XNAS": ("USD", "America/New_York"),
    "XNYS": ("USD", "America/New_York"),
}


class PortfolioWatchlistReader:
    """Compose the latest holdings and watchlist only at analysis time."""

    def __init__(self, portfolios: Any, watchlists: WatchlistStore) -> None:
        self._portfolios = portfolios
        self._watchlists = watchlists

    def latest_snapshot(self) -> PortfolioSnapshot:
        portfolio = self._portfolios.latest_snapshot()
        holding_ids = {(item.instrument.mic, item.instrument.symbol) for item in portfolio.holdings}
        if self._watchlists.exists():
            watchlist_as_of, watch_items = self._watchlists.current()
        else:
            watchlist_as_of, watch_items = portfolio.as_of, ()
        watches = tuple(
            item
            for item in watch_items
            if (item.instrument.mic, item.instrument.symbol) not in holding_ids
        )
        return PortfolioSnapshot(
            max(portfolio.as_of, watchlist_as_of),
            portfolio.holdings,
            watches,
            f"{portfolio.source}+watchlist",
        )


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def parse_instrument_key(value: str) -> Instrument:
    """Parse one supported MIC:SYMBOL identifier without guessing a market."""

    mic, separator, symbol = value.partition(":")
    if not separator or not symbol or symbol != symbol.strip() or mic not in MIC_DEFINITIONS:
        raise ValueError("instrument must use supported MIC:SYMBOL form (XTKS, XNAS, or XNYS)")
    currency, timezone = MIC_DEFINITIONS[mic]
    return Instrument.create(
        symbol=symbol,
        mic=mic,
        currency=currency,
        exchange_timezone=timezone,
        instrument_type=InstrumentType.EQUITY,
    )


def instrument_key(instrument: Instrument) -> str:
    return f"{instrument.mic}:{instrument.symbol}"


def _instrument_document(instrument: Instrument) -> dict[str, str]:
    return {
        "mic": instrument.mic,
        "symbol": instrument.symbol,
        "currency": instrument.currency,
        "timezone": instrument.exchange_timezone.key,
        "type": instrument.instrument_type.value,
    }


class WatchlistStore:
    """Persist explicit human watchlist changes and their provenance."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._objects = root / "objects"
        self._refs = root / "refs"

    def add(
        self,
        instrument: Instrument,
        *,
        as_of: datetime,
        screen_report_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_as_of(as_of)
        current = self._latest_or_empty()
        items = list(cast(list[dict[str, Any]], current["items"]))
        key = instrument_key(instrument)
        existing = next((item for item in items if item["key"] == key), None)
        if existing is not None:
            if screen_report_id is None or existing["source_screen_report_id"] == screen_report_id:
                return current
            items = [
                {**item, "source_screen_report_id": screen_report_id}
                if item["key"] == key
                else item
                for item in items
            ]
            return self._put(
                as_of,
                current["watchlist_id"],
                items,
                "add_provenance",
                key,
            )
        items.append(
            {
                "key": key,
                "instrument": _instrument_document(instrument),
                "source_screen_report_id": screen_report_id,
            }
        )
        items.sort(key=lambda item: item["key"])
        return self._put(as_of, current.get("watchlist_id"), items, "add", key)

    def remove(self, instrument: Instrument, *, as_of: datetime) -> dict[str, Any]:
        self._validate_as_of(as_of)
        current = self.latest()
        key = instrument_key(instrument)
        items = [item for item in current["items"] if item["key"] != key]
        if len(items) == len(current["items"]):
            raise LookupError(f"watchlist instrument {key} does not exist")
        return self._put(as_of, current["watchlist_id"], items, "remove", key)

    def latest(self) -> dict[str, Any]:
        reference = self._refs / "latest.json"
        if not reference.exists() and not reference.is_symlink():
            raise LookupError("watchlist does not exist")
        if reference.is_symlink() or not reference.is_file():
            raise ValueError("watchlist latest reference must be a real file")
        try:
            value = json.loads(reference.read_bytes())
            object_id = value["watchlist_id"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("watchlist latest reference is invalid") from error
        if set(value) != {"watchlist_id"} or _json_bytes(value) != reference.read_bytes():
            raise ValueError("watchlist latest reference is not canonical")
        return self.show(object_id)

    def show(self, watchlist_id: str) -> dict[str, Any]:
        self._validate_id(watchlist_id)
        path = self._objects / f"{watchlist_id}.json"
        if path.is_symlink() or not path.is_file():
            raise LookupError("watchlist object does not exist")
        payload = path.read_bytes()
        try:
            document = cast(dict[str, Any], json.loads(payload))
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("watchlist object is invalid") from error
        self._validate_document(document)
        semantic = {key: value for key, value in document.items() if key != "watchlist_id"}
        if hashlib.sha256(_json_bytes(semantic)).hexdigest() != watchlist_id:
            raise ValueError("watchlist ID does not match semantic content")
        if _json_bytes(document) != payload:
            raise ValueError("watchlist object is not canonical")
        return document

    def history(self) -> tuple[dict[str, Any], ...]:
        if not self.exists():
            return ()
        current = self.latest()
        history: list[dict[str, Any]] = []
        seen: set[str] = set()
        while True:
            object_id = current["watchlist_id"]
            if object_id in seen:
                raise ValueError("watchlist history contains a cycle")
            seen.add(object_id)
            history.append(current)
            previous = current["previous_watchlist_id"]
            if previous is None:
                break
            current = self.show(previous)
        return tuple(reversed(history))

    def watch_items(self) -> tuple[WatchItem, ...]:
        if not self.exists():
            return ()
        _, items = self.current()
        return items

    def exists(self) -> bool:
        """Return false only when no latest reference has ever been created."""

        reference = self._refs / "latest.json"
        if not reference.exists() and not reference.is_symlink():
            return False
        if reference.is_symlink() or not reference.is_file():
            raise ValueError("watchlist latest reference must be a real file")
        return True

    def current(self) -> tuple[datetime, tuple[WatchItem, ...]]:
        """Return one verified revision time and its items from the same immutable object."""

        document = self.latest()
        return (
            datetime.fromisoformat(document["as_of"]),
            tuple(
                WatchItem(self._parse_instrument(item["instrument"])) for item in document["items"]
            ),
        )

    def _latest_or_empty(self) -> dict[str, Any]:
        if self.exists():
            return self.latest()
        return {
            "watchlist_id": None,
            "schema": WATCHLIST_SCHEMA,
            "as_of": None,
            "previous_watchlist_id": None,
            "change": None,
            "items": [],
        }

    def _put(
        self,
        as_of: datetime,
        previous_id: str | None,
        items: list[dict[str, Any]],
        operation: str,
        instrument: str,
    ) -> dict[str, Any]:
        if previous_id is not None:
            previous_as_of = datetime.fromisoformat(self.show(previous_id)["as_of"])
            if as_of < previous_as_of:
                raise ValueError("watchlist revision as_of must not predate its predecessor")
        semantic = {
            "schema": WATCHLIST_SCHEMA,
            "as_of": as_of.isoformat(),
            "previous_watchlist_id": previous_id,
            "change": {"operation": operation, "instrument": instrument},
            "items": items,
        }
        object_id = hashlib.sha256(_json_bytes(semantic)).hexdigest()
        document = {"watchlist_id": object_id, **semantic}
        payload = _json_bytes(document)
        self._ensure_directory(self._objects)
        destination = self._objects / f"{object_id}.json"
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes() != payload:
                raise ValueError("watchlist object conflicts with immutable content")
        else:
            self._atomic_write(destination, payload)
        self._ensure_directory(self._refs)
        self._atomic_write(self._refs / "latest.json", _json_bytes({"watchlist_id": object_id}))
        return document

    @staticmethod
    def _parse_instrument(value: dict[str, Any]) -> Instrument:
        if set(value) != {"mic", "symbol", "currency", "timezone", "type"}:
            raise ValueError("watchlist instrument is invalid")
        instrument = parse_instrument_key(f"{value['mic']}:{value['symbol']}")
        if _instrument_document(instrument) != value:
            raise ValueError("watchlist instrument metadata is invalid")
        return instrument

    def _validate_document(self, document: dict[str, Any]) -> None:
        if (
            set(document)
            != {
                "watchlist_id",
                "schema",
                "as_of",
                "previous_watchlist_id",
                "change",
                "items",
            }
            or document.get("schema") != WATCHLIST_SCHEMA
        ):
            raise ValueError("watchlist schema is unsupported")
        self._validate_id(document["watchlist_id"])
        self._validate_as_of(datetime.fromisoformat(document["as_of"]))
        previous = document["previous_watchlist_id"]
        if previous is not None:
            self._validate_id(previous)
        change = document["change"]
        if not isinstance(change, dict) or set(change) != {"operation", "instrument"}:
            raise ValueError("watchlist change is invalid")
        if change["operation"] not in {"add", "remove", "add_provenance"}:
            raise ValueError("watchlist change operation is invalid")
        items = document["items"]
        if not isinstance(items, list):
            raise ValueError("watchlist items are invalid")
        keys: list[str] = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                "key",
                "instrument",
                "source_screen_report_id",
            }:
                raise ValueError("watchlist item is invalid")
            instrument = self._parse_instrument(item["instrument"])
            if item["key"] != instrument_key(instrument):
                raise ValueError("watchlist item key is invalid")
            source = item["source_screen_report_id"]
            if source is not None:
                self._validate_id(source)
            keys.append(item["key"])
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("watchlist items must be unique and sorted")

    def _ensure_directory(self, path: Path) -> None:
        current = self._root
        directories = [self._root]
        for part in path.relative_to(self._root).parts:
            current /= part
            directories.append(current)
        if any(candidate.is_symlink() for candidate in directories):
            raise ValueError("watchlist storage path must be a real directory")
        path.mkdir(parents=True, exist_ok=True)
        if any(not candidate.is_dir() for candidate in directories):
            raise ValueError("watchlist storage path must be a real directory")

    @staticmethod
    def _atomic_write(destination: Path, payload: bytes) -> None:
        if destination.is_symlink():
            raise ValueError("watchlist destination must not be a symbolic link")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".pending-", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_as_of(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("watchlist as_of must include a UTC offset")

    @staticmethod
    def _validate_id(value: object) -> None:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("watchlist ID must be a lowercase SHA-256 digest")
