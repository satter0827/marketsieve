"""Executable checks shared by instrument-universe plugin authors and hosts."""

from __future__ import annotations

from pathlib import Path

from marketsieve_extension_api.universe import (
    ImportedInstrumentUniverse,
    InstrumentUniverseImporter,
    UniverseRequest,
)


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
