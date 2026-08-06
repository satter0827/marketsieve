"""Strict import of a fixture-proven empty Rakuten Securities asset export."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from marketsieve import PortfolioSnapshot
from marketsieve_extension_api import ImportedPortfolioSnapshot

MAX_SOURCE_BYTES = 4 * 1024 * 1024
SOURCE_VERSION = "0.7.0"
DATASET = "assetbalance-all-empty/v1"
_SUMMARY_MARKER = "■資産合計欄"
_DETAIL_MARKER = "■ 保有商品詳細 (すべて）"  # noqa: RUF001 - exact observed marker
_EMPTY_DETAIL = "該当する情報はありません。"
_REFERENCE_MARKER = "■参考為替レート"
_SUMMARY_HEADER = ("", "時価評価額[円]", "評価損益[円]")
_SUMMARY_LABELS = (
    "資産合計",
    "保有商品の評価額合計",
    "国内株式",
    "米国株式",
    "預り金合計",
    "預り金",
)
_ZERO_BALANCE_LABELS = frozenset({"保有商品の評価額合計", "国内株式", "米国株式"})
_REFERENCE_CURRENCY_WORDS = (
    "ドル",
    "ユーロ",
    "ポンド",
    "ランド",
    "ペソ",
    "元",
    "バーツ",
    "リンギット",
    "ルピー",
)
_ISO_CURRENCY = re.compile(r"[A-Z]{3}")


class RakutenPortfolioImporter:
    """Import only the observed no-holdings form of `assetbalance(all)` CSV."""

    def import_portfolio(self, path: Path, *, as_of: datetime) -> ImportedPortfolioSnapshot:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("portfolio as_of must include a UTC offset")
        payload = _read_source(path)
        rows = _parse_rows(payload)
        _validate_empty_asset_balance(rows)
        snapshot = PortfolioSnapshot(as_of, (), (), "rakuten_assetbalance_empty")
        return ImportedPortfolioSnapshot(
            snapshot=snapshot,
            source_name="rakuten",
            source_version=SOURCE_VERSION,
            dataset=DATASET,
            source_hash=hashlib.sha256(payload).hexdigest(),
            diagnostics=("empty_portfolio",),
        )


def _read_source(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Rakuten portfolio source must be a regular file")
    size = path.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ValueError("Rakuten portfolio CSV exceeds the 4 MiB safety bound")
    payload = path.read_bytes()
    if not payload:
        raise ValueError("Rakuten portfolio CSV is empty")
    if len(payload) != size:
        raise ValueError("Rakuten portfolio CSV changed while being read")
    return payload


def _parse_rows(payload: bytes) -> tuple[tuple[str, ...], ...]:
    try:
        text = payload.decode("cp932")
    except UnicodeDecodeError as error:
        raise ValueError("Rakuten portfolio CSV must use CP932") from error
    try:
        rows = tuple(
            tuple(cell.strip() for cell in row)
            for row in csv.reader(io.StringIO(text), strict=True)
        )
    except csv.Error as error:
        raise ValueError("Rakuten portfolio CSV is malformed") from error
    if not rows or any(len(row) > 32 for row in rows):
        raise ValueError("Rakuten portfolio CSV structure is invalid")
    return rows


def _validate_empty_asset_balance(rows: tuple[tuple[str, ...], ...]) -> None:
    if rows[0] != (_SUMMARY_MARKER,):
        raise ValueError("Rakuten portfolio CSV is not an assetbalance(all) export")
    try:
        detail_index = rows.index((_DETAIL_MARKER,))
        reference_index = rows.index((_REFERENCE_MARKER,))
    except ValueError as error:
        raise ValueError("Rakuten portfolio CSV sections are incomplete") from error
    if reference_index <= detail_index:
        raise ValueError("Rakuten portfolio CSV section order is invalid")
    summary = tuple(row for row in rows[:detail_index] if row)
    if len(summary) != len(_SUMMARY_LABELS) + 2 or summary[1] != _SUMMARY_HEADER:
        raise ValueError("Rakuten portfolio CSV summary structure is unsupported")
    category_rows = summary[2:]
    if tuple(row[0] for row in category_rows) != _SUMMARY_LABELS or any(
        len(row) != 3 for row in category_rows
    ):
        raise ValueError("Rakuten portfolio CSV summary categories are unsupported")
    for label in _ZERO_BALANCE_LABELS:
        matches = tuple(row for row in category_rows if row[0] == label)
        if len(matches) != 1 or not all(_is_zero_or_empty(cell) for cell in matches[0][1:]):
            raise ValueError("Rakuten portfolio CSV contradicts its empty holdings detail")
    detail = tuple(row for row in rows[detail_index + 1 : reference_index] if row)
    if detail != ((_EMPTY_DETAIL,),):
        raise ValueError(
            "non-empty Rakuten holdings are unsupported until an anonymized real export "
            "defines them"
        )
    _validate_reference_rows(rows[reference_index + 1 :])


def _is_zero_or_empty(value: str) -> bool:
    if value in {"", "-", "--", "―"}:
        return True
    normalized = value.replace(",", "").removesuffix("円").removesuffix("%")
    try:
        return Decimal(normalized) == 0
    except InvalidOperation:
        return False


def _validate_reference_rows(rows: tuple[tuple[str, ...], ...]) -> None:
    populated = tuple(row for row in rows if row)
    if (
        not populated
        or not any("通貨" in cell for cell in populated[0])
        or not any("為替" in cell for cell in populated[0])
    ):
        raise ValueError("Rakuten portfolio CSV reference-rate header is unsupported")
    for row in populated[1:]:
        currency = row[0]
        has_currency = bool(_ISO_CURRENCY.fullmatch(currency)) or any(
            word in currency for word in _REFERENCE_CURRENCY_WORDS
        )
        has_numeric_rate = any(_is_number(cell.removesuffix("円")) for cell in row[1:] if cell)
        if not 2 <= len(row) <= 4 or not has_currency or not has_numeric_rate:
            raise ValueError("Rakuten portfolio CSV reference-rate rows are unsupported")


def _is_number(value: str) -> bool:
    try:
        Decimal(value.replace(",", ""))
    except InvalidOperation:
        return False
    return True
