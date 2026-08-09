"""Reference-only Explorer contract and renderer for immutable evidence objects."""

# ruff: noqa: E501

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import Any

EXPLORER_SCHEMA = "explorer-data/v4"
RENDERER_VERSION = "marketsieve-explorer/v4"


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
            "object_contract": "market-snapshot/v8",
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
    return _HTML.replace("__TITLE__", title)


_HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{color-scheme:light dark;--bg:#f4f7fb;--panel:#fff;--panel2:#f8fafc;--text:#182234;--muted:#617086;--line:#d8e0ea;--accent:#1769aa;--accent2:#67a8d8;--pos:#127451;--neg:#b42318;--warn:#a15c00;--shadow:0 8px 28px rgba(22,34,52,.08)}
@media(prefers-color-scheme:dark){:root{--bg:#0f1724;--panel:#172235;--panel2:#111b2b;--text:#e8eef7;--muted:#a9b7ca;--line:#324157;--accent:#66b5ef;--accent2:#407aa5;--pos:#54d39a;--neg:#ff8791;--warn:#f4b75e;--shadow:none}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,-apple-system,sans-serif}button,input,select{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 11px}button{cursor:pointer}button:hover{border-color:var(--accent)}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 35%,transparent);outline-offset:2px}
header{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:22px clamp(14px,4vw,48px);background:var(--panel);border-bottom:1px solid var(--line)}header>div{min-width:0}h1{font-size:24px;margin:0 0 5px}.sub,.meta{color:var(--muted);font-size:12px}.sub{overflow-wrap:anywhere}.header-actions{display:flex;gap:8px;flex-wrap:wrap}.filters{display:grid;grid-template-columns:minmax(180px,2fr) repeat(5,minmax(110px,1fr));gap:8px;padding:12px clamp(14px,4vw,48px);background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}.filters input,.filters select{width:100%}
nav{display:flex;gap:7px;overflow:auto;padding:12px clamp(14px,4vw,48px)}nav button[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:#fff}main{padding:0 clamp(14px,4vw,48px) 48px}.section{display:none}.section.active{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr));gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0;box-shadow:var(--shadow)}.card h2{font-size:16px;margin:0}.card.full{grid-column:1/-1}.chart-meta{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin:3px 0 10px}.chart-frame{min-height:280px}.empty{padding:36px 12px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:10px}svg{width:100%;height:280px}.axis{stroke:var(--line)}.chart-label{fill:var(--muted);font-size:10px}.chart-value{fill:var(--text);font-size:10px}.mark{fill:var(--accent);stroke:var(--accent)}.zero{stroke:var(--muted);stroke-dasharray:4 4}.positive{fill:var(--pos)}.negative{fill:var(--neg)}
.table-wrap{overflow:auto;max-height:560px;border:1px solid var(--line);border-radius:10px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:8px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{position:sticky;top:0;background:var(--panel2);z-index:1}tbody tr:hover{background:color-mix(in srgb,var(--accent) 7%,transparent)}.toolbar,.pager,.compare,.chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}.chips{padding:0 clamp(14px,4vw,48px)}.pager{justify-content:space-between}.badge{display:inline-block;padding:2px 7px;border-radius:999px;background:var(--panel2);border:1px solid var(--line);font-size:11px}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;grid-column:1/-1}.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:13px}.kpi strong{display:block;font-size:22px}.drawer{position:fixed;inset:0 0 0 auto;width:min(520px,100%);background:var(--panel);border-left:1px solid var(--line);z-index:20;padding:20px;overflow:auto;box-shadow:-10px 0 30px rgba(0,0,0,.18)}.drawer[hidden]{display:none}.drawer-head{display:flex;justify-content:space-between;gap:10px}.drawer pre,.handoff{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--panel2);padding:10px;border-radius:9px;border:1px solid var(--line)}details{margin-top:10px}summary{cursor:pointer}.error{color:var(--neg)}
@media(max-width:900px){.filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}header{display:block}.header-actions{margin-top:10px}}@media(max-width:520px){.filters{position:static;grid-template-columns:1fr}.filters input{grid-column:auto}.section.active{display:block}.card{margin-bottom:12px}h1{font-size:20px}.drawer{width:100%}}
</style></head><body>
<header><div><h1 id="title">__TITLE__</h1><div id="identity" class="sub">読み込み中</div></div><div class="header-actions"><button id="copy-state">状態JSONをコピー</button><button id="copy-cli">CLIをコピー</button></div></header>
<div class="filters"><input id="search" placeholder="銘柄ID・名称・業種を検索" aria-label="銘柄検索"><select id="market" aria-label="市場"><option value="">全市場</option><option value="jp">日本</option><option value="us">米国</option></select><select id="index" aria-label="指数"><option value="">全指数</option></select><select id="currency" aria-label="通貨"><option value="">全通貨</option></select><select id="sector" aria-label="セクター"><option value="">全セクター</option></select><select id="industry" aria-label="業種"><option value="">全業種</option></select></div><div id="chips" class="chips" aria-live="polite"></div>
<nav id="tabs" aria-label="Explorer sections"></nav><main id="main"></main><aside id="drawer" class="drawer" hidden aria-label="銘柄詳細"></aside>
<script>
'use strict';
const $=s=>document.querySelector(s), esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>{const n=Number(v);return Number.isFinite(n)?n:null}, median=a=>{if(!a.length)return null;const x=[...a].sort((p,q)=>p-q),m=Math.floor(x.length/2);return x.length%2?x[m]:(x[m-1]+x[m])/2};
const load=async source=>{const r=await fetch(source.path,{cache:'no-store'});if(!r.ok)throw new Error(`${source.path}: HTTP ${r.status}`);const text=await r.text();return source.format==='jsonl'?text.split(/\r?\n/).filter(Boolean).map(line=>JSON.parse(line)):JSON.parse(text)};
const format=(v,unit)=>{const n=num(v);if(n===null)return v??'—';if(['ratio','bounded_ratio','annualized_ratio'].includes(unit))return new Intl.NumberFormat('ja-JP',{style:'percent',maximumFractionDigits:2}).format(n);if(unit==='multiple')return `${new Intl.NumberFormat('ja-JP',{maximumFractionDigits:2}).format(n)}倍`;return new Intl.NumberFormat('ja-JP',{maximumFractionDigits:3}).format(n)};
const UNIT_LABELS={ratio:'%',bounded_ratio:'%',annualized_ratio:'%',multiple:'倍',multiple_and_ratio:'横軸・縦軸の単位を参照',days:'日',count:'銘柄数',shares:'株',quote_currency:'銘柄通貨',definition_specific:'指標別',index_points:'指数ポイント',JPY_per_USD:'円/米ドル',percent:'%',USD_per_barrel:'米ドル/バレル',USD_per_troy_ounce:'米ドル/トロイオンス'};
const FIELD_LABELS={distance_sma_20:'SMA20超過率',distance_sma_200:'SMA200超過率',volatility_60d:'60営業日ボラティリティ',return_60d:'60営業日リターン',trailing_pe:'実績PER',earnings_growth:'利益成長率',price_to_book:'PBR',return_on_equity:'ROE',price_age_days:'株価経過日数',financial_age_days:'財務経過日数',financial:'財務',fundamental:'ファンダメンタルズ',identity:'識別',liquidity:'流動性',momentum:'モメンタム',price:'価格',profitability:'収益性',relative:'指数相対',return:'リターン',risk:'リスク',safety:'安全性',size:'規模',trend:'トレンド',valuation:'バリュエーション'};
const unitLabel=u=>UNIT_LABELS[u]||u||'—',fieldLabel=f=>FIELD_LABELS[f]||f,periodLabel=p=>String(p??'—').replaceAll('trading days','営業日').replaceAll('trading intervals','営業日').replaceAll('at retrieval','取得時点').replaceAll('Snapshot acquisition window','Snapshot取得期間').replaceAll('provider current / trailing','取得時点 / 直近実績'),coverageValue=v=>v&&typeof v==='object'?v.overall:v;
let C,D={},rows=[],filtered=[],active='overview',page=1,pageSize=50,selected=[],fieldMap=new Map();
function marketOf(r){return r.instrument?.mic==='XTKS'?'jp':'us'}
function state(){return{schema:'explorer-state/v1',object_id:C.metadata.object_id,section:active,filters:{search:$('#search').value,market:$('#market').value,index:$('#index').value,currency:$('#currency').value,sector:$('#sector').value,industry:$('#industry').value},page_size:pageSize,selected_instrument_ids:selected}}
function saveState(){location.hash=encodeURIComponent(JSON.stringify(state()))}
function restoreState(){if(!location.hash)return;try{const s=JSON.parse(decodeURIComponent(location.hash.slice(1)));if(s.schema!=='explorer-state/v1'||s.object_id!==C.metadata.object_id)return;active=s.section||active;for(const [k,v] of Object.entries(s.filters||{})){const e=$('#'+k);if(e)e.value=v}pageSize=[25,50,100].includes(s.page_size)?s.page_size:50;selected=Array.isArray(s.selected_instrument_ids)?s.selected_instrument_ids.slice(0,5):[]}catch{location.hash=''}}
function options(id,values,label){const e=$('#'+id);e.innerHTML=`<option value="">${esc(label)}</option>`+[...new Set(values.filter(Boolean))].sort().map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')}
function applyFilters(){const q=$('#search').value.trim().toLowerCase(),m=$('#market').value,idx=$('#index').value,cur=$('#currency').value,sec=$('#sector').value,ind=$('#industry').value;filtered=rows.filter(r=>{const v=r.values||{},text=[r.instrument_id,r.provider_symbol,v.name,v.sector,v.industry,v.exchange,...(r.memberships||[])].filter(Boolean).join(' ').toLowerCase();return(!q||text.includes(q))&&(!m||marketOf(r)===m)&&(!idx||(r.memberships||[]).includes(idx))&&(!cur||v.currency===cur)&&(!sec||v.sector===sec)&&(!ind||v.industry===ind)});page=1;render();saveState()}
function overviewCards(){const metrics=[['上昇銘柄比率','return_1d'],['SMA20超過率','distance_sma_20'],['SMA200超過率','distance_sma_200']],cards=metrics.map(([label,f])=>{const present=filtered.filter(r=>num(r.values?.[f])!==null),positive=present.filter(r=>num(r.values?.[f])>0).length;return`<div class="kpi"><span>${label}</span><strong>${present.length?format(positive/present.length,'ratio'):'—'}</strong><small>${positive} / ${present.length}</small></div>`});const values=filtered.map(r=>num(r.values?.return_20d)).filter(v=>v!==null);cards.push(`<div class="kpi"><span>20営業日リターン中央値</span><strong>${values.length?format(median(values),'ratio'):'—'}</strong><small>有効 ${values.length}</small></div>`);return`<div class="kpis">${cards.join('')}</div>`}
function counts(source,present,marks,missing=0,na=0,excluded=0){return`元観測 ${source} · 描画 ${marks} · 有効 ${present} · 欠損 ${missing} · 適用外 ${na} · 除外 ${excluded}`}
function histogram(field,bins=12){const values=filtered.map(r=>num(r.values?.[field])).filter(v=>v!==null),missing=filtered.length-values.length;if(!values.length)return{data:[],present:0,missing};const lo=Math.min(...values),hi=Math.max(...values);if(lo===hi)return{data:[{label:String(lo),value:values.length}],present:values.length,missing};const width=(hi-lo)/bins,cs=Array(bins).fill(0);for(const v of values)cs[Math.min(Math.floor((v-lo)/width),bins-1)]++;return{data:cs.map((value,i)=>({label:`${(lo+width*i).toFixed(3)}-${(lo+width*(i+1)).toFixed(3)}`,value})),present:values.length,missing}}
function viewData(v){if(v.source==='quality'){if(v.id==='domain_coverage')return{data:Object.entries(D.quality.domains||{}).map(([label,x])=>({label:fieldLabel(label),value:num(x.coverage),count:x.applicable})),present:Object.keys(D.quality.domains||{}).length,missing:0};return{data:Object.entries(D.quality.freshness||{}).flatMap(([label,x])=>['median','p95','maximum'].filter(k=>x?.[k]!=null).map(k=>({label:`${fieldLabel(label)} ${k==='median'?'中央値':k==='maximum'?'最大':'p95'}`,value:num(x[k])}))),present:Object.keys(D.quality.freshness||{}).length,missing:0}}if(v.source==='market_indicators'){const data=D.market_indicators.flatMap((x,i)=>x.observations.map(o=>({date:o.date,value:num(o.close??o.value),series:x.name||x.indicator_id,index:i,unit:x.unit,kind:x.kind})));return{data,present:data.length,missing:D.market_indicators.filter(x=>!x.observations.length).length}}if(v.type==='histogram')return histogram(v.fields[0]);if(v.id==='market_breadth'){const complete=filtered.filter(r=>v.fields.every(f=>num(r.values?.[f])!==null)),data=v.fields.map(f=>{const present=filtered.filter(r=>num(r.values?.[f])!==null),positive=present.filter(r=>num(r.values?.[f])>0).length;return{label:fieldLabel(f),value:present.length?positive/present.length:null,numerator:positive,denominator:present.length}});return{data,present:complete.length,missing:filtered.length-complete.length}}if(v.type==='scatter'){const [xf,yf]=v.fields,data=[];let missing=0;for(const r of filtered){const x=num(r.values?.[xf]),y=num(r.values?.[yf]);if(x===null||y===null){missing++;continue}data.push({label:r.instrument_id,x,y})}return{data,present:data.length,missing}}if(v.type==='heatmap'){const groups=new Map;for(const r of filtered){const sector=r.values?.sector,value=num(r.values?.return_20d);if(!sector||value===null)continue;const key=`${marketOf(r)}|${sector}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(value)}const data=[...groups].map(([key,values])=>{const [x,y]=key.split('|');return{x,y,value:median(values),count:values.length}});return{data,present:data.reduce((n,x)=>n+x.count,0),missing:filtered.length-data.reduce((n,x)=>n+x.count,0)}}return{data:[],present:0,missing:0}}
function ticks(lo,hi,n=4){return Array.from({length:n+1},(_,i)=>lo+(hi-lo)*i/n)}
function svg(type,data,v){if(!data.length)return'';const W=720,H=280,L=72,R=22,T=32,B=50,unit=v.unit,vals=data.map(d=>num(d.value)).filter(x=>x!==null),lo=Math.min(0,...vals),hi=Math.max(0,...vals),y=value=>H-B-(value-lo)/(hi-lo||1)*(H-T-B),yt=ticks(lo,hi),yTicks=yt.map(t=>`<g><line class="axis" x1="${L-4}" y1="${y(t)}" x2="${W-R}" y2="${y(t)}" opacity=".28"/><text class="chart-label" x="${L-7}" y="${y(t)+3}" text-anchor="end">${esc(format(t,type==='histogram'?'count':unit))}</text></g>`).join('');if(type==='scatter'){const xs=data.map(d=>d.x),ys=data.map(d=>d.y),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),xf=v.fields[0],yf=v.fields[1],xu=fieldMap.get(xf)?.unit||unit,yu=fieldMap.get(yf)?.unit||unit,x=t=>L+(t-xmin)/(xmax-xmin||1)*(W-L-R),sy=t=>H-B-(t-ymin)/(ymax-ymin||1)*(H-T-B);return`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="横軸 ${esc(fieldLabel(xf))}、縦軸 ${esc(fieldLabel(yf))}"><line class="axis" x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}"/><line class="axis" x1="${L}" y1="${T}" x2="${L}" y2="${H-B}"/>${ticks(xmin,xmax).map(t=>`<text class="chart-label" x="${x(t)}" y="${H-B+16}" text-anchor="middle">${esc(format(t,xu))}</text>`).join('')}${ticks(ymin,ymax).map(t=>`<text class="chart-label" x="${L-7}" y="${sy(t)+3}" text-anchor="end">${esc(format(t,yu))}</text>`).join('')}${xmin<=0&&xmax>=0?`<line class="zero" x1="${x(0)}" y1="${T}" x2="${x(0)}" y2="${H-B}"/>`:''}${ymin<=0&&ymax>=0?`<line class="zero" x1="${L}" y1="${sy(0)}" x2="${W-R}" y2="${sy(0)}"/>`:''}${data.map(d=>`<circle class="mark" cx="${x(d.x)}" cy="${sy(d.y)}" r="3"><title>${esc(d.label)}: ${format(d.x,xu)}, ${format(d.y,yu)}</title></circle>`).join('')}<text class="chart-value" x="${(L+W-R)/2}" y="${H-7}" text-anchor="middle">${esc(fieldLabel(xf))} (${esc(unitLabel(xu))})</text><text class="chart-value" x="14" y="${(T+H-B)/2}" transform="rotate(-90 14 ${(T+H-B)/2})" text-anchor="middle">${esc(fieldLabel(yf))} (${esc(unitLabel(yu))})</text></svg>`}if(type==='line'){const groups=Map.groupBy?Map.groupBy(data,d=>d.series||'value'):new Map([['value',data]]),dates=data.map(d=>d.date).filter(Boolean).sort();return`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="横軸 日付、縦軸 ${esc(unitLabel(unit))}"><line class="axis" x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}"/>${yTicks}${[...groups.entries()].map(([name,g],gi)=>`<polyline fill="none" stroke="${gi%2?'var(--accent2)':'var(--accent)'}" stroke-width="2" stroke-dasharray="${gi>1?'5 3':'none'}" points="${g.map((d,i)=>`${L+i/(g.length-1||1)*(W-L-R)},${y(d.value)}`).join(' ')}"><title>${esc(name)}</title></polyline>`).join('')}${[...groups.keys()].slice(0,5).map((name,i)=>`<text class="chart-value" x="${L+i*125}" y="17">${i+1}: ${esc(name)}</text>`).join('')}<text class="chart-label" x="${L}" y="${H-B+16}">${esc(dates[0]||'')}</text><text class="chart-label" x="${W-R}" y="${H-B+16}" text-anchor="end">${esc(dates.at(-1)||'')}</text><text class="chart-value" x="${(L+W-R)/2}" y="${H-7}" text-anchor="middle">日付</text><text class="chart-value" x="14" y="${(T+H-B)/2}" transform="rotate(-90 14 ${(T+H-B)/2})" text-anchor="middle">${esc(unitLabel(unit))}</text></svg>`}if(type==='heatmap'){const sectors=[...new Set(data.map(d=>d.y))].sort(),cellW=(W-L-R)/2,chartH=Math.max(H,T+B+sectors.length*20),cellH=(chartH-T-B)/Math.max(1,sectors.length);return`<svg viewBox="0 0 ${W} ${chartH}" role="img" aria-label="市場とセクター別の20営業日リターン中央値"><text class="chart-value" x="${L+cellW/2}" y="18" text-anchor="middle">日本</text><text class="chart-value" x="${L+cellW*1.5}" y="18" text-anchor="middle">米国</text>${sectors.map((s,i)=>`<text class="chart-label" x="${L-5}" y="${T+(i+.65)*cellH}" text-anchor="end">${esc(s)}</text>`).join('')}${data.map(d=>`<g><rect x="${L+(d.x==='us'?cellW:0)}" y="${T+sectors.indexOf(d.y)*cellH}" width="${cellW-2}" height="${cellH-2}" fill="${d.value>=0?'var(--pos)':'var(--neg)'}" opacity="${Math.min(.9,.25+Math.abs(d.value)*8)}"><title>${esc(d.x)} / ${esc(d.y)}: ${format(d.value,'ratio')} (${d.count})</title></rect><text x="${L+(d.x==='us'?cellW:0)+cellW/2}" y="${T+(sectors.indexOf(d.y)+.65)*cellH}" text-anchor="middle" fill="white" font-size="10">${esc(format(d.value,'ratio'))} · ${d.count}</text></g>`).join('')}</svg>`}if(type==='horizontal_bar'){const max=Math.max(...data.map(d=>Math.abs(d.value)),1e-9),rowH=Math.max(28,(H-T-B)/data.length),chartH=Math.max(H,T+B+rowH*data.length),barW=W-L-R;return`<svg viewBox="0 0 ${W} ${chartH}" role="img" aria-label="横軸 ${esc(unitLabel(unit))}">${data.map((d,i)=>{const yy=T+i*rowH,w=Math.abs(d.value)/max*barW;return`<text class="chart-label" x="${L-6}" y="${yy+rowH*.62}" text-anchor="end">${esc(d.label)}</text><rect class="${d.value>=0?'positive':'negative'}" x="${L}" y="${yy+4}" width="${w}" height="${rowH-9}"><title>${esc(d.label)}: ${format(d.value,unit)}</title></rect><text class="chart-value" x="${Math.min(W-R-2,L+w+5)}" y="${yy+rowH*.62}">${esc(format(d.value,unit))}${d.denominator!=null?` (${d.numerator}/${d.denominator})`:''}</text>`}).join('')}<text class="chart-value" x="${(L+W-R)/2}" y="${chartH-7}" text-anchor="middle">${esc(unitLabel(unit))}</text></svg>`}const bw=(W-L-R)/data.length;return`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="横軸 ${esc(unitLabel(unit))}、縦軸 銘柄数"><line class="axis" x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}"/>${yTicks}${data.map((d,i)=>{const yy=y(Math.max(0,d.value)),zz=y(Math.min(0,d.value));return`<rect class="${d.value>=0?'positive':'negative'}" x="${L+i*bw+2}" y="${Math.min(yy,zz)}" width="${Math.max(1,bw-4)}" height="${Math.max(1,Math.abs(zz-yy))}"><title>${esc(d.label)}: ${d.value}</title></rect>`}).join('')}<text class="chart-label" x="${L}" y="${H-B+16}">${esc(data[0]?.label||'')}</text><text class="chart-label" x="${W-R}" y="${H-B+16}" text-anchor="end">${esc(data.at(-1)?.label||'')}</text><text class="chart-value" x="${(L+W-R)/2}" y="${H-7}" text-anchor="middle">${esc(unitLabel(unit))}</text><text class="chart-value" x="14" y="${(T+H-B)/2}" transform="rotate(-90 14 ${(T+H-B)/2})" text-anchor="middle">銘柄数</text></svg>`}
function table(data,limit=200){if(!data.length)return'<div class="empty">表示できるデータがありません。</div>';const keys=[...new Set(data.slice(0,limit).flatMap(Object.keys))];return`<div class="table-wrap"><table><thead><tr>${keys.map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${data.slice(0,limit).map(r=>`<tr>${keys.map(k=>`<td>${esc(r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function chart(v){const x=v._data?{data:v._data,present:v._present??v._data.length,missing:v._missing??0}:viewData(v),source=v.source==='securities'?filtered.length:x.present+x.missing;if(v.source==='market_indicators'){const groups=Object.groupBy?Object.groupBy(x.data,d=>d.unit):{definition_specific:x.data},panels=Object.entries(groups).filter(([,data])=>data.length).map(([unit,data])=>chart({...v,title:`${v.title} · ${unitLabel(unit)}`,unit,source:'market_indicator_group',_data:data,_present:data.length,_missing:0})).join(''),unavailable=D.market_indicators.filter(indicator=>!indicator.observations.length).map(indicator=>({指標:indicator.name||indicator.indicator_id,単位:unitLabel(indicator.unit),reason_code:indicator.missing_reason||'field_absent'}));return panels+(unavailable.length?`<article class="card"><h2>未取得の市場指標</h2><div class="chart-meta"><span>取得済み系列と分けて表示</span><span>欠損 ${unavailable.length}</span></div>${table(unavailable)}</article>`:'')}const data=x.data,visual=data.length>=2?svg(v.type,data,v):'';return`<article class="card"><h2>${esc(v.title)}</h2><div class="chart-meta"><span>単位 ${esc(unitLabel(v.unit))}</span><span>期間 ${esc(periodLabel(v.period))}</span><span>${counts(source,x.present,data.length,x.missing,x.not_applicable||0,x.excluded||0)}</span></div><div class="chart-frame">${visual||table(data)}</div>${visual?`<details><summary>表データ</summary>${table(data)}</details>`:''}</article>`}
function qualityPanel(){const q=D.quality||{},f=q.failures||{},cards=[['価格取得率',format(coverageValue(q.price_coverage),'ratio')],['影響銘柄',f.affected_security_count??0],['完全取得不能',f.complete_failure_security_count??0],['部分取得',f.partial_failure_security_count??0]].map(([label,value])=>`<div class="kpi"><span>${label}</span><strong>${esc(value)}</strong></div>`).join('');const failures=[...Object.entries(f.by_stage||{}).map(([name,count])=>({分類:'stage',項目:name,件数:count})),...Object.entries(f.by_reason||{}).map(([name,count])=>({分類:'reason',項目:name,件数:count}))];const freshness=Object.entries(q.freshness||{}).map(([name,x])=>({証拠:name,観測数:x.observation_count??0,中央値:x.median??'—',p95:x.p95??'—',最大:x.maximum??'—'}));const summary=[{項目:'障害レコード',件数:f.record_count??0},{項目:'外れ値候補',件数:q.outlier_candidate_count??D.quality_outliers.length},{項目:'単位検査の問題',件数:q.unit_issue_count??0},{項目:'時点不整合',件数:q.temporal_misalignment_count??0}];return`<div class="kpis">${cards}</div>${C.views.filter(v=>v.section==='quality').map(chart).join('')}<article class="card full"><h2>障害・外れ値・鮮度</h2><div class="chart-meta"><span>障害件数と影響銘柄数は別の指標です</span></div>${table(summary)}<details><summary>障害の内訳</summary>${table(failures)}</details><details><summary>鮮度の分布 (日)</summary>${table(freshness)}</details><details><summary>外れ値候補</summary>${table(D.quality_outliers,200)}</details></article>`}
function valueCell(r,f){if(r.values?.[f]!=null)return format(r.values[f],fieldMap.get(f)?.unit);return r.missing?.[f]||'未取得'}
function securities(){const cols=C.column_sets.main,start=(page-1)*pageSize,visible=filtered.slice(start,start+pageSize),pages=Math.max(1,Math.ceil(filtered.length/pageSize));return`<article class="card full"><h2>銘柄</h2><div class="toolbar"><label>表示件数 <select id="page-size">${[25,50,100].map(n=>`<option ${n===pageSize?'selected':''}>${n}</option>`).join('')}</select></label><span class="meta">該当 ${filtered.length} / ${rows.length}</span></div>${table(visible.map(r=>({instrument_id:r.instrument_id,market:marketOf(r),memberships:(r.memberships||[]).join(', '),...Object.fromEntries(cols.map(f=>[fieldMap.get(f)?.name||f,valueCell(r,f)]))})),pageSize)}<div class="pager"><button id="prev" ${page<=1?'disabled':''}>前へ</button><span>${page} / ${pages}</span><button id="next" ${page>=pages?'disabled':''}>次へ</button></div><h2>一時比較</h2><div class="compare"><span>${selected.map(x=>`<span class="badge">${esc(x)}</span>`).join('')||'銘柄詳細から最大5銘柄を選択'}</span><button id="copy-compare" ${selected.length<2?'disabled':''}>比較CLIをコピー</button></div></article>`}
function detail(id){const r=rows.find(x=>x.instrument_id===id);if(!r)return;const v=r.values||{},command=C.actions.research.replace('{instrument_id}',r.instrument_id).replace('{object_id}',C.metadata.object_id),inSelection=selected.includes(id);$('#drawer').innerHTML=`<div class="drawer-head"><div><h2>${esc(v.name||id)}</h2><div class="meta">${esc(id)} · ${esc(r.provider_symbol)} · ${esc((r.memberships||[]).join(', '))}</div></div><button id="close-drawer">閉じる</button></div><h3>主要指標</h3>${table(C.column_sets.main.map(f=>({field:f,label:fieldMap.get(f)?.name||f,value:valueCell(r,f)})))}<h3>個別調査</h3><pre>${esc(command)}</pre><div class="toolbar"><button id="copy-research">Research CLIをコピー</button><button id="toggle-compare">${inSelection?'比較から外す':'比較へ追加'}</button></div>`;$('#drawer').hidden=false;$('#close-drawer').onclick=()=>$('#drawer').hidden=true;$('#copy-research').onclick=()=>copy(command);$('#toggle-compare').onclick=()=>{if(inSelection)selected=selected.filter(x=>x!==id);else{if(selected.length>=5)return alert('比較は最大5銘柄です。');const candidate=[...selected,id].map(x=>rows.find(r=>r.instrument_id===x)),markets=new Set(candidate.map(marketOf)),currencies=new Set(candidate.map(x=>x.values?.currency));if(markets.size>1||currencies.size>1)return alert('同一市場・同一通貨の銘柄だけ比較できます。');selected.push(id)}saveState();detail(id);render()}}
async function copy(text){try{await navigator.clipboard.writeText(text)}catch{const w=window.open('','copy');w.document.body.innerHTML=`<pre>${esc(text)}</pre>`}}
function render(){document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.id===active)));const section=$('#section-'+active);document.querySelectorAll('.section').forEach(s=>{s.classList.toggle('active',s===section);if(s!==section)s.replaceChildren()});if(active==='securities')section.innerHTML=securities();else if(active==='quality')section.innerHTML=qualityPanel();else{const charts=C.views.filter(v=>v.section===active).map(chart).join('');section.innerHTML=(active==='overview'?overviewCards():'')+(charts||'<div class="card empty">表示項目はありません。</div>')}const labels={search:'検索',market:'市場',index:'指数',currency:'通貨',sector:'セクター',industry:'業種'},selectedFilters=['search','market','index','currency','sector','industry'].map(id=>[id,$('#'+id).value]).filter(x=>x[1]);$('#chips').innerHTML=selectedFilters.map(([k,v])=>`<span class="badge">${esc(labels[k])}: ${esc(v)}</span>`).join('')+`<span>該当 ${filtered.length} / ${rows.length}</span>`+(selectedFilters.length?'<button id="clear-filters">すべて解除</button>':'');if($('#clear-filters'))$('#clear-filters').onclick=()=>{for(const id of ['search','market','index','currency','sector','industry'])$('#'+id).value='';options('industry',rows.map(r=>r.values?.industry),'全業種');applyFilters()};if(active==='securities'){section.querySelectorAll('tbody tr').forEach((tr,i)=>tr.onclick=()=>detail(filtered[(page-1)*pageSize+i].instrument_id));$('#page-size').onchange=e=>{pageSize=Number(e.target.value);page=1;render();saveState()};$('#prev').onclick=()=>{page--;render()};$('#next').onclick=()=>{page++;render()};$('#copy-compare').onclick=()=>copy(C.actions.compare.replace('{instrument_ids}',selected.join(' ')).replace('{object_id}',C.metadata.object_id))}}
async function init(){if(location.protocol==='file:')throw new Error(`file:// では正本JSONを読み込めません。marketsieve preview snapshot:latest --open を実行してください。`);C=await(await fetch('explorer-data.json',{cache:'no-store'})).json();if(C.schema!=='explorer-data/v4')throw new Error('unsupported Explorer contract');const loaded=await Promise.all(Object.entries(C.sources).map(async([k,v])=>[k,await load(v)]));D=Object.fromEntries(loaded);rows=D.securities;fieldMap=new Map(C.field_catalog.map(f=>[f.name,f]));$('#title').textContent=C.metadata.title;const dates=[...new Set(rows.map(r=>r.temporal?.price_as_of).filter(Boolean))].sort();$('#identity').textContent=`価格基準 ${dates.at(-1)||'—'} · 作成 ${C.metadata.created_at} · 価格取得率 ${format(coverageValue(D.quality.price_coverage),'ratio')} · ${rows.length}銘柄 · Snapshot ${C.metadata.object_id.slice(0,12)}`;options('index',rows.flatMap(r=>r.memberships||[]),'全指数');options('currency',rows.map(r=>r.values?.currency),'全通貨');options('sector',rows.map(r=>r.values?.sector),'全セクター');options('industry',rows.map(r=>r.values?.industry),'全業種');$('#tabs').innerHTML=C.sections.map(s=>`<button data-id="${s.id}" aria-selected="false">${esc(s.label)}</button>`).join('');$('#main').innerHTML=C.sections.map(s=>`<section id="section-${s.id}" class="section" aria-label="${esc(s.label)}"></section>`).join('');restoreState();document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{active=b.dataset.id;render();saveState()});['search','market','index','currency','industry'].forEach(id=>{$('#'+id).oninput=applyFilters;$('#'+id).onchange=applyFilters});$('#sector').onchange=()=>{const selectedIndustry=$('#industry').value,sector=$('#sector').value;options('industry',rows.filter(r=>!sector||r.values?.sector===sector).map(r=>r.values?.industry),'全業種');if([...$('#industry').options].some(o=>o.value===selectedIndustry))$('#industry').value=selectedIndustry;applyFilters()};$('#copy-state').onclick=()=>copy(JSON.stringify(state(),null,2));$('#copy-cli').onclick=()=>copy(C.actions.query.replace('{object_id}',C.metadata.object_id));applyFilters()}
init().catch(e=>{$('#main').innerHTML=`<div class="card error"><h2>Explorerを読み込めませんでした</h2><pre>${esc(e.message)}</pre></div>`});
</script></body></html>
"""


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
            "object_contract": "security-research/v8",
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
        return _RESEARCH_HTML.replace("__TITLE__", title)
    raise ValueError(f"unsupported Explorer object type: {object_type}")


_RESEARCH_HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{color-scheme:light dark;--bg:#f4f7fb;--panel:#fff;--text:#182234;--muted:#617086;--line:#d8e0ea;--accent:#1769aa;--accent2:#e78b22;--neg:#b42318;--shadow:0 8px 28px rgba(22,34,52,.08)}
@media(prefers-color-scheme:dark){:root{--bg:#0f1724;--panel:#172235;--text:#e8eef7;--muted:#a9b7ca;--line:#324157;--accent:#66b5ef;--accent2:#f1ad5f;--neg:#ff8791;--shadow:none}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,-apple-system,sans-serif}button,select{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 11px}button{cursor:pointer}button:focus-visible,select:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 35%,transparent);outline-offset:2px}header{display:flex;justify-content:space-between;gap:18px;padding:22px clamp(14px,4vw,48px);background:var(--panel);border-bottom:1px solid var(--line)}h1{font-size:24px;margin:0 0 5px}.sub,.meta{color:var(--muted);font-size:12px}.sub{overflow-wrap:anywhere}.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}nav{display:flex;gap:7px;overflow:auto;padding:12px clamp(14px,4vw,48px)}nav button[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:#fff}main{padding:0 clamp(14px,4vw,48px) 48px}.section{display:none}.section.active{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0;box-shadow:var(--shadow)}.card.full{grid-column:1/-1}.card h2{font-size:16px;margin:0 0 4px}.chart{min-height:260px}.chart-meta{color:var(--muted);font-size:12px;margin-bottom:8px}svg{width:100%;height:260px}.axis{stroke:var(--line)}.chart-label{fill:var(--muted);font-size:10px}.chart-value{fill:var(--text);font-size:10px}.series{fill:none;stroke:var(--accent);stroke-width:2}.series.s1{stroke:var(--accent2);stroke-dasharray:8 4}.series.s2{stroke:var(--muted);stroke-dasharray:2 4}.zero{stroke:var(--muted);stroke-dasharray:4 4}.table-wrap{overflow:auto;max-height:520px;border:1px solid var(--line);border-radius:10px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:8px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{position:sticky;top:0;background:var(--panel);z-index:1}.empty{padding:36px 12px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:10px}.status{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 7px}.acquisition_failed{color:var(--neg)}details{margin-top:10px}summary{cursor:pointer}
@media(max-width:700px){header{display:block}.controls{margin-top:10px}.section.active{display:block}.card{margin-bottom:12px}h1{font-size:20px}}
</style></head><body><header><div><h1 id="title">__TITLE__</h1><div id="identity" class="sub">読み込み中</div></div><div class="controls"><label>表示期間 <select id="period"><option value="3m">3か月</option><option value="6m">6か月</option><option value="1y" selected>1年</option><option value="3y">3年</option><option value="all">全期間</option></select></label><label>価格表示 <select id="price-mode"><option value="line">終値線</option><option value="candlestick">ローソク足</option></select></label><label>財務期間 <select id="financial-period"><option value="annual">年次</option><option value="quarterly">四半期</option></select></label><button id="copy-cli">CLIをコピー</button></div></header><nav id="tabs"></nav><main id="main"></main>
<script>'use strict';
const $=s=>document.querySelector(s),esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),num=v=>{const n=Number(v);return Number.isFinite(n)?n:null};
const RUNIT={ratio:'%',annualized_ratio:'%',multiple:'倍',shares:'株','銘柄通貨':'銘柄通貨','報告通貨':'報告通貨','比率':'%','start = 100':'開始値=100','rebased index':'開始値=100'},STATUS={available:'利用可能',partial:'一部利用可能',none_observed:'観測なし',not_requested:'未要求',acquisition_failed:'取得失敗',not_applicable:'適用不能',temporally_misaligned:'時点不整合'},CONCEPT={revenue:'売上高',operating_income:'営業利益',net_income:'純利益',operating_cash_flow:'営業CF',capital_expenditure:'設備投資',free_cash_flow:'FCF',operating_margin:'営業利益率',net_margin:'純利益率',return_on_equity:'ROE'};
const unitText=u=>RUNIT[u]||u,formatR=(v,u)=>{const n=num(v);if(n===null)return v??'—';if(['ratio','annualized_ratio','比率'].includes(u))return new Intl.NumberFormat('ja-JP',{style:'percent',maximumFractionDigits:2}).format(n);return new Intl.NumberFormat('ja-JP',{maximumFractionDigits:2}).format(n)},rticks=(lo,hi)=>Array.from({length:5},(_,i)=>lo+(hi-lo)*i/4);let C,D={},active='overview';
const load=async s=>{const r=await fetch(s.path,{cache:'no-store'});if(!r.ok)throw new Error(`${s.path}: HTTP ${r.status}`);const t=await r.text();return s.format==='jsonl'?t.split(/\r?\n/).filter(Boolean).map(JSON.parse):JSON.parse(t)};
function selected(rows,key='date'){const p=$('#period').value;if(p==='all'||!rows.length)return rows;const last=new Date(rows.at(-1)[key]),days={"3m":92,"6m":183,"1y":366,"3y":1096}[p],start=new Date(last);start.setUTCDate(start.getUTCDate()-days);return rows.filter(r=>new Date(r[key])>=start)}
function table(rows,limit=500){if(!rows.length)return'<div class="empty">該当する保存済み証拠はありません。</div>';const keys=[...new Set(rows.slice(0,limit).flatMap(Object.keys))];return`<div class="table-wrap"><table><thead><tr>${keys.map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${rows.slice(0,limit).map(r=>`<tr>${keys.map(k=>`<td>${esc(typeof r[k]==='object'?JSON.stringify(r[k]):r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function line(series,unit){const available=series.filter(s=>s.rows.filter(r=>num(r.value)!==null).length>=2),all=available.flatMap(s=>s.rows.map(r=>num(r.value)).filter(v=>v!==null));if(all.length<2)return'';const W=720,H=260,L=68,R=18,T=32,B=46,rawMin=Math.min(...all),rawMax=Math.max(...all),zeroBased=['株','shares','ratio','annualized_ratio','比率','報告通貨'].includes(unit),min=zeroBased?Math.min(rawMin,0):rawMin,max=zeroBased?Math.max(rawMax,0):rawMax,y=v=>H-B-(v-min)/(max-min||1)*(H-T-B),dates=available.flatMap(s=>s.rows.map(r=>r.date)).filter(Boolean).sort();return`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="横軸 日付、縦軸 ${esc(unitText(unit))}"><line class="axis" x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}"/>${rticks(min,max).map(t=>`<g><line class="axis" x1="${L-4}" y1="${y(t)}" x2="${W-R}" y2="${y(t)}" opacity=".25"/><text class="chart-label" x="${L-7}" y="${y(t)+3}" text-anchor="end">${esc(formatR(t,unit))}</text></g>`).join('')}${available.map((s,j)=>`<polyline class="series s${j%3}" points="${s.rows.map((r,i)=>`${L+i/(s.rows.length-1||1)*(W-L-R)},${y(num(r.value))}`).join(' ')}"><title>${esc(s.name)} · ${esc(unitText(unit))}</title></polyline>`).join('')}${available.map((s,j)=>`<text class="chart-value" x="${L+j*145}" y="18">${j+1}: ${esc(CONCEPT[s.name]||s.name)}</text>`).join('')}<text class="chart-label" x="${L}" y="${H-B+15}">${esc(dates[0]||'')}</text><text class="chart-label" x="${W-R}" y="${H-B+15}" text-anchor="end">${esc(dates.at(-1)||'')}</text><text class="chart-value" x="${(L+W-R)/2}" y="${H-6}" text-anchor="middle">日付</text><text class="chart-value" x="13" y="${(T+H-B)/2}" transform="rotate(-90 13 ${(T+H-B)/2})" text-anchor="middle">${esc(unitText(unit))}</text></svg>`}
function candles(rows,unit){if(rows.length<2)return'';const W=720,H=260,L=68,R=18,T=32,B=46,values=rows.flatMap(r=>[num(r.low),num(r.high)]),lo=Math.min(...values),hi=Math.max(...values),y=v=>H-B-(v-lo)/(hi-lo||1)*(H-T-B),step=(W-L-R)/rows.length,w=Math.max(1,Math.min(8,step*.65));return`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="横軸 日付、縦軸 ${esc(unitText(unit))} のローソク足"><line class="axis" x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}"/>${rticks(lo,hi).map(t=>`<text class="chart-label" x="${L-7}" y="${y(t)+3}" text-anchor="end">${esc(formatR(t,unit))}</text>`).join('')}${rows.map((r,i)=>{const x=L+(i+.5)*step,o=num(r.open),c=num(r.close),h=num(r.high),l=num(r.low),color=c>=o?'var(--accent)':'var(--neg)';return`<g><line x1="${x}" y1="${y(h)}" x2="${x}" y2="${y(l)}" stroke="${color}"/><rect x="${x-w/2}" y="${Math.min(y(o),y(c))}" width="${w}" height="${Math.max(1,Math.abs(y(o)-y(c)))}" fill="${color}"><title>${esc(r.date)} O ${o} H ${h} L ${l} C ${c}</title></rect></g>`}).join('')}<text class="chart-label" x="${L}" y="${H-B+15}">${esc(rows[0].date)}</text><text class="chart-label" x="${W-R}" y="${H-B+15}" text-anchor="end">${esc(rows.at(-1).date)}</text><text class="chart-value" x="${(L+W-R)/2}" y="${H-6}" text-anchor="middle">日付</text><text class="chart-value" x="13" y="${(T+H-B)/2}" transform="rotate(-90 13 ${(T+H-B)/2})" text-anchor="middle">${esc(unitText(unit))}</text></svg>`}
function card(title,unit,rows,visual=''){return`<article class="card"><h2>${esc(title)}</h2><div class="chart-meta">単位 ${esc(unitText(unit))} · 観測 ${rows.length}</div><div class="chart">${visual||table(rows)}</div>${visual?`<details><summary>表データ</summary>${table(rows)}</details>`:''}</article>`}
function sma(rows,n){return rows.map((r,i)=>({date:r.date,value:i+1<n?null:rows.slice(i-n+1,i+1).reduce((a,x)=>a+num(x.close),0)/n})).filter(r=>r.value!==null)}
function priceCards(){const rows=selected(D.prices),dates=new Set(rows.map(r=>r.date)),close=rows.map(r=>({date:r.date,value:num(r.close)})),vol=rows.map(r=>({date:r.date,value:num(r.volume)})),sma20=sma(D.prices,20).filter(r=>dates.has(r.date)),sma50=sma(D.prices,50).filter(r=>dates.has(r.date)),short=['3m','6m','1y'].includes($('#period').value),mode=$('#price-mode').value,visual=mode==='candlestick'&&short?candles(rows,'銘柄通貨'):line([{name:'終値',rows:close},{name:'SMA20',rows:sma20},{name:'SMA50',rows:sma50}],'銘柄通貨');$('#price-mode').querySelector('option[value=candlestick]').disabled=!short;if(!short&&mode==='candlestick')$('#price-mode').value='line';return card(mode==='candlestick'&&short?'ローソク足':'株価と20・50日移動平均','銘柄通貨',rows,visual)+card('出来高','株',vol,line([{name:'出来高',rows:vol}],'株'))+relative(rows)}
function relative(prices){const byDate=new Map(prices.map(r=>[r.date,num(r.close)])),groups=new Map;for(const r of selected(D.benchmarks)){if(!byDate.has(r.date))continue;if(!groups.has(r.benchmark))groups.set(r.benchmark,[]);groups.get(r.benchmark).push({date:r.date,value:num(r.close)})}const security=prices.map(r=>({date:r.date,value:num(r.close)})),all=[['security',security],...groups];const rebased=all.flatMap(([name,rows])=>{const base=rows.find(r=>r.value>0)?.value;return base?[{name,rows:rows.map(r=>({...r,value:r.value/base*100}))}]:[]});return card('ベンチマーク相対推移','start = 100',rebased.flatMap(x=>x.rows),line(rebased,'rebased index'))}
function riskCards(){const rows=selected(D.prices),returns=rows.map((r,i)=>i?Math.log(num(r.close)/num(rows[i-1].close)):null),rolling=rows.map((r,i)=>{const w=returns.slice(Math.max(1,i-19),i+1).filter(Number.isFinite);if(w.length<2)return{date:r.date,value:null};const mean=w.reduce((a,x)=>a+x,0)/w.length,variance=w.reduce((a,x)=>a+(x-mean)**2,0)/(w.length-1);return{date:r.date,value:Math.sqrt(variance*252)}}).filter(r=>r.value!==null);let peak=0;const dd=rows.map(r=>{const c=num(r.close);peak=Math.max(peak,c);return{date:r.date,value:c/peak-1}});const underwater=dd.filter(r=>r.value<0).length;return card('20営業日ローリング・ボラティリティ','annualized ratio',rolling,line([{name:'volatility',rows:rolling}],'ratio'))+card('ドローダウンと下落継続','ratio',dd,line([{name:`drawdown (underwater ${underwater} days)`,rows:dd}],'ratio'))}
function financialChart(title,period,concepts,unit){const rows=D.financials.filter(r=>r.period===period&&concepts.includes(r.concept)),groups=concepts.map(concept=>({name:concept,rows:rows.filter(r=>r.concept===concept).sort((a,b)=>a.fiscal_period_end.localeCompare(b.fiscal_period_end)).map(r=>({date:r.fiscal_period_end,value:num(r.value)}))})).filter(x=>x.rows.length);return card(title,unit,rows,line(groups,unit))}
function financialCards(){const period=$('#financial-period').value;return financialChart('売上高・営業利益・純利益',period,['revenue','operating_income','net_income'],'報告通貨')+financialChart('営業CF・設備投資・FCF',period,['operating_cash_flow','capital_expenditure','free_cash_flow'],'報告通貨')+financialChart('利益率・ROE',period,['operating_margin','net_margin','return_on_equity'],'比率')+`<article class="card full"><details><summary>財務の正本データ</summary>${table(D.financials.filter(r=>r.period===period),50)}</details></article>`}
function eventCards(){const rows=selected(D.events,'effective_date');return card('企業イベント','event specific',rows)}
function evidenceCards(){const states=Object.entries(D.quality.evidence_statuses||{}).map(([domain,status])=>({証拠領域:domain,状態:STATUS[status]||status,reason_code:status}));const company=Object.entries(D.company.values||{}).map(([field,value])=>({domain:'company',field,value,unit:(D.definitions.company_fields||[]).find(x=>x.name===field)?.unit||'text',basis:'retrieval'}));const failures=D.failures.map(x=>({domain:x.stage,field:x.field,value:x.reason,unit:'reason_code',basis:'retrieval'}));return card('証拠領域の取得状態','状態',states)+card('会社情報','項目別',company)+card('取得・計算障害','reason code',failures)+card('定義','contract',Object.entries(D.definitions).filter(([k])=>k!=='market_context').map(([field,value])=>({field,value:typeof value==='object'?JSON.stringify(value):value})))}
function render(){document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.id===active)));document.querySelectorAll('.section').forEach(s=>{s.classList.toggle('active',s.id===`section-${active}`);if(s.id!==`section-${active}`)s.replaceChildren()});const target=$(`#section-${active}`);target.innerHTML=active==='overview'?priceCards():active==='risk'?riskCards():active==='financials'?financialCards():active==='events'?eventCards():evidenceCards()}
async function copy(t){try{await navigator.clipboard.writeText(t)}catch{prompt('コピーしてください',t)}}
async function init(){if(location.protocol==='file:')throw new Error('file:// では正本JSONを読み込めません。marketsieve preview research:<id> --open を実行してください。');C=await(await fetch('explorer-data.json',{cache:'no-store'})).json();if(C.schema!=='explorer-data/v4'||C.metadata.object_type!=='security_research')throw new Error('unsupported Explorer contract');D=Object.fromEntries(await Promise.all(Object.entries(C.sources).map(async([k,v])=>[k,await load(v)])));const cv=D.company.values||{},last=D.prices.at(-1)||{},fresh=D.quality.freshness||{},states=Object.values(D.quality.evidence_statuses||{}),partial=states.includes('acquisition_failed')||states.includes('partial');$('#title').textContent=cv.long_name||cv.name||C.metadata.title;$('#identity').textContent=`${D.manifest.instrument_id} · ${cv.exchange_name||cv.exchange||'—'} / ${cv.currency||'—'} · 終値 ${formatR(last.close,'銘柄通貨')} (${D.manifest.temporal?.price_cutoff||last.date||'—'}) · 株価鮮度 ${fresh.price_age_days??'—'}日 / 財務鮮度 ${fresh.financial_age_days??'—'}日 · 証拠 ${partial?'一部失敗あり':'利用可能'} · Research ${C.metadata.object_id.slice(0,12)}`;$('#tabs').innerHTML=C.sections.map(s=>`<button data-id="${s.id}" aria-selected="false">${esc(s.label)}</button>`).join('');$('#main').innerHTML=C.sections.map(s=>`<section id="section-${s.id}" class="section" aria-label="${esc(s.label)}"></section>`).join('');document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{active=b.dataset.id;render()});['period','price-mode','financial-period'].forEach(id=>$('#'+id).onchange=render);$('#copy-cli').onclick=()=>copy(C.actions.query);render()}
init().catch(e=>{$('#main').innerHTML=`<article class="card"><h2>Explorerを読み込めませんでした</h2><pre>${esc(e.message)}</pre></article>`});
</script></body></html>
"""
