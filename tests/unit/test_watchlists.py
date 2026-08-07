from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from marketsieve import Holding, PortfolioSnapshot
from marketsieve_cli.adapters.watchlists import (
    PortfolioWatchlistReader,
    WatchlistStore,
    parse_instrument_key,
)
from marketsieve_cli.bootstrap import build_watchlist_store


class Portfolios:
    def __init__(self, snapshot: PortfolioSnapshot) -> None:
        self._snapshot = snapshot

    def latest_snapshot(self) -> PortfolioSnapshot:
        return self._snapshot


def test_watchlist_add_remove_history(tmp_path: Path) -> None:
    store = WatchlistStore(tmp_path / "watchlists")
    first_time = datetime(2026, 8, 6, 10, tzinfo=UTC)
    first = store.add(
        parse_instrument_key("XTKS:7203"),
        as_of=first_time,
    )
    duplicate = store.add(
        parse_instrument_key("XTKS:7203"),
        as_of=first_time + timedelta(minutes=1),
    )
    second = store.add(
        parse_instrument_key("XNAS:MSFT"),
        as_of=first_time + timedelta(minutes=2),
    )
    removed = store.remove(
        parse_instrument_key("XTKS:7203"),
        as_of=first_time + timedelta(minutes=3),
    )

    assert duplicate == first
    assert second["previous_watchlist_id"] == first["watchlist_id"]
    assert removed["previous_watchlist_id"] == second["watchlist_id"]
    assert removed["items"][0]["key"] == "XNAS:MSFT"
    assert first["items"] == [
        {
            "key": "XTKS:7203",
            "instrument": {
                "mic": "XTKS",
                "symbol": "7203",
                "currency": "JPY",
                "timezone": "Asia/Tokyo",
                "type": "equity",
            },
        }
    ]
    assert [item["watchlist_id"] for item in store.history()] == [
        first["watchlist_id"],
        second["watchlist_id"],
        removed["watchlist_id"],
    ]


def test_existing_watchlist_item_is_idempotent(tmp_path: Path) -> None:
    store = WatchlistStore(tmp_path / "watchlists")
    observed = datetime(2026, 8, 6, 10, tzinfo=UTC)
    instrument = parse_instrument_key("XNAS:MSFT")
    first = store.add(instrument, as_of=observed)

    duplicate = store.add(instrument, as_of=observed + timedelta(minutes=1))

    assert duplicate == first
    assert len(store.history()) == 1


def test_composed_watchlist_store_does_not_read_legacy_v1_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / ".marketsieve/watchlists"
    (legacy / "refs").mkdir(parents=True)
    (legacy / "refs/latest.json").write_text("not-json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    store = build_watchlist_store()

    assert store.history() == ()
    store.add(
        parse_instrument_key("XNAS:MSFT"),
        as_of=datetime(2026, 8, 6, 10, tzinfo=UTC),
    )
    assert (legacy / "refs/latest.json").read_text(encoding="utf-8") == "not-json"
    assert (legacy / "v2/refs/latest.json").is_file()


def test_holding_takes_precedence_over_watchlist_duplicate(tmp_path: Path) -> None:
    instrument = parse_instrument_key("XTKS:7203")
    observed = datetime(2026, 8, 6, 10, tzinfo=UTC)
    store = WatchlistStore(tmp_path / "watchlists")
    store.add(instrument, as_of=observed)
    portfolio = PortfolioSnapshot(
        observed,
        (Holding(instrument, Decimal("10"), Decimal("2500"), "taxable"),),
        (),
        "fixture",
    )

    combined = PortfolioWatchlistReader(Portfolios(portfolio), store).latest_snapshot()

    assert combined.holdings == portfolio.holdings
    assert combined.watch_items == ()


def test_composed_snapshot_preserves_latest_watchlist_knowledge_time(tmp_path: Path) -> None:
    portfolio_time = datetime(2026, 8, 5, 10, tzinfo=UTC)
    watchlist_time = datetime(2026, 8, 6, 10, tzinfo=UTC)
    store = WatchlistStore(tmp_path / "watchlists")
    store.add(parse_instrument_key("XNAS:MSFT"), as_of=watchlist_time)
    portfolio = PortfolioSnapshot(portfolio_time, (), (), "fixture")

    combined = PortfolioWatchlistReader(Portfolios(portfolio), store).latest_snapshot()

    assert combined.as_of == watchlist_time
    assert [item.instrument.symbol for item in combined.watch_items] == ["MSFT"]


def test_watchlist_accepts_the_bats_identity_emitted_by_the_matrix(tmp_path: Path) -> None:
    store = WatchlistStore(tmp_path / "watchlists")
    instrument = parse_instrument_key("BATS:CBOE")

    document = store.add(instrument, as_of=datetime(2026, 8, 6, 10, tzinfo=UTC))

    assert document["items"][0]["key"] == "BATS:CBOE"
    assert store.watch_items()[0].instrument == instrument


def test_watchlist_rejects_revision_older_than_predecessor(tmp_path: Path) -> None:
    store = WatchlistStore(tmp_path / "watchlists")
    observed = datetime(2026, 8, 6, 10, tzinfo=UTC)
    store.add(parse_instrument_key("XTKS:7203"), as_of=observed)

    with pytest.raises(ValueError, match="must not predate"):
        store.add(
            parse_instrument_key("XNAS:MSFT"),
            as_of=observed - timedelta(seconds=1),
        )


@pytest.mark.parametrize("value", ("7203", "XHKG:0700", "xtks:7203", "XTKS:"))
def test_watchlist_rejects_unsupported_or_ambiguous_identity(value: str) -> None:
    with pytest.raises(ValueError, match="supported MIC:SYMBOL"):
        parse_instrument_key(value)


def test_watchlist_detects_tampering(tmp_path: Path) -> None:
    root = tmp_path / "watchlists"
    store = WatchlistStore(root)
    document = store.add(
        parse_instrument_key("XNYS:IBM"), as_of=datetime(2026, 8, 6, 10, tzinfo=UTC)
    )
    path = root / "objects" / f"{document['watchlist_id']}.json"
    path.write_bytes(path.read_bytes().replace(b"IBM", b"MSFT"))

    with pytest.raises(ValueError):
        store.show(document["watchlist_id"])


def test_empty_and_missing_watchlist_operations_are_explicit(tmp_path: Path) -> None:
    store = WatchlistStore(tmp_path / "watchlists")

    assert store.history() == ()
    assert store.watch_items() == ()
    with pytest.raises(LookupError, match="does not exist"):
        store.latest()
    with pytest.raises(LookupError, match="does not exist"):
        store.show("a" * 64)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        store.show("not-an-id")
    with pytest.raises(ValueError, match="UTC offset"):
        store.add(parse_instrument_key("XTKS:7203"), as_of=datetime(2026, 8, 6, 10))


def test_watchlist_rejects_invalid_reference_and_missing_removal(tmp_path: Path) -> None:
    root = tmp_path / "watchlists"
    store = WatchlistStore(root)
    observed = datetime(2026, 8, 6, 10, tzinfo=UTC)
    store.add(parse_instrument_key("XTKS:7203"), as_of=observed)

    with pytest.raises(LookupError, match="does not exist"):
        store.remove(parse_instrument_key("XNAS:MSFT"), as_of=observed)

    (root / "refs" / "latest.json").write_text('{"bad":"reference"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="latest reference is invalid"):
        store.latest()

    (root / "refs" / "latest.json").write_text(json.dumps({"watchlist_id": "a" * 64}))
    with pytest.raises(ValueError, match="not canonical"):
        store.latest()


def test_watchlist_does_not_hide_dangling_latest_object(tmp_path: Path) -> None:
    root = tmp_path / "watchlists"
    store = WatchlistStore(root)
    observed = datetime(2026, 8, 6, 10, tzinfo=UTC)
    document = store.add(parse_instrument_key("XTKS:7203"), as_of=observed)
    (root / "objects" / f"{document['watchlist_id']}.json").unlink()

    with pytest.raises(LookupError, match="object does not exist"):
        store.history()
    with pytest.raises(LookupError, match="object does not exist"):
        store.watch_items()
    with pytest.raises(LookupError, match="object does not exist"):
        store.add(parse_instrument_key("XNAS:MSFT"), as_of=observed)


def test_watchlist_rejects_symbolic_link_latest_reference(tmp_path: Path) -> None:
    root = tmp_path / "watchlists"
    (root / "refs").mkdir(parents=True)
    (root / "refs" / "latest.json").symlink_to(root / "missing.json")
    store = WatchlistStore(root)

    with pytest.raises(ValueError, match="real file"):
        store.exists()


@pytest.mark.parametrize("directory", ("objects", "refs"))
def test_watchlist_rejects_symlinked_storage_directory(tmp_path: Path, directory: str) -> None:
    root = tmp_path / "watchlists"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / directory).symlink_to(outside, target_is_directory=True)
    store = WatchlistStore(root)

    with pytest.raises(ValueError, match="storage path must be a real directory"):
        store.add(
            parse_instrument_key("XTKS:7203"),
            as_of=datetime(2026, 8, 6, 10, tzinfo=UTC),
        )

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(schema="unknown/v1"), "schema is unsupported"),
        (
            lambda value: value.update(change={"operation": "rename", "instrument": "XTKS:7203"}),
            "operation is invalid",
        ),
        (lambda value: value.update(items={}), "items are invalid"),
        (lambda value: value["items"][0].update(key="XTKS:9999"), "item key is invalid"),
        (lambda value: value["items"][0].update(unexpected="bad"), "item is invalid"),
    ),
)
def test_watchlist_validates_stored_document_shape(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None], message: str
) -> None:
    root = tmp_path / "watchlists"
    store = WatchlistStore(root)
    document = store.add(
        parse_instrument_key("XTKS:7203"),
        as_of=datetime(2026, 8, 6, 10, tzinfo=UTC),
    )
    path = root / "objects" / f"{document['watchlist_id']}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        store.show(document["watchlist_id"])
