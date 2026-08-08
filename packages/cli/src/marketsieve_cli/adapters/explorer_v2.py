"""Reference-only Explorer contract and renderer for immutable evidence objects."""

# ruff: noqa: E501

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import Any

EXPLORER_SCHEMA = "explorer-data/v2"
RENDERER_VERSION = "marketsieve-explorer/v2"


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
            "object_contract": "market-snapshot/v7",
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
            "quality": {"path": "quality.json", "format": "json"},
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


def render_explorer(document: Mapping[str, Any]) -> str:
    """Render the shared no-CDN shell; evidence is loaded from sibling authorities."""

    metadata = document["metadata"]
    title = html.escape(str(metadata["title"]))
    return _HTML.replace("__TITLE__", title)


_HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{color-scheme:light dark;--bg:#f4f7fb;--panel:#fff;--panel2:#f8fafc;--text:#182234;--muted:#617086;--line:#d8e0ea;--accent:#1769aa;--accent2:#67a8d8;--pos:#127451;--neg:#b42318;--warn:#a15c00;--shadow:0 8px 28px rgba(22,34,52,.08)}
@media(prefers-color-scheme:dark){:root{--bg:#0f1724;--panel:#172235;--panel2:#111b2b;--text:#e8eef7;--muted:#a9b7ca;--line:#324157;--accent:#66b5ef;--accent2:#407aa5;--pos:#54d39a;--neg:#ff8791;--warn:#f4b75e;--shadow:none}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,-apple-system,sans-serif}button,input,select{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 11px}button{cursor:pointer}button:hover{border-color:var(--accent)}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 35%,transparent);outline-offset:2px}
header{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:22px clamp(14px,4vw,48px);background:var(--panel);border-bottom:1px solid var(--line)}header>div{min-width:0}h1{font-size:24px;margin:0 0 5px}.sub,.meta{color:var(--muted);font-size:12px}.sub{overflow-wrap:anywhere}.header-actions{display:flex;gap:8px;flex-wrap:wrap}.filters{display:grid;grid-template-columns:minmax(180px,2fr) repeat(5,minmax(110px,1fr));gap:8px;padding:12px clamp(14px,4vw,48px);background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}.filters input,.filters select{width:100%}
nav{display:flex;gap:7px;overflow:auto;padding:12px clamp(14px,4vw,48px)}nav button[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:#fff}main{padding:0 clamp(14px,4vw,48px) 48px}.section{display:none}.section.active{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr));gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0;box-shadow:var(--shadow)}.card h2{font-size:16px;margin:0}.card.full{grid-column:1/-1}.chart-meta{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin:3px 0 10px}.chart-frame{min-height:280px}.empty{padding:36px 12px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:10px}svg{width:100%;height:280px}.axis{stroke:var(--line)}.mark{fill:var(--accent);stroke:var(--accent)}.zero{stroke:var(--muted);stroke-dasharray:4 4}.positive{fill:var(--pos)}.negative{fill:var(--neg)}
.table-wrap{overflow:auto;max-height:560px;border:1px solid var(--line);border-radius:10px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:8px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{position:sticky;top:0;background:var(--panel2);z-index:1}tbody tr:hover{background:color-mix(in srgb,var(--accent) 7%,transparent)}.toolbar,.pager,.compare{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}.pager{justify-content:space-between}.badge{display:inline-block;padding:2px 7px;border-radius:999px;background:var(--panel2);border:1px solid var(--line);font-size:11px}.drawer{position:fixed;inset:0 0 0 auto;width:min(520px,100%);background:var(--panel);border-left:1px solid var(--line);z-index:20;padding:20px;overflow:auto;box-shadow:-10px 0 30px rgba(0,0,0,.18)}.drawer[hidden]{display:none}.drawer-head{display:flex;justify-content:space-between;gap:10px}.drawer pre,.handoff{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--panel2);padding:10px;border-radius:9px;border:1px solid var(--line)}details{margin-top:10px}summary{cursor:pointer}.error{color:var(--neg)}
@media(max-width:900px){.filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}header{display:block}.header-actions{margin-top:10px}}@media(max-width:520px){.filters{position:static;grid-template-columns:1fr}.filters input{grid-column:auto}.section.active{display:block}.card{margin-bottom:12px}h1{font-size:20px}.drawer{width:100%}}
</style></head><body>
<header><div><h1 id="title">__TITLE__</h1><div id="identity" class="sub">読み込み中</div></div><div class="header-actions"><button id="copy-state">状態JSONをコピー</button><button id="copy-cli">CLIをコピー</button></div></header>
<div class="filters"><input id="search" placeholder="銘柄ID・名称・業種を検索" aria-label="銘柄検索"><select id="market" aria-label="市場"><option value="">全市場</option><option value="jp">日本</option><option value="us">米国</option></select><select id="index" aria-label="指数"><option value="">全指数</option></select><select id="currency" aria-label="通貨"><option value="">全通貨</option></select><select id="sector" aria-label="セクター"><option value="">全セクター</option></select><select id="industry" aria-label="業種"><option value="">全業種</option></select></div>
<nav id="tabs" aria-label="Explorer sections"></nav><main id="main"></main><aside id="drawer" class="drawer" hidden aria-label="銘柄詳細"></aside>
<script>
'use strict';
const $=s=>document.querySelector(s), esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>{const n=Number(v);return Number.isFinite(n)?n:null}, median=a=>{if(!a.length)return null;const x=[...a].sort((p,q)=>p-q),m=Math.floor(x.length/2);return x.length%2?x[m]:(x[m-1]+x[m])/2};
const load=async source=>{const r=await fetch(source.path,{cache:'no-store'});if(!r.ok)throw new Error(`${source.path}: HTTP ${r.status}`);const text=await r.text();return source.format==='jsonl'?text.split(/\r?\n/).filter(Boolean).map(line=>JSON.parse(line)):JSON.parse(text)};
const format=(v,unit)=>{const n=num(v);if(n===null)return v??'—';if(['ratio','bounded_ratio','annualized_ratio'].includes(unit))return new Intl.NumberFormat('ja-JP',{style:'percent',maximumFractionDigits:2}).format(n);if(unit==='multiple')return `${new Intl.NumberFormat('ja-JP',{maximumFractionDigits:2}).format(n)}倍`;return new Intl.NumberFormat('ja-JP',{maximumFractionDigits:3}).format(n)};
let C,D={},rows=[],filtered=[],active='overview',page=1,pageSize=50,selected=[],fieldMap=new Map();
function marketOf(r){return r.instrument?.mic==='XTKS'?'jp':'us'}
function state(){return{schema:'explorer-state/v1',object_id:C.metadata.object_id,section:active,filters:{search:$('#search').value,market:$('#market').value,index:$('#index').value,currency:$('#currency').value,sector:$('#sector').value,industry:$('#industry').value},page_size:pageSize,selected_instrument_ids:selected}}
function saveState(){location.hash=encodeURIComponent(JSON.stringify(state()))}
function restoreState(){if(!location.hash)return;try{const s=JSON.parse(decodeURIComponent(location.hash.slice(1)));if(s.schema!=='explorer-state/v1'||s.object_id!==C.metadata.object_id)return;active=s.section||active;for(const [k,v] of Object.entries(s.filters||{})){const e=$('#'+k);if(e)e.value=v}pageSize=[25,50,100].includes(s.page_size)?s.page_size:50;selected=Array.isArray(s.selected_instrument_ids)?s.selected_instrument_ids.slice(0,5):[]}catch{location.hash=''}}
function options(id,values,label){const e=$('#'+id);e.innerHTML=`<option value="">${esc(label)}</option>`+[...new Set(values.filter(Boolean))].sort().map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')}
function applyFilters(){const q=$('#search').value.trim().toLowerCase(),m=$('#market').value,idx=$('#index').value,cur=$('#currency').value,sec=$('#sector').value,ind=$('#industry').value;filtered=rows.filter(r=>{const v=r.values||{},text=[r.instrument_id,r.provider_symbol,v.name,v.sector,v.industry,v.exchange,...(r.memberships||[])].filter(Boolean).join(' ').toLowerCase();return(!q||text.includes(q))&&(!m||marketOf(r)===m)&&(!idx||(r.memberships||[]).includes(idx))&&(!cur||v.currency===cur)&&(!sec||v.sector===sec)&&(!ind||v.industry===ind)});page=1;render();saveState()}
function counts(source,present,marks,missing=0,na=0,excluded=0){return`元観測 ${source} · 描画 ${marks} · 有効 ${present} · 欠損 ${missing} · 適用外 ${na} · 除外 ${excluded}`}
function histogram(field,bins=12){const values=filtered.map(r=>num(r.values?.[field])).filter(v=>v!==null),missing=filtered.length-values.length;if(!values.length)return{data:[],present:0,missing};const lo=Math.min(...values),hi=Math.max(...values);if(lo===hi)return{data:[{label:String(lo),value:values.length}],present:values.length,missing};const width=(hi-lo)/bins,cs=Array(bins).fill(0);for(const v of values)cs[Math.min(Math.floor((v-lo)/width),bins-1)]++;return{data:cs.map((value,i)=>({label:`${(lo+width*i).toFixed(3)}-${(lo+width*(i+1)).toFixed(3)}`,value})),present:values.length,missing}}
function viewData(v){if(v.source==='quality'){if(v.id==='domain_coverage')return{data:Object.entries(D.quality.domains||{}).map(([label,x])=>({label,value:num(x.coverage),count:x.applicable})),present:Object.keys(D.quality.domains||{}).length,missing:0};return{data:Object.entries(D.quality.freshness||{}).flatMap(([label,x])=>['median','p95','maximum'].filter(k=>x?.[k]!=null).map(k=>({label:`${label}:${k}`,value:num(x[k])}))),present:Object.keys(D.quality.freshness||{}).length,missing:0}}if(v.source==='market_indicators'){const data=D.market_indicators.flatMap((x,i)=>x.observations.map(o=>({date:o.date,value:num(o.close??o.value),series:x.name||x.indicator_id,index:i})));return{data,present:data.length,missing:D.market_indicators.filter(x=>!x.observations.length).length}}if(v.type==='histogram')return histogram(v.fields[0]);if(v.id==='market_breadth'){const data=v.fields.map(f=>({label:fieldMap.get(f)?.name||f,value:filtered.length?filtered.filter(r=>num(r.values?.[f])>0).length/filtered.length:null}));return{data,present:filtered.length,missing:0}}if(v.type==='scatter'){const [xf,yf]=v.fields,data=[];let missing=0;for(const r of filtered){const x=num(r.values?.[xf]),y=num(r.values?.[yf]);if(x===null||y===null){missing++;continue}data.push({label:r.instrument_id,x,y})}return{data,present:data.length,missing}}if(v.type==='heatmap'){const groups=new Map;for(const r of filtered){const sector=r.values?.sector,value=num(r.values?.return_20d);if(!sector||value===null)continue;const key=`${marketOf(r)}|${sector}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(value)}const data=[...groups].map(([key,values])=>{const [x,y]=key.split('|');return{x,y,value:median(values),count:values.length}});return{data,present:data.reduce((n,x)=>n+x.count,0),missing:filtered.length-data.reduce((n,x)=>n+x.count,0)}}return{data:[],present:0,missing:0}}
function svg(type,data){if(!data.length)return'';const W=720,H=280,p=40,vals=data.flatMap(d=>[num(d.value),num(d.x),num(d.y)]).filter(v=>v!==null),min=Math.min(0,...vals),max=Math.max(0,...vals),scale=v=>H-p-(v-min)/(max-min||1)*(H-2*p);if(type==='scatter'){const xs=data.map(d=>d.x),ys=data.map(d=>d.y),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);return`<svg viewBox="0 0 ${W} ${H}" role="img"><line class="axis" x1="${p}" y1="${H-p}" x2="${W-p}" y2="${H-p}"/><line class="axis" x1="${p}" y1="${p}" x2="${p}" y2="${H-p}"/>${data.map(d=>`<circle class="mark" cx="${p+(d.x-xmin)/(xmax-xmin||1)*(W-2*p)}" cy="${H-p-(d.y-ymin)/(ymax-ymin||1)*(H-2*p)}" r="3"><title>${esc(d.label)}: ${d.x}, ${d.y}</title></circle>`).join('')}</svg>`}if(type==='line'){const groups=Map.groupBy?Map.groupBy(data,d=>d.series||'value'):new Map([['value',data]]);return`<svg viewBox="0 0 ${W} ${H}" role="img">${[...groups.values()].map((g,gi)=>`<polyline fill="none" stroke="${gi?'var(--accent2)':'var(--accent)'}" stroke-width="2" points="${g.map((d,i)=>`${p+i/(g.length-1||1)*(W-2*p)},${scale(d.value)}`).join(' ')}"/>`).join('')}</svg>`}if(type==='heatmap'){const sectors=[...new Set(data.map(d=>d.y))].sort(),cellW=(W-2*p)/2,chartH=Math.max(H,2*p+sectors.length*18),cellH=(chartH-2*p)/Math.max(1,sectors.length);return`<svg viewBox="0 0 ${W} ${chartH}" role="img">${data.map(d=>`<rect x="${p+(d.x==='us'?cellW:0)}" y="${p+sectors.indexOf(d.y)*cellH}" width="${cellW-2}" height="${cellH-2}" fill="${d.value>=0?'var(--pos)':'var(--neg)'}" opacity="${Math.min(.9,.25+Math.abs(d.value)*8)}"><title>${esc(d.x)} / ${esc(d.y)}: ${format(d.value,'ratio')} (${d.count})</title></rect>`).join('')}</svg>`}const bw=(W-2*p)/data.length;return`<svg viewBox="0 0 ${W} ${H}" role="img"><line class="zero" x1="${p}" y1="${scale(0)}" x2="${W-p}" y2="${scale(0)}"/>${data.map((d,i)=>{const y=scale(Math.max(0,d.value)),z=scale(Math.min(0,d.value));return`<rect class="${d.value>=0?'positive':'negative'}" x="${p+i*bw+2}" y="${Math.min(y,z)}" width="${Math.max(1,bw-4)}" height="${Math.max(1,Math.abs(z-y))}"><title>${esc(d.label)}: ${d.value}</title></rect>`}).join('')}</svg>`}
function table(data,limit=200){if(!data.length)return'<div class="empty">表示できるデータがありません。</div>';const keys=[...new Set(data.slice(0,limit).flatMap(Object.keys))];return`<div class="table-wrap"><table><thead><tr>${keys.map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${data.slice(0,limit).map(r=>`<tr>${keys.map(k=>`<td>${esc(r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function chart(v){const x=viewData(v),visual=x.data.length>=2?svg(v.type,x.data):'';const source=v.source==='securities'?filtered.length:x.present+x.missing;return`<article class="card"><h2>${esc(v.title)}</h2><div class="chart-meta"><span>単位 ${esc(v.unit)}</span><span>期間 ${esc(v.period||'—')}</span><span>${counts(source,x.present,x.data.length,x.missing)}</span></div><div class="chart-frame">${visual||table(x.data)}</div>${visual?`<details><summary>表データ</summary>${table(x.data)}</details>`:''}</article>`}
function valueCell(r,f){if(r.values?.[f]!=null)return format(r.values[f],fieldMap.get(f)?.unit);return r.missing?.[f]||'未取得'}
function securities(){const cols=C.column_sets.main,start=(page-1)*pageSize,visible=filtered.slice(start,start+pageSize),pages=Math.max(1,Math.ceil(filtered.length/pageSize));return`<article class="card full"><h2>銘柄</h2><div class="toolbar"><label>表示件数 <select id="page-size">${[25,50,100].map(n=>`<option ${n===pageSize?'selected':''}>${n}</option>`).join('')}</select></label><span class="meta">該当 ${filtered.length} / ${rows.length}</span></div>${table(visible.map(r=>({instrument_id:r.instrument_id,market:marketOf(r),memberships:(r.memberships||[]).join(', '),...Object.fromEntries(cols.map(f=>[fieldMap.get(f)?.name||f,valueCell(r,f)]))})),pageSize)}<div class="pager"><button id="prev" ${page<=1?'disabled':''}>前へ</button><span>${page} / ${pages}</span><button id="next" ${page>=pages?'disabled':''}>次へ</button></div><h2>一時比較</h2><div class="compare"><span>${selected.map(x=>`<span class="badge">${esc(x)}</span>`).join('')||'銘柄詳細から最大5銘柄を選択'}</span><button id="copy-compare" ${selected.length<2?'disabled':''}>比較CLIをコピー</button></div></article>`}
function detail(id){const r=rows.find(x=>x.instrument_id===id);if(!r)return;const v=r.values||{},command=C.actions.research.replace('{instrument_id}',r.instrument_id).replace('{object_id}',C.metadata.object_id),inSelection=selected.includes(id);$('#drawer').innerHTML=`<div class="drawer-head"><div><h2>${esc(v.name||id)}</h2><div class="meta">${esc(id)} · ${esc(r.provider_symbol)} · ${esc((r.memberships||[]).join(', '))}</div></div><button id="close-drawer">閉じる</button></div><h3>主要指標</h3>${table(C.column_sets.main.map(f=>({field:f,label:fieldMap.get(f)?.name||f,value:valueCell(r,f)})))}<h3>個別調査</h3><pre>${esc(command)}</pre><div class="toolbar"><button id="copy-research">Research CLIをコピー</button><button id="toggle-compare">${inSelection?'比較から外す':'比較へ追加'}</button></div>`;$('#drawer').hidden=false;$('#close-drawer').onclick=()=>$('#drawer').hidden=true;$('#copy-research').onclick=()=>copy(command);$('#toggle-compare').onclick=()=>{if(inSelection)selected=selected.filter(x=>x!==id);else{if(selected.length>=5)return alert('比較は最大5銘柄です。');const candidate=[...selected,id].map(x=>rows.find(r=>r.instrument_id===x)),markets=new Set(candidate.map(marketOf)),currencies=new Set(candidate.map(x=>x.values?.currency));if(markets.size>1||currencies.size>1)return alert('同一市場・同一通貨の銘柄だけ比較できます。');selected.push(id)}saveState();detail(id);render()}}
async function copy(text){try{await navigator.clipboard.writeText(text)}catch{const w=window.open('','copy');w.document.body.innerHTML=`<pre>${esc(text)}</pre>`}}
function render(){document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.id===active)));const section=$('#section-'+active);document.querySelectorAll('.section').forEach(s=>{s.classList.toggle('active',s===section);if(s!==section)s.replaceChildren()});if(active==='securities')section.innerHTML=securities();else section.innerHTML=C.views.filter(v=>v.section===active).map(chart).join('')||'<div class="card empty">表示項目はありません。</div>';if(active==='securities'){section.querySelectorAll('tbody tr').forEach((tr,i)=>tr.onclick=()=>detail(filtered[(page-1)*pageSize+i].instrument_id));$('#page-size').onchange=e=>{pageSize=Number(e.target.value);page=1;render();saveState()};$('#prev').onclick=()=>{page--;render()};$('#next').onclick=()=>{page++;render()};$('#copy-compare').onclick=()=>copy(C.actions.compare.replace('{instrument_ids}',selected.join(' ')).replace('{object_id}',C.metadata.object_id))}}
async function init(){C=await(await fetch('explorer-data.json',{cache:'no-store'})).json();if(C.schema!=='explorer-data/v2')throw new Error('unsupported Explorer contract');const loaded=await Promise.all(Object.entries(C.sources).map(async([k,v])=>[k,await load(v)]));D=Object.fromEntries(loaded);rows=D.securities;fieldMap=new Map(C.field_catalog.map(f=>[f.name,f]));$('#title').textContent=C.metadata.title;$('#identity').textContent=`Snapshot ${C.metadata.object_id} · 作成 ${C.metadata.created_at} · yfinance ${C.metadata.source.version}`;options('index',rows.flatMap(r=>r.memberships||[]),'全指数');options('currency',rows.map(r=>r.values?.currency),'全通貨');options('sector',rows.map(r=>r.values?.sector),'全セクター');options('industry',rows.map(r=>r.values?.industry),'全業種');$('#tabs').innerHTML=C.sections.map(s=>`<button data-id="${s.id}" aria-selected="false">${esc(s.label)}</button>`).join('');$('#main').innerHTML=C.sections.map(s=>`<section id="section-${s.id}" class="section" aria-label="${esc(s.label)}"></section>`).join('');restoreState();document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{active=b.dataset.id;render();saveState()});['search','market','index','currency','sector','industry'].forEach(id=>{$('#'+id).oninput=applyFilters;$('#'+id).onchange=applyFilters});$('#copy-state').onclick=()=>copy(JSON.stringify(state(),null,2));$('#copy-cli').onclick=()=>copy(C.actions.query.replace('{object_id}',C.metadata.object_id));applyFilters()}
init().catch(e=>{$('#main').innerHTML=`<div class="card error"><h2>Explorerを読み込めませんでした</h2><pre>${esc(e.message)}</pre></div>`});
</script></body></html>
"""
