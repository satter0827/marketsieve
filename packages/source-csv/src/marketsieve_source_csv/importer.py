"""Strict normalization of a local CSV dataset bundle."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from marketsieve.data.daily import Adjustment, DailyBar, Provenance
from marketsieve.domain import Instrument
from marketsieve_extension_api import AvailabilityBasis, ImportedDailyBars

MANIFEST_SCHEMA = "marketsieve-csv-daily-bars/v1"
CSV_FIELDS = ("trading_date", "open", "high", "low", "close", "volume", "published_at")


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO 8601 timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a UTC offset")
    return parsed


def _text(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest field {field} must be a non-empty string")
    return value


def _bundle_hash(manifest_bytes: bytes, csv_bytes: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(len(manifest_bytes).to_bytes(8, "big"))
    digest.update(manifest_bytes)
    digest.update(len(csv_bytes).to_bytes(8, "big"))
    digest.update(csv_bytes)
    return digest.hexdigest()


class CsvDailyBarImporter:
    """Import the v1 bundle format without guessing missing market metadata."""

    def import_bundle(self, path: Path) -> ImportedDailyBars:
        bundle = path.resolve()
        if not bundle.is_dir() or path.is_symlink():
            raise ValueError("CSV bundle path must be a real directory")
        manifest_path = bundle / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("CSV bundle requires a regular manifest.json")
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("manifest.json must contain valid UTF-8 JSON") from error
        if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
            raise ValueError(f"manifest schema must be {MANIFEST_SCHEMA}")
        instrument_data = manifest.get("instrument")
        dataset_data = manifest.get("dataset")
        if not isinstance(instrument_data, dict) or not isinstance(dataset_data, dict):
            raise ValueError("manifest requires instrument and dataset objects")
        instrument = Instrument.create(
            symbol=_text(instrument_data, "symbol"),
            mic=_text(instrument_data, "mic"),
            currency=_text(instrument_data, "currency"),
            exchange_timezone=_text(instrument_data, "timezone"),
        )
        adjustment = Adjustment(_text(dataset_data, "adjustment"))
        basis = AvailabilityBasis(_text(dataset_data, "availability_basis"))
        retrieved_at = _aware_datetime(manifest.get("retrieved_at"), "retrieved_at")
        filename = _text(dataset_data, "file")
        if Path(filename).name != filename:
            raise ValueError("dataset file must be a filename without path components")
        data_path = bundle / filename
        if not data_path.is_file() or data_path.is_symlink():
            raise ValueError("dataset file must be a regular file inside the bundle")
        csv_bytes = data_path.read_bytes()
        try:
            rows = tuple(csv.DictReader(csv_bytes.decode("utf-8-sig").splitlines()))
        except UnicodeDecodeError as error:
            raise ValueError("daily-bar CSV must be UTF-8") from error
        if not rows:
            raise ValueError("daily-bar CSV must contain at least one row")
        reader_fields = tuple(rows[0])
        required = CSV_FIELDS if basis is AvailabilityBasis.PUBLISHED else CSV_FIELDS[:-1]
        if any(field not in reader_fields for field in required):
            raise ValueError(f"daily-bar CSV requires columns: {', '.join(required)}")
        provenance = Provenance(
            _text(manifest, "source"),
            _text(dataset_data, "name"),
            _text(manifest, "source_version"),
        )
        bars = tuple(
            self._parse_row(row, adjustment, basis, retrieved_at, provenance, index)
            for index, row in enumerate(rows, start=2)
        )
        return ImportedDailyBars(
            source_profile=_text(manifest, "source_profile"),
            source_name=provenance.source,
            source_version=provenance.version,
            dataset=provenance.dataset,
            instrument=instrument,
            adjustment=adjustment,
            retrieved_at=retrieved_at,
            availability_basis=basis,
            bars=bars,
            bundle_hash=_bundle_hash(manifest_bytes, csv_bytes),
        )

    @staticmethod
    def _parse_row(
        row: dict[str, str | None],
        adjustment: Adjustment,
        basis: AvailabilityBasis,
        retrieved_at: datetime,
        provenance: Provenance,
        line: int,
    ) -> DailyBar:
        try:
            published = row.get("published_at")
            available_at = (
                _aware_datetime(published, f"line {line} published_at")
                if basis is AvailabilityBasis.PUBLISHED
                else retrieved_at
            )
            return DailyBar(
                trading_date=date.fromisoformat(row["trading_date"] or ""),
                open=Decimal(row["open"] or ""),
                high=Decimal(row["high"] or ""),
                low=Decimal(row["low"] or ""),
                close=Decimal(row["close"] or ""),
                volume=int(row["volume"] or ""),
                adjustment=adjustment,
                available_at=available_at,
                provenance=provenance,
            )
        except (InvalidOperation, TypeError, ValueError, KeyError) as error:
            raise ValueError(f"invalid daily-bar value on CSV line {line}") from error
