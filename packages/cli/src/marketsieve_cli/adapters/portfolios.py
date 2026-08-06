"""Strict canonical portfolio CSV import and content-addressed storage."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from marketsieve import Holding, PortfolioSnapshot, WatchItem
from marketsieve.domain import Instrument, InstrumentType
from marketsieve_extension_api import ImportedPortfolioSnapshot

PORTFOLIO_SCHEMA = "portfolio-result/v2"
CSV_HEADERS = (
    "kind",
    "mic",
    "symbol",
    "currency",
    "timezone",
    "quantity",
    "average_acquisition_price",
    "account_type",
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _instrument_document(instrument: Instrument) -> dict[str, str]:
    return {
        "mic": instrument.mic,
        "symbol": instrument.symbol,
        "currency": instrument.currency,
        "timezone": instrument.exchange_timezone.key,
        "type": instrument.instrument_type.value,
    }


def portfolio_document(
    imported: ImportedPortfolioSnapshot, *, object_id: str | None = None
) -> dict[str, object]:
    snapshot = imported.snapshot
    document: dict[str, object] = {
        "schema": PORTFOLIO_SCHEMA,
        "as_of": snapshot.as_of.isoformat(),
        "source": snapshot.source,
        "source_name": imported.source_name,
        "source_version": imported.source_version,
        "dataset": imported.dataset,
        "source_hash": imported.source_hash,
        "diagnostics": list(imported.diagnostics),
        "holdings": [
            {
                "instrument": _instrument_document(item.instrument),
                "quantity": _decimal_text(item.quantity),
                "average_acquisition_price": _decimal_text(item.average_acquisition_price),
                "account_type": item.account_type,
            }
            for item in snapshot.holdings
        ],
        "watch_items": [
            {"instrument": _instrument_document(item.instrument)} for item in snapshot.watch_items
        ],
    }
    return {"object_id": object_id, **document} if object_id is not None else document


def import_canonical_csv(payload: bytes, *, as_of: datetime) -> ImportedPortfolioSnapshot:
    """Normalize the documented broker-neutral CSV without retaining its bytes."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("portfolio as_of must include a UTC offset")
    if len(payload) > 4 * 1024 * 1024:
        raise ValueError("portfolio CSV exceeds the 4 MiB safety bound")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("portfolio CSV must use UTF-8") from error
    reader = csv.DictReader(io.StringIO(text), strict=True)
    if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_HEADERS:
        raise ValueError("portfolio CSV headers do not match the canonical format")
    holdings: list[Holding] = []
    watch_items: list[WatchItem] = []
    try:
        rows = list(reader)
    except csv.Error as error:
        raise ValueError("portfolio CSV is malformed") from error
    if not rows:
        raise ValueError("portfolio CSV must contain at least one row")
    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("portfolio CSV row width is invalid")
        instrument = _instrument(row)
        kind = row["kind"].strip()
        if kind == "holding":
            try:
                quantity = Decimal(row["quantity"].strip())
                price = Decimal(row["average_acquisition_price"].strip())
            except InvalidOperation as error:
                raise ValueError("portfolio holding amount is invalid") from error
            holdings.append(Holding(instrument, quantity, price, row["account_type"].strip()))
        elif kind == "watch":
            if any(
                row[name].strip()
                for name in ("quantity", "average_acquisition_price", "account_type")
            ):
                raise ValueError("portfolio watch rows must leave holding fields empty")
            watch_items.append(WatchItem(instrument))
        else:
            raise ValueError("portfolio kind must be holding or watch")
    holdings.sort(key=lambda item: (item.instrument.mic, item.instrument.symbol))
    watch_items.sort(key=lambda item: (item.instrument.mic, item.instrument.symbol))
    return ImportedPortfolioSnapshot(
        snapshot=PortfolioSnapshot(as_of, tuple(holdings), tuple(watch_items), "canonical_csv"),
        source_name="canonical",
        source_version="1.0.0",
        dataset="canonical-portfolio/v1",
        source_hash=hashlib.sha256(payload).hexdigest(),
    )


def _instrument(row: dict[str, str]) -> Instrument:
    try:
        timezone = ZoneInfo(row["timezone"].strip())
    except ZoneInfoNotFoundError as error:
        raise ValueError("portfolio timezone is unknown") from error
    return Instrument(
        row["symbol"].strip(),
        row["mic"].strip(),
        row["currency"].strip(),
        timezone,
        InstrumentType.EQUITY,
    )


class PortfolioStore:
    """Persist immutable normalized portfolios and one replaceable latest reference."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._objects = root / "objects"
        self._refs = root / "refs"

    def put(self, imported: ImportedPortfolioSnapshot) -> str:
        document = portfolio_document(imported)
        payload = _json_bytes(document)
        object_id = hashlib.sha256(payload).hexdigest()
        self._ensure_directory(self._objects)
        destination = self._objects / f"{object_id}.json"
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes() != payload:
                raise ValueError("portfolio object conflicts with immutable content")
        else:
            self._atomic_write(destination, payload)
        self._ensure_directory(self._refs)
        self._atomic_write(self._refs / "latest.json", _json_bytes({"object_id": object_id}))
        return object_id

    def latest(self) -> tuple[str, ImportedPortfolioSnapshot]:
        reference = self._refs / "latest.json"
        if reference.is_symlink() or not reference.is_file():
            raise LookupError("portfolio not found; run 'marketsieve portfolio import'")
        try:
            value = json.loads(reference.read_bytes())
            object_id = value["object_id"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("portfolio latest reference is invalid") from error
        return self.show(object_id)

    def latest_snapshot(self) -> PortfolioSnapshot:
        """Return only the normalized value needed by application services."""

        return self.latest()[1].snapshot

    def show(self, object_id: str) -> tuple[str, ImportedPortfolioSnapshot]:
        if len(object_id) != 64 or any(
            character not in "0123456789abcdef" for character in object_id
        ):
            raise ValueError("portfolio object ID must be a lowercase SHA-256 digest")
        path = self._objects / f"{object_id}.json"
        if path.is_symlink() or not path.is_file():
            raise LookupError("portfolio object not found")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != object_id:
            raise ValueError("portfolio object ID does not match its content")
        try:
            value = json.loads(payload)
            imported = _parse_imported(value)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("portfolio object is invalid") from error
        if _json_bytes(portfolio_document(imported)) != payload:
            raise ValueError("portfolio object is not canonical")
        return object_id, imported

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        if path.exists() and (path.is_symlink() or not path.is_dir()):
            raise ValueError("portfolio store directory must be a real directory")
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write(destination: Path, payload: bytes) -> None:
        if destination.is_symlink():
            raise ValueError("portfolio destination must not be a symbolic link")
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        try:
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def _parse_imported(value: dict[str, Any]) -> ImportedPortfolioSnapshot:
    if value.get("schema") != PORTFOLIO_SCHEMA or set(value) != {
        "schema",
        "as_of",
        "source",
        "source_name",
        "source_version",
        "dataset",
        "source_hash",
        "diagnostics",
        "holdings",
        "watch_items",
    }:
        raise ValueError("portfolio schema is unsupported")
    holdings = tuple(
        Holding(
            _parse_instrument(item["instrument"]),
            Decimal(item["quantity"]),
            Decimal(item["average_acquisition_price"]),
            item["account_type"],
        )
        for item in value["holdings"]
    )
    watch_items = tuple(
        WatchItem(_parse_instrument(item["instrument"])) for item in value["watch_items"]
    )
    snapshot = PortfolioSnapshot(
        datetime.fromisoformat(value["as_of"]), holdings, watch_items, value["source"]
    )
    return ImportedPortfolioSnapshot(
        snapshot=snapshot,
        source_name=value["source_name"],
        source_version=value["source_version"],
        dataset=value["dataset"],
        source_hash=value["source_hash"],
        diagnostics=tuple(value["diagnostics"]),
    )


def _parse_instrument(value: dict[str, str]) -> Instrument:
    return Instrument(
        value["symbol"],
        value["mic"],
        value["currency"],
        ZoneInfo(value["timezone"]),
        InstrumentType(value["type"]),
    )
