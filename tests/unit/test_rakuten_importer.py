from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from marketsieve_import_rakuten import RakutenPortfolioImporter

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests/fixtures/rakuten/assetbalance-empty.csv"
OBSERVED_AT = datetime(2026, 8, 6, 3, 48, 40, tzinfo=UTC)


def test_rakuten_empty_export_imports_without_retaining_personal_data(tmp_path: Path) -> None:
    result = RakutenPortfolioImporter().import_portfolio(FIXTURE, as_of=OBSERVED_AT)

    assert result.snapshot.as_of == OBSERVED_AT
    assert result.snapshot.holdings == ()
    assert result.snapshot.watch_items == ()
    assert result.snapshot.source == "rakuten_assetbalance_empty"
    assert result.diagnostics == ("empty_portfolio",)
    assert len(result.source_hash) == 64
    assert tuple(tmp_path.iterdir()) == ()
    fixture_text = FIXTURE.read_bytes().decode("cp932")
    assert "お客様コード" not in fixture_text
    assert "氏名" not in fixture_text


def test_rakuten_import_requires_aware_observation_time() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        RakutenPortfolioImporter().import_portfolio(FIXTURE, as_of=datetime(2026, 8, 6, 12, 48, 40))


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ("該当する情報はありません。", "銘柄コード,銘柄名,数量"),
        ("■参考為替レート", "■別の参考情報"),
        ("国内株式,0,0", ""),
    ),
)
def test_rakuten_import_rejects_unverified_or_incomplete_shapes(
    tmp_path: Path, replacement: str, message: str
) -> None:
    source = tmp_path / "assetbalance.csv"
    text = FIXTURE.read_bytes().decode("cp932").replace(replacement, message)
    source.write_bytes(text.encode("cp932"))

    with pytest.raises(ValueError):
        RakutenPortfolioImporter().import_portfolio(source, as_of=OBSERVED_AT)


def test_rakuten_import_rejects_non_empty_detail_explicitly(tmp_path: Path) -> None:
    source = tmp_path / "assetbalance.csv"
    text = (
        FIXTURE.read_bytes()
        .decode("cp932")
        .replace("該当する情報はありません。", "銘柄コード,銘柄名,数量")
    )
    source.write_bytes(text.encode("cp932"))

    with pytest.raises(ValueError, match="non-empty Rakuten holdings are unsupported"):
        RakutenPortfolioImporter().import_portfolio(source, as_of=OBSERVED_AT)


def test_rakuten_import_rejects_nonzero_security_summary(tmp_path: Path) -> None:
    source = tmp_path / "assetbalance.csv"
    text = FIXTURE.read_bytes().decode("cp932").replace("国内株式,0,0", "国内株式,100000,0")
    source.write_bytes(text.encode("cp932"))

    with pytest.raises(ValueError, match="contradicts its empty holdings detail"):
        RakutenPortfolioImporter().import_portfolio(source, as_of=OBSERVED_AT)


def test_rakuten_import_rejects_unknown_trailing_sections(tmp_path: Path) -> None:
    source = tmp_path / "assetbalance.csv"
    source.write_bytes(FIXTURE.read_bytes() + "\n■unknown\ncustomer,secret\n".encode("cp932"))

    with pytest.raises(ValueError, match="reference-rate rows are unsupported"):
        RakutenPortfolioImporter().import_portfolio(source, as_of=OBSERVED_AT)


def test_rakuten_import_rejects_unknown_summary_sections(tmp_path: Path) -> None:
    source = tmp_path / "assetbalance.csv"
    text = (
        FIXTURE.read_bytes()
        .decode("cp932")
        .replace(
            "保有商品の評価額合計,0,0\n",
            "保有商品の評価額合計,0,0\n■未検証セクション\n顧客コード,123456\n",
        )
    )
    source.write_bytes(text.encode("cp932"))

    with pytest.raises(ValueError, match="summary structure is unsupported"):
        RakutenPortfolioImporter().import_portfolio(source, as_of=OBSERVED_AT)


def test_rakuten_import_rejects_empty_or_indirect_source(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    link = tmp_path / "link.csv"
    link.symlink_to(FIXTURE)

    with pytest.raises(ValueError, match="empty"):
        RakutenPortfolioImporter().import_portfolio(empty, as_of=OBSERVED_AT)
    with pytest.raises(ValueError, match="regular file"):
        RakutenPortfolioImporter().import_portfolio(link, as_of=OBSERVED_AT)


def test_rakuten_import_accepts_supported_reference_rate_rows(tmp_path: Path) -> None:
    source = tmp_path / "assetbalance.csv"
    source.write_bytes(FIXTURE.read_bytes() + "USD,150.25\n米ドル,150円\n".encode("cp932"))

    assert (
        RakutenPortfolioImporter().import_portfolio(source, as_of=OBSERVED_AT).snapshot.holdings
        == ()
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        (b"\x81", "CP932"),
        ('"unterminated'.encode("cp932"), "malformed"),
        (
            FIXTURE.read_bytes() + (",".join("x" for _ in range(33)) + "\n").encode("cp932"),
            "structure",
        ),
        (
            FIXTURE.read_bytes().replace("時価評価額[円]".encode("cp932"), b"unsupported"),
            "summary structure",
        ),
        (
            FIXTURE.read_bytes().replace("通貨,為替レート".encode("cp932"), b"unsupported"),
            "reference-rate header",
        ),
    ),
)
def test_rakuten_import_rejects_unsafe_encodings_and_shapes(
    tmp_path: Path, payload: bytes, message: str
) -> None:
    source = tmp_path / "assetbalance.csv"
    source.write_bytes(payload)

    with pytest.raises(ValueError, match=message):
        RakutenPortfolioImporter().import_portfolio(source, as_of=OBSERVED_AT)


def test_rakuten_import_rejects_oversized_source(tmp_path: Path) -> None:
    source = tmp_path / "assetbalance.csv"
    source.write_bytes(b"x" * (4 * 1024 * 1024 + 1))

    with pytest.raises(ValueError, match="4 MiB"):
        RakutenPortfolioImporter().import_portfolio(source, as_of=OBSERVED_AT)
