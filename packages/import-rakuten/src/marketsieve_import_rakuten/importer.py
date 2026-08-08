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
SOURCE_VERSION = "0.11.0"
DATASET = "assetbalance-all-empty/v1"
_SUMMARY_MARKER = "■資産合計欄"
_DETAIL_MARKER = "■ 保有商品詳細 (すべて）"  # noqa: RUF001 - exact observed marker
_EMPTY_DETAIL = "該当する情報はありません。"
_REFERENCE_MARKER = "■参考為替レート"
_SUMMARY_HEADER = (
    "",
    "時価評価額[円]",
    "前日比[円]",
    "前日比[％]",  # noqa: RUF001 - exact provider header
    "前月比[円]",
    "前月比[％]",  # noqa: RUF001 - exact provider header
    "評価損益[円]",
    "評価損益[％]",  # noqa: RUF001 - exact provider header
    "",
    "実現損益[円]",
    "配当・分配金[円貨]",
    "配当・分配金[外貨]",
)
_SUMMARY_LABELS = (
    "資産合計",
    "保有商品の評価額合計",
    "国内株式",
    "米国株式",
    "中国株式",
    "アセアン株式",
    "投資信託",
    "楽天・マネーファンド",
    "外貨建MMF",
    "国内債券",
    "外国債券",
    "金・プラチナ",
    "預り金合計",
    "預り金",
    "外貨預り金",
    "楽天銀行普通預金残高",
)
_ZERO_BALANCE_LABELS = frozenset(
    {
        "保有商品の評価額合計",
        "国内株式",
        "米国株式",
        "中国株式",
        "アセアン株式",
        "投資信託",
        "楽天・マネーファンド",
        "外貨建MMF",
        "国内債券",
        "外国債券",
        "金・プラチナ",
    }
)
_REFERENCE_LABELS = (
    "米ドル",
    "ユーロ",
    "イギリスポンド",
    "オーストラリアドル",
    "ニュージーランドドル",
    "カナダドル",
    "トルコリラ",
    "南アフリカランド",
    "ロシアルーブル",
    "メキシコペソ",
)
_REFERENCE_CURRENCY_WORDS = (
    "ドル",
    "ユーロ",
    "ポンド",
    "リラ",
    "ルーブル",
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
    if len(summary) > 1 and summary[1] == ("", "時価評価額[円]", "評価損益[円]"):
        _validate_legacy_summary(summary)
        detail = tuple(row for row in rows[detail_index + 1 : reference_index] if row)
        if detail != ((_EMPTY_DETAIL,),):
            raise ValueError(
                "non-empty Rakuten holdings are unsupported until an anonymized real export "
                "defines them"
            )
        _validate_legacy_reference_rows(rows[reference_index + 1 :])
        return
    if len(summary) != len(_SUMMARY_LABELS) + 2 or summary[1] != _SUMMARY_HEADER:
        raise ValueError("Rakuten portfolio CSV summary structure is unsupported")
    category_rows = summary[2:]
    if tuple(row[0] for row in category_rows) != _SUMMARY_LABELS:
        raise ValueError("Rakuten portfolio CSV summary categories are unsupported")
    for row in category_rows:
        expected_width = (
            2 if row[0] == "楽天銀行普通預金残高" else 10 if row[0] == "金・プラチナ" else 12
        )
        if len(row) != expected_width:
            raise ValueError("Rakuten portfolio CSV summary row width is unsupported")
    bank = category_rows[-1]
    if bank[1] not in {"未連携", "0", "-"}:
        raise ValueError("Rakuten bank balance state is unsupported")
    for label in _ZERO_BALANCE_LABELS:
        matches = tuple(row for row in category_rows if row[0] == label)
        if len(matches) != 1 or not all(_is_zero_or_empty(cell) for cell in matches[0][1:8]):
            raise ValueError("Rakuten portfolio CSV contradicts its empty holdings detail")
    detail = tuple(row for row in rows[detail_index + 1 : reference_index] if row)
    if detail != ((_EMPTY_DETAIL,),):
        raise ValueError(
            "non-empty Rakuten holdings are unsupported until an anonymized real export "
            "defines them"
        )
    _validate_reference_rows(rows[reference_index + 1 :])


def _validate_legacy_summary(summary: tuple[tuple[str, ...], ...]) -> None:
    labels = ("資産合計", "保有商品の評価額合計", "国内株式", "米国株式", "預り金合計", "預り金")
    if len(summary) != len(labels) + 2:
        raise ValueError("Rakuten portfolio CSV summary structure is unsupported")
    category_rows = summary[2:]
    if tuple(row[0] for row in category_rows) != labels or any(
        len(row) != 3 for row in category_rows
    ):
        raise ValueError("Rakuten portfolio CSV summary categories are unsupported")
    for label in ("保有商品の評価額合計", "国内株式", "米国株式"):
        row = next(item for item in category_rows if item[0] == label)
        if not all(_is_zero_or_empty(cell) for cell in row[1:]):
            raise ValueError("Rakuten portfolio CSV contradicts its empty holdings detail")


def _validate_legacy_reference_rows(rows: tuple[tuple[str, ...], ...]) -> None:
    populated = tuple(row for row in rows if row)
    if not populated or populated[0] != ("通貨", "為替レート"):
        raise ValueError("Rakuten portfolio CSV reference-rate header is unsupported")
    for row in populated[1:]:
        currency = row[0]
        has_currency = bool(_ISO_CURRENCY.fullmatch(currency)) or any(
            word in currency for word in _REFERENCE_CURRENCY_WORDS
        )
        if (
            not 2 <= len(row) <= 4
            or not has_currency
            or not any(_is_number(cell.removesuffix("円")) for cell in row[1:] if cell)
        ):
            raise ValueError("Rakuten portfolio CSV reference-rate rows are unsupported")


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
    if tuple(row[0] for row in populated) != _REFERENCE_LABELS:
        raise ValueError("Rakuten portfolio CSV reference-rate currencies are unsupported")
    for row in populated:
        currency = row[0]
        has_currency = bool(_ISO_CURRENCY.fullmatch(currency)) or any(
            word in currency for word in _REFERENCE_CURRENCY_WORDS
        )
        has_numeric_rate = any(_is_number(cell.removesuffix("円")) for cell in row[1:] if cell)
        if len(row) != 4 or not has_currency or not has_numeric_rate:
            raise ValueError("Rakuten portfolio CSV reference-rate rows are unsupported")


def _is_number(value: str) -> bool:
    try:
        Decimal(value.replace(",", ""))
    except InvalidOperation:
        return False
    return True
