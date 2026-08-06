"""Minimal external portfolio importer example."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from marketsieve import PortfolioSnapshot
from marketsieve_extension_api import ImportedPortfolioSnapshot


class ExamplePortfolioImporter:
    """Import one explicit empty state without application dependencies."""

    def import_portfolio(self, path: Path, *, as_of: datetime) -> ImportedPortfolioSnapshot:
        source = path.read_bytes()
        if source.decode("utf-8").splitlines() != ["status", "empty"]:
            raise ValueError("example portfolio input must contain one explicit empty state")
        return ImportedPortfolioSnapshot(
            snapshot=PortfolioSnapshot(as_of, (), (), "example_portfolio"),
            source_name="example-portfolio",
            source_version="0.1.0",
            dataset=path.name,
            source_hash=hashlib.sha256(source).hexdigest(),
            diagnostics=("empty_portfolio",),
        )
