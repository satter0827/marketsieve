"""Reference-only Explorer contract and renderer for immutable evidence objects."""

# ruff: noqa: E501

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from importlib import resources
from typing import Any

EXPLORER_SCHEMA = "explorer-data/v5"
RENDERER_VERSION = "marketsieve-explorer/v5"


def _template(name: str) -> str:
    return (
        resources.files("marketsieve_cli.adapters")
        .joinpath("templates", name)
        .read_text(encoding="utf-8")
    )


def _view(
    view_id: str,
    section: str,
    chart_type: str,
    title: str,
    source: str,
    fields: Sequence[str],
    unit: str,
    period: str | None,
) -> dict[str, Any]:
    return {
        "id": view_id,
        "section": section,
        "type": chart_type,
        "title": title,
        "source": source,
        "fields": list(fields),
        "unit": unit,
        "period": period,
    }


def build_snapshot_explorer_data(
    manifest: Mapping[str, Any],
    fields: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a compact view contract that references Snapshot authorities."""

    catalog = [dict(field) for field in fields]
    known = {str(field["name"]) for field in catalog}
    column_sets = {
        "main": [
            "name",
            "close",
            "currency",
            "sector",
            "return_5d",
            "return_20d",
            "return_60d",
            "volatility_60d",
            "atr_14_ratio",
            "price_as_of",
        ],
        "price": ["close", "previous_close", "high_52w", "low_52w", "position_52w"],
        "return": [
            "return_1d",
            "return_5d",
            "return_20d",
            "return_60d",
            "return_120d",
            "return_252d",
        ],
        "risk": [
            "atr_14_ratio",
            "volatility_20d",
            "volatility_60d",
            "volatility_252d",
            "maximum_drawdown_60d",
            "maximum_drawdown_252d",
        ],
        "liquidity": [
            "average_volume_20d",
            "median_traded_value_20d",
            "volume_turnover_20d",
            "amihud_illiquidity_20d",
            "zero_volume_days_20d",
        ],
        "fundamental": [
            "trailing_pe",
            "forward_pe",
            "price_to_book",
            "enterprise_to_ebitda",
            "free_cash_flow_yield",
            "dividend_yield",
            "return_on_equity",
            "operating_margin",
            "revenue_growth",
        ],
        "quality": ["price_as_of"],
    }
    unknown = sorted({name for names in column_sets.values() for name in names} - known)
    if unknown:
        raise ValueError(f"Explorer column sets contain unknown fields: {unknown}")
    views = [
        _view(
            "market_breadth",
            "overview",
            "horizontal_bar",
            "移動平均を上回る銘柄の比率",
            "securities",
            ("distance_sma_20", "distance_sma_200"),
            "ratio",
            "20 / 200 trading days",
        ),
        _view(
            "return_distribution_20d",
            "overview",
            "histogram",
            "20営業日リターン分布",
            "securities",
            ("return_20d",),
            "ratio",
            "20 trading days",
        ),
        _view(
            "range_position_distribution",
            "overview",
            "histogram",
            "52週レンジ位置の分布",
            "securities",
            ("position_52w",),
            "bounded_ratio",
            "252 trading days",
        ),
        _view(
            "market_sector_heatmap",
            "overview",
            "heatmap",
            "市場・セクター別20営業日リターン中央値",
            "securities",
            ("sector", "return_20d"),
            "ratio",
            "20 trading days",
        ),
        _view(
            "return_volatility_60d",
            "risk",
            "scatter",
            "60営業日リターンとボラティリティ",
            "securities",
            ("volatility_60d", "return_60d"),
            "ratio",
            "60 trading days",
        ),
        _view(
            "atr_ratio_distribution",
            "risk",
            "histogram",
            "ATR率の分布",
            "securities",
            ("atr_14_ratio",),
            "ratio",
            "14 trading days",
        ),
        _view(
            "drawdown_distribution",
            "risk",
            "histogram",
            "252営業日最大ドローダウン分布",
            "securities",
            ("maximum_drawdown_252d",),
            "ratio",
            "252 trading days",
        ),
        _view(
            "pe_growth",
            "fundamentals",
            "scatter",
            "PERと利益成長率",
            "securities",
            ("trailing_pe", "earnings_growth"),
            "multiple_and_ratio",
            "provider current / trailing",
        ),
        _view(
            "pbr_roe",
            "fundamentals",
            "scatter",
            "PBRとROE",
            "securities",
            ("price_to_book", "return_on_equity"),
            "multiple_and_ratio",
            "provider current / trailing",
        ),
        _view(
            "market_indicators",
            "context",
            "line",
            "市場指標",
            "market_indicators",
            (),
            "definition_specific",
            "Snapshot acquisition window",
        ),
        _view(
            "domain_coverage",
            "quality",
            "horizontal_bar",
            "証拠領域別取得率",
            "quality",
            (),
            "ratio",
            None,
        ),
        _view(
            "freshness",
            "quality",
            "horizontal_bar",
            "証拠の経過日数",
            "quality",
            (),
            "days",
            "at retrieval",
        ),
    ]
    for view in views:
        if missing := sorted(set(view["fields"]) - known):
            raise ValueError(f"Explorer view {view['id']} contains unknown fields: {missing}")
    return {
        "schema": EXPLORER_SCHEMA,
        "metadata": {
            "object_type": "market_snapshot",
            "object_id": manifest["snapshot_id"],
            "title": "Market Snapshot Explorer",
            "locale": "ja",
            "created_at": manifest["created_at"],
            "source": manifest["source"],
            "object_contract": "market-snapshot/v9",
        },
        "renderer": {"version": RENDERER_VERSION},
        "sections": [
            {"id": "overview", "label": "概要", "description": "市場の広がりと分布"},
            {"id": "risk", "label": "リスク", "description": "変動、下落、流動性"},
            {
                "id": "fundamentals",
                "label": "ファンダメンタルズ",
                "description": "倍率、成長性、収益性",
            },
            {"id": "context", "label": "市場環境", "description": "指数、為替、金利、商品"},
            {"id": "quality", "label": "品質", "description": "取得率、鮮度、障害、欠損"},
            {"id": "securities", "label": "銘柄", "description": "検索、比較、個別調査"},
        ],
        "sources": {
            "definitions": {"path": "definitions.json", "format": "json"},
            "quality": {"path": "quality-summary.json", "format": "json"},
            "quality_details": {"path": "quality-details.jsonl", "format": "jsonl"},
            "quality_outliers": {"path": "quality-outliers.jsonl", "format": "jsonl"},
            "aggregates": {"path": "aggregates.jsonl", "format": "jsonl"},
            "securities": {"path": "securities.jsonl", "format": "jsonl"},
            "failures": {"path": "failures.jsonl", "format": "jsonl"},
            "market_indicators": {"path": "market-indicators.jsonl", "format": "jsonl"},
        },
        "facets": ["market", "index", "currency", "sector", "industry"],
        "column_sets": column_sets,
        "field_catalog": catalog,
        "views": views,
        "actions": {
            "query": "marketsieve market query --snapshot {object_id}",
            "compare": "marketsieve market compare {instrument_ids} --snapshot {object_id}",
            "research": (
                "marketsieve research build {instrument_id} --snapshot {object_id} "
                "--evidence price --evidence company --evidence financials "
                "--evidence events --evidence benchmarks --history-days 3653"
            ),
        },
    }


def _render_snapshot_explorer(document: Mapping[str, Any]) -> str:
    """Render the shared no-CDN shell; evidence is loaded from sibling authorities."""

    metadata = document["metadata"]
    title = html.escape(str(metadata["title"]))
    return _template("snapshot.html").replace("__TITLE__", title)


def build_research_explorer_data(
    manifest: Mapping[str, Any], definitions: Mapping[str, Any]
) -> dict[str, Any]:
    """Build a reference-only Research Explorer contract."""

    del definitions  # Definitions remain authoritative through the registered source.
    source_paths = {
        "manifest.json",
        "definitions.json",
        "company.json",
        "market-context.json",
        "prices.jsonl",
        "benchmarks.jsonl",
        "financials.jsonl",
        "events.jsonl",
        "failures.jsonl",
        "quality-summary.json",
        "quality-details.jsonl",
        "quality-outliers.jsonl",
    }
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("Research Explorer sources are not registered artifacts: manifest")
    if missing := sorted(source_paths - set(artifacts)):
        raise ValueError(f"Research Explorer sources are not registered artifacts: {missing}")
    catalog = [
        {
            "name": name,
            "data_type": data_type,
            "unit": unit,
            "definition": definition,
        }
        for name, data_type, unit, definition in (
            ("date", "date", "date", "Trading date."),
            ("close", "decimal", "instrument_currency", "Adjusted closing price."),
            ("volume", "integer", "split_adjusted_shares", "Daily traded volume."),
            ("benchmark", "string", "identifier", "Benchmark membership identifier."),
            ("concept", "string", "identifier", "Normalized financial concept."),
            ("value", "decimal", "definition_specific", "Evidence value."),
            ("period", "string", "period", "Annual or quarterly reporting period."),
            ("event_type", "string", "identifier", "Corporate event type."),
            ("effective_date", "date", "date", "Event effective date."),
            ("status", "string", "state", "Independent evidence acquisition state."),
        )
    ]
    views = [
        _view(
            "price",
            "overview",
            "line",
            "株価と移動平均",
            "prices",
            ("date", "close"),
            "instrument_currency",
            "selected",
        ),
        _view(
            "volume",
            "overview",
            "horizontal_bar",
            "出来高",
            "prices",
            ("date", "volume"),
            "split_adjusted_shares",
            "selected",
        ),
        _view(
            "relative",
            "overview",
            "line",
            "ベンチマーク相対推移",
            "benchmarks",
            ("date", "close"),
            "rebased_index",
            "selected",
        ),
        _view(
            "volatility",
            "risk",
            "line",
            "20営業日ローリング・ボラティリティ",
            "prices",
            ("date", "close"),
            "annualized_ratio",
            "20 trading days",
        ),
        _view(
            "drawdown",
            "risk",
            "line",
            "ドローダウン",
            "prices",
            ("date", "close"),
            "ratio",
            "selected",
        ),
        _view(
            "annual",
            "financials",
            "horizontal_bar",
            "年次財務",
            "financials",
            ("concept", "value"),
            "reporting_currency_or_per_share",
            "annual",
        ),
        _view(
            "quarterly",
            "financials",
            "horizontal_bar",
            "四半期財務",
            "financials",
            ("concept", "value"),
            "reporting_currency_or_per_share",
            "quarterly",
        ),
        _view(
            "events",
            "events",
            "horizontal_bar",
            "企業イベント",
            "events",
            ("event_type", "effective_date"),
            "event_specific",
            "selected",
        ),
        _view(
            "evidence",
            "evidence",
            "horizontal_bar",
            "証拠状態と定義",
            "quality",
            ("status",),
            "state",
            None,
        ),
    ]
    return {
        "schema": EXPLORER_SCHEMA,
        "metadata": {
            "object_type": "security_research",
            "object_id": manifest["research_id"],
            "title": "Security Research Explorer",
            "locale": "ja",
            "created_at": manifest["created_at"],
            "source": manifest["source"],
            "object_contract": "security-research/v9",
        },
        "renderer": {"version": RENDERER_VERSION},
        "sections": [
            {"id": "overview", "label": "概要", "description": "価格、出来高、ベンチマーク"},
            {"id": "risk", "label": "リスク", "description": "変動と下落、回復"},
            {"id": "financials", "label": "財務", "description": "年次と四半期の証拠"},
            {"id": "events", "label": "イベント", "description": "決算、配当、分割"},
            {"id": "evidence", "label": "証拠", "description": "取得状態、定義、欠損、障害"},
        ],
        "sources": {
            "manifest": {"path": "manifest.json", "format": "json"},
            "definitions": {"path": "definitions.json", "format": "json"},
            "company": {"path": "company.json", "format": "json"},
            "market_context": {"path": "market-context.json", "format": "json"},
            "prices": {"path": "prices.jsonl", "format": "jsonl"},
            "benchmarks": {"path": "benchmarks.jsonl", "format": "jsonl"},
            "financials": {"path": "financials.jsonl", "format": "jsonl"},
            "events": {"path": "events.jsonl", "format": "jsonl"},
            "failures": {"path": "failures.jsonl", "format": "jsonl"},
            "quality": {"path": "quality-summary.json", "format": "json"},
            "quality_details": {"path": "quality-details.jsonl", "format": "jsonl"},
            "quality_outliers": {"path": "quality-outliers.jsonl", "format": "jsonl"},
        },
        "facets": ["period", "event_type", "evidence_domain"],
        "column_sets": {
            "price": ["date", "close", "volume"],
            "financial": ["period", "concept", "value"],
            "event": ["effective_date", "event_type"],
            "evidence": ["status"],
        },
        "field_catalog": catalog,
        "views": views,
        "actions": {
            "query": f"marketsieve research show {manifest['research_id']}",
            "compare": (
                f"marketsieve market compare {{instrument_ids}} --snapshot {manifest['snapshot_id']}"
            ),
            "research": (
                f"marketsieve research build {manifest['instrument_id']} "
                f"--snapshot {manifest['snapshot_id']} --evidence price --evidence company "
                "--evidence financials --evidence events --evidence benchmarks --history-days 3653"
            ),
        },
    }


def render_explorer(document: Mapping[str, Any]) -> str:
    """Render the object-specific shell from the shared Explorer contract."""

    object_type = document.get("metadata", {}).get("object_type")
    if object_type == "market_snapshot":
        return _render_snapshot_explorer(document)
    if object_type == "security_research":
        title = html.escape(str(document["metadata"]["title"]))
        return _template("research.html").replace("__TITLE__", title)
    raise ValueError(f"unsupported Explorer object type: {object_type}")
