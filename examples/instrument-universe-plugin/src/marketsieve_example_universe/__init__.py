"""Minimal external instrument-universe importer example."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path

from marketsieve.domain import Instrument
from marketsieve_extension_api import ImportedInstrumentUniverse, UniverseRequest


class ExampleUniverseImporter:
    """Import an explicit, small universe without depending on MarketSieve application code."""

    def import_universe(self, path: Path, request: UniverseRequest) -> ImportedInstrumentUniverse:
        source = path.read_bytes()
        retrieved_at_text = request.settings.get("retrieved_at")
        if retrieved_at_text is None:
            raise ValueError("example plugin requires settings.retrieved_at")
        retrieved_at = datetime.fromisoformat(retrieved_at_text)
        rows = tuple(csv.DictReader(source.decode("utf-8").splitlines()))
        expected_mics = {"jp": {"XTKS"}, "us": {"XNAS", "XNYS", "XASE"}}[request.market]
        if any(str(row["mic"]) not in expected_mics for row in rows):
            raise ValueError("example input contains an instrument from another market")
        instruments = tuple(
            sorted(
                (
                    Instrument.create(
                        mic=str(row["mic"]),
                        symbol=str(row["symbol"]),
                        currency=str(row["currency"]),
                        exchange_timezone=str(row["timezone"]),
                    )
                    for row in rows
                ),
                key=lambda item: (item.mic, item.symbol),
            )
        )
        selected = instruments[: request.limit]
        return ImportedInstrumentUniverse(
            request=request,
            source_name="example-universe",
            source_version="0.1.0",
            dataset=path.name,
            retrieved_at=retrieved_at,
            instruments=selected,
            source_hash=hashlib.sha256(source).hexdigest(),
            provider_total=len(instruments),
            truncated=len(instruments) > len(selected),
        )
