"""Executable checks shared by instrument-universe plugin authors and hosts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from marketsieve_extension_api.portfolio import (
    ImportedPortfolioSnapshot,
    PortfolioSnapshotImporter,
)
from marketsieve_extension_api.universe import (
    ImportedInstrumentUniverse,
    InstrumentUniverseImporter,
    UniverseRequest,
)


def verify_portfolio_snapshot_importer(
    importer: object, path: Path, *, as_of: datetime
) -> ImportedPortfolioSnapshot:
    """Execute one portfolio import and verify its public result contract."""

    if not isinstance(importer, PortfolioSnapshotImporter):
        raise TypeError("plugin does not implement PortfolioSnapshotImporter")
    result = importer.import_portfolio(path, as_of=as_of)
    if not isinstance(result, ImportedPortfolioSnapshot):
        raise TypeError("plugin returned a non-conforming portfolio snapshot")
    if result.snapshot.as_of.isoformat() != as_of.isoformat():
        raise ValueError("plugin result does not preserve the exact portfolio as_of")
    if result.snapshot.watch_items:
        raise ValueError("plugin result must not contain watchlist instruments")
    return result


def verify_instrument_universe_importer(
    importer: object, path: Path, request: UniverseRequest
) -> ImportedInstrumentUniverse:
    """Execute one importer request and verify the public result contract."""

    if not isinstance(importer, InstrumentUniverseImporter):
        raise TypeError("plugin does not implement InstrumentUniverseImporter")
    result = importer.import_universe(path, request)
    if not isinstance(result, ImportedInstrumentUniverse):
        raise TypeError("plugin returned a non-conforming instrument universe")
    if result.request != request:
        raise ValueError("plugin result does not preserve the exact universe request")
    return result
