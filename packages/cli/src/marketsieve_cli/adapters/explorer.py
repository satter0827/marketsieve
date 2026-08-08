"""Deterministic data projections and a shared self-contained Explorer renderer."""

# ruff: noqa: E501

from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any


def _decimal(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _chart(
    chart_id: str,
    section: str,
    chart_type: str,
    title: str,
    *,
    fields: Sequence[str],
    unit: str,
    period: str | None,
    data: Sequence[Mapping[str, object]],
    missing_count: int = 0,
    applicability: str = "all_equities",
) -> dict[str, Any]:
    rows = [dict(value) for value in data]
    return {
        "chart_id": chart_id,
        "section": section,
        "chart_type": chart_type,
        "title": title,
        "fields": list(fields),
        "unit": unit,
        "period": period,
        "observation_count": len(rows),
        "missing_count": missing_count,
        "applicability": applicability,
        "data": rows,
        "fallback_table": rows,
    }


def _histogram(
    rows: Sequence[Mapping[str, Any]], field: str, bins: int = 12
) -> list[dict[str, object]]:
    values = [value for row in rows if (value := _decimal(row["values"].get(field))) is not None]
    if not values:
        return []
    low, high = min(values), max(values)
    if low == high:
        return [{"label": str(low), "value": len(values)}]
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        index = min(int((value - low) / width), bins - 1)
        counts[index] += 1
    return [
        {
            "label": f"{low + width * index:.4f}-{low + width * (index + 1):.4f}",
            "value": count,
        }
        for index, count in enumerate(counts)
    ]


def _scatter(
    rows: Sequence[Mapping[str, Any]], x_field: str, y_field: str
) -> list[dict[str, object]]:
    output = []
    for row in rows:
        x = _decimal(row["values"].get(x_field))
        y = _decimal(row["values"].get(y_field))
        if x is not None and y is not None:
            output.append(
                {
                    "label": row["instrument_id"],
                    "x": str(x),
                    "y": str(y),
                    "market": "jp" if row["instrument"]["mic"] == "XTKS" else "us",
                    "currency": row["values"].get("currency", row["instrument"]["currency"]),
                }
            )
    return output


def build_snapshot_explorer_data(
    manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
    fields: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    quality: Mapping[str, Any],
    market_indicators: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a chart-neutral deterministic Snapshot projection."""

    groups = summary["groups"]
    breadth = []
    for group_name in ("all", "market:jp", "market:us"):
        group = groups[group_name]
        count = group["price_count"]
        for label, key in (("SMA20超", "above_sma_20_count"), ("SMA200超", "above_sma_200_count")):
            breadth.append(
                {
                    "label": f"{group_name}:{label}",
                    "value": str(Decimal(group[key]) / count) if count else None,
                }
            )
    charts = [
        _chart(
            "market_breadth",
            "Overview",
            "horizontal_bar",
            "市場の広がり",
            fields=("distance_sma_20", "distance_sma_200"),
            unit="ratio",
            period="20 / 200 trading days",
            data=breadth,
        ),
        _chart(
            "range_position_distribution",
            "Overview",
            "histogram",
            "52週レンジ位置の分布",
            fields=("position_52w",),
            unit="ratio",
            period="252 trading days",
            data=_histogram(rows, "position_52w"),
            missing_count=sum("position_52w" not in row["values"] for row in rows),
        ),
        _chart(
            "return_distribution_20d",
            "Overview",
            "histogram",
            "20営業日リターン分布",
            fields=("return_20d",),
            unit="ratio",
            period="20 trading days",
            data=_histogram(rows, "return_20d"),
            missing_count=sum("return_20d" not in row["values"] for row in rows),
        ),
        _chart(
            "return_volatility_60d",
            "Risk",
            "scatter",
            "60営業日リターンとボラティリティ",
            fields=("volatility_60d", "return_60d"),
            unit="ratio",
            period="60 trading days",
            data=_scatter(rows, "volatility_60d", "return_60d"),
        ),
        _chart(
            "atr_ratio_distribution",
            "Risk",
            "histogram",
            "ATR率の分布",
            fields=("atr_14_ratio",),
            unit="ratio",
            period="14 trading days",
            data=_histogram(rows, "atr_14_ratio"),
            missing_count=sum("atr_14_ratio" not in row["values"] for row in rows),
        ),
        _chart(
            "zero_volume_distribution",
            "Risk",
            "histogram",
            "直近20営業日の無出来高日数",
            fields=("zero_volume_days_20d",),
            unit="trading_days",
            period="20 trading days",
            data=_histogram(rows, "zero_volume_days_20d"),
            missing_count=sum("zero_volume_days_20d" not in row["values"] for row in rows),
        ),
        _chart(
            "drawdown_distribution",
            "Risk",
            "histogram",
            "252営業日最大ドローダウン分布",
            fields=("maximum_drawdown_252d",),
            unit="ratio",
            period="252 trading days",
            data=_histogram(rows, "maximum_drawdown_252d"),
        ),
    ]
    for chart_id, title, x_field, y_field in (
        ("pe_growth", "PERと利益成長率", "trailing_pe", "earnings_growth"),
        ("pbr_roe", "PBRとROE", "price_to_book", "return_on_equity"),
        ("ev_ebitda_growth", "EV/EBITDAと売上成長率", "enterprise_to_ebitda", "revenue_growth"),
        ("fcf_yield_margin", "FCF利回りとFCF率", "free_cash_flow_yield", "free_cash_flow_margin"),
    ):
        charts.append(
            _chart(
                chart_id,
                "Fundamentals",
                "scatter",
                title,
                fields=(x_field, y_field),
                unit="mixed_ratio_or_multiple",
                period="provider current / trailing",
                data=_scatter(rows, x_field, y_field),
                applicability="definition-specific; JP and US must be filtered before comparison",
            )
        )
    heatmap = []
    for key, value in sorted(groups.items()):
        if not key.startswith("market-sector:"):
            continue
        market, _, sector = key.removeprefix("market-sector:").partition("|")
        distribution = value["distributions"].get("return_20d", {})
        heatmap.append(
            {
                "x": market,
                "y": sector,
                "value": distribution.get("median"),
                "count": distribution.get("count", 0),
            }
        )
    charts.append(
        _chart(
            "market_sector_heatmap",
            "Overview",
            "heatmap",
            "市場 x セクター 20営業日リターン中央値",
            fields=("return_20d", "sector"),
            unit="ratio",
            period="20 trading days",
            data=heatmap,
        )
    )
    freshness = [
        {"label": key, "value": value.get("maximum")}
        for key, value in sorted(quality.get("freshness", {}).items())
        if isinstance(value, Mapping) and _decimal(value.get("maximum")) is not None
    ]
    charts.append(
        _chart(
            "quality_freshness",
            "Quality",
            "horizontal_bar",
            "証拠の経過日数",
            fields=("price_age_days", "financial_age_days"),
            unit="days",
            period="at retrieval",
            data=freshness,
        )
    )
    for indicator in market_indicators:
        charts.append(
            _chart(
                f"context_{indicator['indicator_id']}",
                "Context",
                "line",
                str(indicator["name"]),
                fields=(str(indicator["indicator_id"]),),
                unit=str(indicator["unit"]),
                period="Snapshot acquisition window",
                data=indicator["observations"],
                missing_count=0 if indicator["observations"] else 1,
            )
        )
    domain_quality = [
        {"label": name, "value": value["coverage"], "count": value["applicable"]}
        for name, value in sorted(quality["domains"].items())
    ]
    charts.append(
        _chart(
            "quality_domain_coverage",
            "Quality",
            "horizontal_bar",
            "証拠領域別取得率",
            fields=(),
            unit="ratio",
            period=None,
            data=domain_quality,
        )
    )
    visible = (
        "name",
        "close",
        "currency",
        "sector",
        "industry",
        "exchange",
        "country",
        "position_52w",
        "return_1d",
        "return_5d",
        "return_20d",
        "return_60d",
        "return_120d",
        "return_252d",
        "distance_sma_20",
        "distance_sma_50",
        "distance_sma_200",
        "rsi_14",
        "macd_histogram",
        "atr_14_ratio",
        "volatility_20d",
        "volatility_60d",
        "maximum_drawdown_252d",
        "average_volume_20d",
        "median_traded_value_20d",
        "amihud_illiquidity_20d",
        "trailing_pe",
        "forward_pe",
        "price_to_book",
        "enterprise_to_ebitda",
        "free_cash_flow_yield",
        "dividend_yield",
        "return_on_equity",
        "operating_margin",
        "revenue_growth",
        "price_as_of",
    )
    securities = [
        {
            "instrument_id": row["instrument_id"],
            "market": "jp" if row["instrument"]["mic"] == "XTKS" else "us",
            "memberships": row["memberships"],
            "instrument": row["instrument"],
            "values": {name: row["values"].get(name) for name in visible},
            "missing": {
                name: row["missing"].get(name) for name in visible if name in row["missing"]
            },
        }
        for row in rows
    ]
    return {
        "schema": "explorer-data/v1",
        "object_type": "market_snapshot",
        "object_id": manifest["snapshot_id"],
        "title": "Market Snapshot Explorer",
        "locale": "ja",
        "sections": ["Overview", "Risk", "Fundamentals", "Context", "Quality", "Securities"],
        "charts": charts,
        "securities": securities,
        "field_definitions": list(fields),
    }


def _moving_average(values: Sequence[Decimal], period: int) -> list[str | None]:
    output: list[str | None] = []
    for index in range(len(values)):
        selected = values[max(0, index - period + 1) : index + 1]
        output.append(str(sum(selected) / period) if len(selected) == period else None)
    return output


def _rolling_risk(
    prices: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    closes = [_decimal(value.get("close")) for value in prices]
    returns: list[float | None] = [None]
    for previous, current in pairwise(closes):
        returns.append(
            math.log(float(current / previous))
            if previous is not None and current is not None and previous > 0 and current > 0
            else None
        )
    volatility = []
    liquidity = []
    for index, price in enumerate(prices):
        window = [value for value in returns[max(0, index - 19) : index + 1] if value is not None]
        annualized = None
        if len(window) >= 2:
            average = sum(window) / len(window)
            variance = sum((value - average) ** 2 for value in window) / (len(window) - 1)
            annualized = math.sqrt(variance * 252)
        volatility.append({"date": price["date"], "value": annualized})
        liquidity.append({"date": price["date"], "value": price.get("volume")})
    return volatility, liquidity


def build_research_explorer_data(
    manifest: Mapping[str, Any],
    company: Mapping[str, Any],
    quality: Mapping[str, Any],
    prices: Sequence[Mapping[str, Any]],
    benchmarks: Sequence[Mapping[str, Any]],
    financials: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a chart-neutral deterministic Research projection."""

    closes = [_decimal(value["close"]) or Decimal(0) for value in prices]
    sma20 = _moving_average(closes, 20)
    sma50 = _moving_average(closes, 50)
    price_data = [
        {
            "date": value["date"],
            "close": value["close"],
            "sma20": sma20[index],
            "sma50": sma50[index],
            "volume": value["volume"],
        }
        for index, value in enumerate(prices)
    ]
    drawdown = []
    peak: Decimal | None = None
    for value in prices:
        close = _decimal(value["close"])
        if close is None:
            continue
        peak = close if peak is None else max(peak, close)
        drawdown.append({"date": value["date"], "value": str(close / peak - 1)})
    rolling_volatility, liquidity = _rolling_risk(prices)
    financial_rows = [
        {
            "date": value["fiscal_period_end"],
            "period": value["period"],
            "statement": value["statement"],
            "concept": value["concept"],
            "value": value["value"],
            "currency": value["currency"],
        }
        for value in financials
    ]
    charts = [
        _chart(
            "price_sma_volume",
            "Overview",
            "line",
            "株価・移動平均・出来高",
            fields=("close", "sma20", "sma50", "volume"),
            unit="instrument_currency_and_shares",
            period="daily; 20 / 50 trading-day SMA",
            data=price_data[-252:],
            missing_count=sum(value["volume"] is None for value in price_data[-252:]),
        ),
        _chart(
            "drawdown",
            "Risk",
            "line",
            "ドローダウン",
            fields=("close",),
            unit="ratio",
            period="from rolling peak",
            data=drawdown[-252:],
        ),
        _chart(
            "rolling_volatility_20d",
            "Risk",
            "line",
            "20営業日ローリング・ボラティリティ",
            fields=("close",),
            unit="annualized_ratio",
            period="20 trading days",
            data=rolling_volatility[-252:],
            missing_count=sum(value["value"] is None for value in rolling_volatility[-252:]),
        ),
        _chart(
            "daily_liquidity",
            "Risk",
            "line",
            "日次出来高",
            fields=("volume",),
            unit="split_adjusted_shares",
            period="daily",
            data=liquidity[-252:],
            missing_count=sum(value["value"] is None for value in liquidity[-252:]),
        ),
        _chart(
            "benchmark_relative",
            "Overview",
            "line",
            "ベンチマーク推移",
            fields=("close",),
            unit="index_or_proxy_points",
            period="daily",
            data=benchmarks[-1000:],
        ),
        _chart(
            "events",
            "Events",
            "horizontal_bar",
            "企業イベント",
            fields=("event_type", "effective_date"),
            unit="event_specific",
            period="effective date",
            data=events,
            missing_count=0,
        ),
    ]
    for period in ("annual", "quarterly"):
        selected = [value for value in financial_rows if value["period"] == period]
        charts.append(
            _chart(
                f"financials_{period}",
                "Financials",
                "horizontal_bar",
                "年次財務事実" if period == "annual" else "四半期財務事実",
                fields=("concept", "value"),
                unit="reporting_currency_or_ratio_by_definition",
                period=period,
                data=selected,
            )
        )
    return {
        "schema": "explorer-data/v1",
        "object_type": "security_research",
        "object_id": manifest["research_id"],
        "title": "Security Research Explorer",
        "locale": "ja",
        "sections": ["Overview", "Risk", "Financials", "Events", "Evidence"],
        "charts": charts,
        "evidence": {"company": company, "quality": quality},
    }


def render_explorer(document: Mapping[str, Any]) -> str:
    """Render one shared no-CDN Explorer with accessible SVG and table fallbacks."""

    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    payload = payload.replace("</", "<\\/")
    title = html.escape(str(document["title"]))
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#f5f7fb;--panel:#fff;--text:#172033;--muted:#64748b;--line:#d9e1ec;--accent:#1769aa;--positive:#167d55;--negative:#b42318}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111827;--panel:#182235;--text:#e7edf6;--muted:#a5b4c7;--line:#334155;--accent:#60a5fa;--positive:#4ade80;--negative:#fb7185}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,sans-serif}}
header{{padding:24px clamp(16px,4vw,48px);background:var(--panel);border-bottom:1px solid var(--line)}}h1{{margin:0 0 4px;font-size:24px}}.muted{{color:var(--muted);overflow-wrap:anywhere}}
nav{{display:flex;gap:8px;overflow:auto;padding:12px clamp(16px,4vw,48px);position:sticky;top:0;background:var(--bg);z-index:2}}
button,input,select{{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 12px}}button[aria-selected=true]{{background:var(--accent);color:#fff}}
main{{padding:0 clamp(16px,4vw,48px) 48px}}section{{display:none}}section.active{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr));gap:16px}}
.chart{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0}}.chart h2{{font-size:16px;margin:0}}.meta{{color:var(--muted);font-size:12px;margin:2px 0 12px}}svg{{width:100%;height:280px;overflow:visible}}.axis{{stroke:var(--line)}}.mark{{fill:var(--accent);stroke:var(--accent)}}.zero{{stroke:var(--muted);stroke-dasharray:4 3}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{padding:7px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}.table-wrap{{overflow:auto;max-height:520px}}
.full{{grid-column:1/-1}}.toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}}.empty{{padding:40px 12px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:10px}}
</style></head><body><header><h1>{title}</h1><div class="muted">ID: {html.escape(str(document["object_id"]))}</div></header>
<nav id="tabs" aria-label="Explorer sections"></nav><main id="main"></main>
<script id="explorer-data" type="application/json">{payload}</script><script>
const D=JSON.parse(document.getElementById('explorer-data').textContent);const main=document.getElementById('main'),tabs=document.getElementById('tabs');
const esc=v=>String(v??'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
function table(rows){{if(!rows.length)return '<div class="empty">表示できる観測がありません。</div>';const keys=[...new Set(rows.flatMap(Object.keys))];return '<div class="table-wrap"><table><thead><tr>'+keys.map(k=>`<th>${{esc(k)}}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+keys.map(k=>`<td>${{esc(typeof r[k]==='object'?JSON.stringify(r[k]):r[k])}}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>'}}
function svg(chart){{const rows=chart.data;if(rows.length<2)return '';const W=640,H=260,P=36;let out=`<svg viewBox="0 0 ${{W}} ${{H}}" role="img" aria-label="${{esc(chart.title)}}"><line class="axis" x1="${{P}}" y1="${{H-P}}" x2="${{W-P}}" y2="${{H-P}}"/>`;
if(chart.chart_type==='scatter'){{const xs=rows.map(r=>+r.x),ys=rows.map(r=>+r.y),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);rows.forEach(r=>{{const x=P+(+r.x-xmin)/(xmax-xmin||1)*(W-2*P),y=H-P-(+r.y-ymin)/(ymax-ymin||1)*(H-2*P);out+=`<circle class="mark" cx="${{x}}" cy="${{y}}" r="3"><title>${{esc(r.label)}}: ${{r.x}}, ${{r.y}}</title></circle>`}})}}
else if(chart.chart_type==='line'){{const keys=chart.fields.filter(k=>rows.some(r=>Number.isFinite(+r[k])));if(!keys.length&&rows.some(r=>Number.isFinite(+r.value)))keys.push('value');const vals=keys.flatMap(k=>rows.map(r=>+r[k])).filter(Number.isFinite);if(vals.length){{const lo=Math.min(...vals),hi=Math.max(...vals),patterns=['','6 3','2 3','8 2 2 2'];keys.forEach((key,j)=>{{const pts=rows.map((r,i)=>Number.isFinite(+r[key])?`${{P+i/(rows.length-1)*(W-2*P)}},${{H-P-(+r[key]-lo)/(hi-lo||1)*(H-2*P)}}`:null).filter(Boolean).join(' ');out+=`<polyline fill="none" class="mark" stroke-width="${{j?1.5:2.5}}" stroke-dasharray="${{patterns[j%patterns.length]}}" points="${{pts}}"><title>${{esc(key)}}</title></polyline>`}})}}}}
else if(chart.chart_type==='heatmap'){{const xs=[...new Set(rows.map(r=>r.x))],ys=[...new Set(rows.map(r=>r.y))],vals=rows.map(r=>Math.abs(+(r.value??0))),max=Math.max(...vals,1),cw=(W-2*P)/Math.max(xs.length,1),ch=(H-2*P)/Math.max(ys.length,1);rows.forEach(r=>{{const x=P+xs.indexOf(r.x)*cw,y=P+ys.indexOf(r.y)*ch,opacity=.15+.85*Math.abs(+(r.value??0))/max;out+=`<rect class="mark" x="${{x}}" y="${{y}}" width="${{cw-2}}" height="${{ch-2}}" opacity="${{opacity}}"><title>${{esc(r.x)}} / ${{esc(r.y)}}: ${{esc(r.value)}} (n=${{r.count}})</title></rect>`}})}}
else if(chart.chart_type==='box_plot'){{const vals=rows.map(r=>+r.value).filter(Number.isFinite).sort((a,b)=>a-b),q=p=>vals[Math.min(vals.length-1,Math.floor((vals.length-1)*p))];if(vals.length){{const lo=vals[0],q1=q(.25),med=q(.5),q3=q(.75),hi=vals.at(-1),scale=v=>P+(v-lo)/(hi-lo||1)*(W-2*P);out+=`<line class="mark" x1="${{scale(lo)}}" y1="130" x2="${{scale(hi)}}" y2="130"/><rect class="mark" fill="none" x="${{scale(q1)}}" y="90" width="${{scale(q3)-scale(q1)}}" height="80"/><line class="mark" x1="${{scale(med)}}" y1="90" x2="${{scale(med)}}" y2="170"/>`}}}}
else{{const vals=rows.map(r=>+(r.value??0)),max=Math.max(...vals.map(Math.abs),1),bw=(W-2*P)/rows.length;rows.forEach((r,i)=>{{const h=Math.abs(+(r.value??0))/max*(H-2*P),x=P+i*bw+2,y=H-P-h;out+=`<rect class="mark" x="${{x}}" y="${{y}}" width="${{Math.max(1,bw-4)}}" height="${{h}}"><title>${{esc(r.label??r.y??'')}}: ${{esc(r.value)}}</title></rect>`}})}}return out+'</svg>'}}
function chartCard(c){{const visual=c.observation_count>=2?svg(c):'';const fallback=table(c.fallback_table);return `<article class="chart"><h2>${{esc(c.title)}}</h2><div class="meta">単位: ${{esc(c.unit)}} · 期間: ${{esc(c.period??'—')}} · 観測: ${{c.observation_count}} · 欠損: ${{c.missing_count}}</div>${{visual||fallback}}${{visual?`<details><summary>表データ</summary>${{fallback}}</details>`:''}}</article>`}}
function securities(section){{const rows=D.securities||[],unique=(fn)=>[...new Set(rows.flatMap(fn).filter(Boolean))].sort(),options=(values,label)=>`<option value="">${{label}}</option>`+values.map(v=>`<option>${{esc(v)}}</option>`).join(''),searchText=r=>[r.instrument_id,r.provider_symbol,r.market,r.instrument?.mic,r.values.name,r.values.sector,r.values.industry,r.values.exchange,...r.memberships].filter(Boolean).join(' ').toLowerCase();section.classList.add('full');section.innerHTML=`<article class="chart full"><h2>銘柄</h2><div class="toolbar"><input id="search" aria-label="銘柄検索" placeholder="銘柄・名称・業種を検索"><select id="market"><option value="">全市場</option><option value="jp">JP</option><option value="us">US</option></select><select id="index">${{options(unique(r=>r.memberships),'全指数')}}</select><select id="sector">${{options(unique(r=>[r.values.sector]),'全セクター')}}</select><select id="currency">${{options(unique(r=>[r.values.currency]),'全通貨')}}</select><select id="domain"><option value="">主要列</option>${{options(unique(r=>[]).concat(['return','trend','momentum','risk','liquidity','valuation','profitability']),'全ドメイン').replace('<option value="">全ドメイン</option>','')}}</select><select id="sort"><option value="instrument_id:asc">銘柄ID順</option><option value="return_20d:desc">20日リターン降順</option><option value="volatility_60d:asc">60日ボラ昇順</option><option value="trailing_pe:asc">PER昇順</option></select></div><div id="security-count" class="meta"></div><div id="security-table"></div><h2>一時比較</h2><div class="toolbar"><input id="compare-ids" aria-label="比較する銘柄ID" placeholder="XNAS:AAPL, XNAS:MSFT"><button id="compare-button">比較</button></div><div id="comparison" class="meta">同一市場・同一通貨の銘柄IDを入力してください。保存や再計算は行いません。</div></article>`;const get=id=>section.querySelector('#'+id);const draw=()=>{{const q=get('search').value.toLowerCase(),m=get('market').value,idx=get('index').value,sec=get('sector').value,cur=get('currency').value,domain=get('domain').value,[sortField,direction]=get('sort').value.split(':');const domainFields=domain?D.field_definitions.filter(f=>f.group===domain).map(f=>f.name):['name','close','currency','sector','return_5d','return_20d','return_60d','volatility_60d','atr_14_ratio','price_as_of'];const filtered=rows.filter(r=>(!m||r.market===m)&&(!idx||r.memberships.includes(idx))&&(!sec||r.values.sector===sec)&&(!cur||r.values.currency===cur)&&searchText(r).includes(q)).sort((a,b)=>{{const av=sortField==='instrument_id'?a.instrument_id:+(a.values[sortField]??NaN),bv=sortField==='instrument_id'?b.instrument_id:+(b.values[sortField]??NaN);if(Number.isNaN(av))return 1;if(Number.isNaN(bv))return -1;return (av<bv?-1:av>bv?1:0)*(direction==='desc'?-1:1)}});get('security-count').textContent=`該当 ${{filtered.length}} / ${{rows.length}}`;const projected=filtered.map(r=>({{instrument_id:r.instrument_id,market:r.market,memberships:r.memberships.join(','),...Object.fromEntries(domainFields.map(k=>[k,r.values[k]??r.missing[k]??null])),research_command:`marketsieve research build ${{r.instrument_id}} --snapshot ${{D.object_id}} --evidence company --evidence financials --evidence price --history-days 365`}}));get('security-table').innerHTML=table(projected)}};['search','market','index','sector','currency','domain','sort'].forEach(id=>{{get(id).oninput=draw;get(id).onchange=draw}});get('compare-button').onclick=()=>{{const ids=get('compare-ids').value.split(',').map(v=>v.trim()).filter(Boolean),selected=ids.map(id=>rows.find(r=>r.instrument_id===id)).filter(Boolean),markets=new Set(selected.map(r=>r.market)),currencies=new Set(selected.map(r=>r.values.currency));const target=get('comparison');if(selected.length<2){{target.innerHTML='<div class="empty">2銘柄以上の有効なIDが必要です。</div>';return}}if(markets.size!==1||currencies.size!==1){{target.innerHTML='<div class="empty">市場または通貨が異なるため比較できません。</div>';return}}target.innerHTML=table(selected.map(r=>({{instrument_id:r.instrument_id,name:r.values.name,close:r.values.close,return_20d:r.values.return_20d,volatility_60d:r.values.volatility_60d,atr_14_ratio:r.values.atr_14_ratio,trailing_pe:r.values.trailing_pe,return_on_equity:r.values.return_on_equity}})))}};draw()}}
D.sections.forEach((name,i)=>{{const b=document.createElement('button');b.textContent=name;b.setAttribute('aria-selected',String(i===0));b.onclick=()=>{{document.querySelectorAll('main section').forEach(s=>s.classList.toggle('active',s.dataset.section===name));tabs.querySelectorAll('button').forEach(x=>x.setAttribute('aria-selected',String(x===b)))}};tabs.appendChild(b);const s=document.createElement('section');s.dataset.section=name;if(i===0)s.classList.add('active');D.charts.filter(c=>c.section===name).forEach(c=>s.insertAdjacentHTML('beforeend',chartCard(c)));if(name==='Securities')securities(s);if(name==='Evidence')s.insertAdjacentHTML('beforeend','<article class="chart full"><h2>Evidence</h2>'+table([D.evidence])+'</article>');main.appendChild(s)}});
</script></body></html>"""
