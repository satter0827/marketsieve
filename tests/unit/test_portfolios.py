from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from marketsieve_cli.adapters.portfolios import (
    PortfolioStore,
    import_canonical_csv,
    portfolio_document,
)

HEADER = "kind,mic,symbol,currency,timezone,quantity,average_acquisition_price,account_type\n"


def payload() -> bytes:
    return (
        HEADER
        + "watch,XNAS,MSFT,USD,America/New_York,,,\n"
        + "holding,XTKS,7203,JPY,Asia/Tokyo,10.5,2500,NISA\n"
    ).encode()


def test_canonical_import_is_sorted_typed_and_source_bytes_are_not_stored(tmp_path: Path) -> None:
    original = payload()
    imported = import_canonical_csv(original, as_of=datetime(2026, 8, 6, 20, tzinfo=UTC))
    store = PortfolioStore(tmp_path / "portfolio")

    first = store.put(imported)
    second = store.put(imported)
    object_id, restored = store.latest()

    assert first == second == object_id
    assert restored == imported
    assert restored.source_hash == hashlib.sha256(original).hexdigest()
    assert restored.source_name == "canonical"
    assert restored.dataset == "canonical-portfolio/v1"
    assert store.latest_snapshot() == imported.snapshot
    assert [
        (item.instrument.mic, item.instrument.symbol) for item in restored.snapshot.holdings
    ] == [("XTKS", "7203")]
    assert [
        (item.instrument.mic, item.instrument.symbol) for item in restored.snapshot.watch_items
    ] == [("XNAS", "MSFT")]
    assert original not in (tmp_path / "portfolio" / "objects" / f"{object_id}.json").read_bytes()


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b"", "headers"),
        ((HEADER + "").encode(), "at least one"),
        ((HEADER + "watch,XNAS,MSFT,USD,America/New_York,1,,\n").encode(), "leave"),
        ((HEADER + "holding,XTKS,7203,JPY,Asia/Tokyo,nope,1,NISA\n").encode(), "amount"),
        ((HEADER + "other,XTKS,7203,JPY,Asia/Tokyo,,,\n").encode(), "kind"),
        ((HEADER + "watch,XNAS,MSFT,USD,Nowhere/Unknown,,,\n").encode(), "timezone"),
    ],
)
def test_canonical_import_rejects_ambiguous_input(body: bytes, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        import_canonical_csv(body, as_of=datetime(2026, 8, 6, tzinfo=UTC))


def test_import_rejects_futureless_timestamp_duplicate_and_oversized_source() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        import_canonical_csv(payload(), as_of=datetime(2026, 8, 6))
    duplicate = payload() + b"watch,XNAS,MSFT,USD,America/New_York,,,\n"
    with pytest.raises(ValueError, match="unique"):
        import_canonical_csv(duplicate, as_of=datetime(2026, 8, 6, tzinfo=UTC))
    with pytest.raises(ValueError, match="4 MiB"):
        import_canonical_csv(b"x" * (4 * 1024 * 1024 + 1), as_of=datetime(2026, 8, 6, tzinfo=UTC))


def test_store_rejects_missing_tampered_and_noncanonical_objects(tmp_path: Path) -> None:
    store = PortfolioStore(tmp_path / "portfolio")
    with pytest.raises(LookupError, match="portfolio import"):
        store.latest()
    with pytest.raises(ValueError, match="SHA-256"):
        store.show("bad")

    imported = import_canonical_csv(payload(), as_of=datetime(2026, 8, 6, tzinfo=UTC))
    object_id = store.put(imported)
    path = tmp_path / "portfolio" / "objects" / f"{object_id}.json"
    value = json.loads(path.read_bytes())
    value["source"] = "changed"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        store.show(object_id)


def test_store_rejects_symlink_destination(tmp_path: Path) -> None:
    imported = import_canonical_csv(payload(), as_of=datetime(2026, 8, 6, tzinfo=UTC))
    store = PortfolioStore(tmp_path / "portfolio")

    objects = tmp_path / "portfolio" / "objects"
    objects.mkdir(parents=True)
    target = tmp_path / "target"
    target.write_text("unchanged", encoding="utf-8")
    expected = hashlib.sha256(
        (
            json.dumps(
                portfolio_document(imported),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
    ).hexdigest()
    (objects / f"{expected}.json").symlink_to(target)
    with pytest.raises(ValueError, match="conflicts"):
        store.put(imported)
    assert target.read_text(encoding="utf-8") == "unchanged"
