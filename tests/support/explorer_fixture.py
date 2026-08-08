"""Write a deterministic chart-renderer fixture for CI visual evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from marketsieve_cli.adapters.explorer import render_explorer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)
    charts = []
    for chart_type in ("line", "horizontal_bar", "histogram", "box_plot"):
        charts.append(
            {
                "chart_id": chart_type,
                "section": "Overview",
                "chart_type": chart_type,
                "title": chart_type,
                "fields": ["value"],
                "unit": "ratio",
                "period": "20 trading days",
                "observation_count": 4,
                "missing_count": 0,
                "applicability": "all_equities",
                "data": [
                    {"date": f"2026-08-0{index + 1}", "label": f"value-{index}", "value": index}
                    for index in range(4)
                ],
                "fallback_table": [
                    {"label": f"value-{index}", "value": index} for index in range(4)
                ],
            }
        )
    charts.extend(
        (
            {
                "chart_id": "scatter",
                "section": "Risk",
                "chart_type": "scatter",
                "title": "scatter",
                "fields": ["x", "y"],
                "unit": "ratio",
                "period": "60 trading days",
                "observation_count": 4,
                "missing_count": 0,
                "applicability": "all_equities",
                "data": [
                    {"label": str(index), "x": index, "y": index * index} for index in range(4)
                ],
                "fallback_table": [
                    {"label": str(index), "x": index, "y": index * index} for index in range(4)
                ],
            },
            {
                "chart_id": "heatmap",
                "section": "Risk",
                "chart_type": "heatmap",
                "title": "heatmap",
                "fields": ["return_20d"],
                "unit": "ratio",
                "period": "20 trading days",
                "observation_count": 4,
                "missing_count": 0,
                "applicability": "all_equities",
                "data": [
                    {"x": market, "y": sector, "value": value, "count": 10}
                    for market, sector, value in (
                        ("jp", "Technology", 0.02),
                        ("jp", "Financials", -0.01),
                        ("us", "Technology", 0.03),
                        ("us", "Financials", 0.01),
                    )
                ],
                "fallback_table": [],
            },
        )
    )
    document = {
        "schema": "explorer-data/v1",
        "object_type": "market_snapshot",
        "object_id": "0" * 64,
        "title": "MarketSieve Explorer Visual Evidence",
        "locale": "ja",
        "sections": ["Overview", "Risk", "Securities"],
        "charts": charts,
        "securities": [
            {
                "instrument_id": "XNAS:OTHER",
                "provider_symbol": "OTHER",
                "instrument": {"mic": "XNAS"},
                "market": "us",
                "memberships": ["sp500"],
                "values": {
                    "name": "Numeric Match Control",
                    "close": "7203",
                    "currency": "USD",
                    "sector": "Technology",
                    "industry": "Software",
                },
                "missing": {},
            },
            {
                "instrument_id": "XTKS:7203",
                "provider_symbol": "7203.T",
                "instrument": {"mic": "XTKS"},
                "market": "jp",
                "memberships": ["nikkei225", "topix500"],
                "values": {
                    "name": "Toyota Motor Corporation",
                    "close": "3130",
                    "currency": "JPY",
                    "sector": "Consumer Cyclical",
                    "industry": "Auto Manufacturers",
                },
                "missing": {},
            },
        ],
        "field_definitions": [],
    }
    (output / "explorer.html").write_text(render_explorer(document), encoding="utf-8")


if __name__ == "__main__":
    main()
