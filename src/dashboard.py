"""
Prefab UI Dashboard Builder for Stock Research MCP.

Builds interactive Prefab UI components for rendering stock analysis
dashboards inside MCP-compatible hosts (Claude Desktop, etc.) using the
``prefab-ui`` generative UI framework (https://pypi.org/project/prefab-ui/).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Companies featured in the dropdown selector (left panel requirement).
DROPDOWN_COMPANIES = [
    ("National Aluminium", "NATIONALUM.NS"),
    ("TCS", "TCS.NS"),
    ("Infosys", "INFY.NS"),
    ("Reliance", "RELIANCE.NS"),
]

GROWTH_BADGE_VARIANT = {
    "Growth": "success",     # Green
    "Neutral": "warning",    # Yellow
    "Weak": "destructive",   # Red
}

GROWTH_COLOR = {
    "Growth": "#10b981",
    "Neutral": "#f59e0b",
    "Weak": "#ef4444",
}


def build_dashboard_data(report: dict) -> dict:
    """
    Transform a stock report into a structured dashboard data payload.

    This data structure is used by both the Prefab UI tool and the
    web dashboard to render consistent views.

    Args:
        report: Complete stock analysis report dict.

    Returns:
        Structured dashboard data dict ready for UI rendering.
    """
    fundamentals = report.get("fundamentals", {})
    calculated = report.get("calculated_metrics", {})
    fair_price_data = calculated.get("fair_price_data", {})
    quarterly = report.get("quarterly_metrics", [])
    historical = report.get("historical_prices", [])

    growth_status = calculated.get("growth_status", "Neutral")

    dashboard_data = {
        "header": {
            "company_name": fundamentals.get("company_name", report.get("symbol", "Unknown")),
            "symbol": report.get("symbol", ""),
            "sector": fundamentals.get("sector", "N/A"),
            "industry": fundamentals.get("industry", "N/A"),
        },
        "growth_status": {
            "status": growth_status,
            "score": calculated.get("growth_score", 0),
            "color": GROWTH_COLOR.get(growth_status, "#f59e0b"),
            "badge_variant": GROWTH_BADGE_VARIANT.get(growth_status, "secondary"),
        },
        "key_metrics": {
            "date": report.get("fetched_at", "")[:10],
            "cmp": fundamentals.get("current_price", 0),
            "fair_price": fair_price_data.get("fair_price", 0),
            "gap_percentage": fair_price_data.get("gap_percentage", 0),
            "market_cap": fundamentals.get("market_cap", 0),
            "pe_ratio": fundamentals.get("pe_ratio", 0),
            "pb_ratio": fundamentals.get("pb_ratio", 0),
            "roe": fundamentals.get("roe", 0),
            "roce": fundamentals.get("roce"),
            "debt_to_equity": fundamentals.get("debt_to_equity", 0),
            "fifty_two_week_high": fundamentals.get("fifty_two_week_high", 0),
            "fifty_two_week_low": fundamentals.get("fifty_two_week_low", 0),
        },
        "company_info": {
            "company_name": fundamentals.get("company_name", report.get("symbol", "Unknown")),
            "promoter_holding": fundamentals.get("promoter_holding"),
            "institutional_holding": fundamentals.get("institutional_holding"),
            "institutional_holders_count": fundamentals.get("institutional_holders_count"),
        },
        "quarterly_table": quarterly,
        "candlestick_data": historical,
        "ai_summary": report.get("ai_summary", ""),
        "fair_price": {
            "fair_price": fair_price_data.get("fair_price", 0),
            "current_price": fair_price_data.get("current_price", 0),
            "gap_percentage": fair_price_data.get("gap_percentage", 0),
            "is_undervalued": fair_price_data.get("is_undervalued", False),
            "valuation_method": fair_price_data.get("valuation_method", "PE-based"),
        },
        "recommendation": report.get("recommendation", "Neutral"),
    }

    return dashboard_data


def _format_market_cap(value: float) -> str:
    """Format market cap in Indian Crore notation."""
    if not value:
        return "N/A"
    crore = value / 1e7
    if crore >= 100000:
        return f"{crore / 100000:,.2f} Lakh Cr"
    elif crore >= 1000:
        return f"{crore:,.0f} Cr"
    else:
        return f"{crore:,.2f} Cr"


def _build_candlestick_html(candles: list, company_name: str) -> str:
    """
    Build a small self-contained HTML snippet (Plotly.js via CDN) that renders
    an interactive daily candlestick chart with zoom, pan, hover and a date
    range slider. Embedded into the Prefab dashboard via the `Embed` component.
    """
    if not candles:
        return (
            "<div style='display:flex;align-items:center;justify-content:center;"
            "height:420px;font-family:sans-serif;color:#9ca3af;background:#0b0f19;'>"
            "No historical price data available.</div>"
        )

    # Keep payload light: cap to the last ~280 daily candles.
    trimmed = candles[-280:]
    dates = [c["date"] for c in trimmed]
    opens = [c["open"] for c in trimmed]
    highs = [c["high"] for c in trimmed]
    lows = [c["low"] for c in trimmed]
    closes = [c["close"] for c in trimmed]

    import json as _json
    safe_name = company_name.replace("'", "")

    return f"""
<div id="candle" style="width:100%;height:420px;background:#0b0f19;"></div>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script>
  var trace = {{
    x: {_json.dumps(dates)},
    open: {_json.dumps(opens)},
    high: {_json.dumps(highs)},
    low: {_json.dumps(lows)},
    close: {_json.dumps(closes)},
    type: 'candlestick',
    increasing: {{line: {{color: '#10b981'}}}},
    decreasing: {{line: {{color: '#ef4444'}}}},
    name: '{safe_name}'
  }};
  var layout = {{
    title: {{text: '{safe_name} — Daily Candlestick', font: {{color: '#f3f4f6'}}}},
    paper_bgcolor: '#0b0f19',
    plot_bgcolor: '#0b0f19',
    font: {{color: '#9ca3af'}},
    xaxis: {{
      title: 'Date',
      rangeslider: {{visible: true}},
      gridcolor: '#263350',
      color: '#9ca3af'
    }},
    yaxis: {{title: 'Price', gridcolor: '#263350', color: '#9ca3af'}},
    margin: {{l: 50, r: 30, t: 50, b: 40}}
  }};
  var config = {{responsive: true, scrollZoom: true, displaylogo: false}};
  Plotly.newPlot('candle', [trace], layout, config);
</script>
"""


def build_prefab_dashboard(report: dict) -> Any:
    """
    Build a Prefab UI component tree for the stock dashboard.

    Constructs the full dashboard layout (left panel: company selector +
    growth status + key metrics + shareholding pattern, right panel:
    quarterly fundamentals table, bottom panel: candlestick chart, AI
    analysis and fair price estimation) using Prefab UI components
    (Card, DataTable, Badge, Select, Embed, Metric, etc.) for rendering
    inside MCP hosts.

    Args:
        report: Complete stock analysis report dict.

    Returns:
        A Prefab UI component (PrefabApp) ready for serialization, or the
        raw dashboard data dict if `prefab-ui` is not installed.
    """
    try:
        from prefab_ui.app import PrefabApp
        from prefab_ui.components import (
            Card, CardContent, CardHeader, CardTitle, CardDescription,
            DataTable, DataTableColumn,
            Badge, Metric, Embed, Separator,
            Select, SelectOption,
            Column, Row, Grid,
            P, Muted, Markdown,
        )
        from prefab_ui.actions import CallTool
    except ImportError:
        logger.warning("prefab_ui not installed. Returning raw dashboard data.")
        return build_dashboard_data(report)

    data = build_dashboard_data(report)
    header = data["header"]
    growth = data["growth_status"]
    metrics = data["key_metrics"]
    info = data["company_info"]
    quarterly = data["quarterly_table"]
    fair = data["fair_price"]
    candles = data["candlestick_data"]

    gap_status = "Undervalued" if fair["is_undervalued"] else "Overvalued"

    with PrefabApp(title=f"\U0001F4CA {header['company_name']} — Stock Analysis") as app:

        # === HEADER ===
        with Card():
            with CardHeader():
                CardTitle(f"\U0001F4CA {header['company_name']} ({header['symbol']})")
                CardDescription(f"{header['sector']} • {header['industry']}")

        with Row():
            # ================= LEFT PANEL =================
            with Column(css_class="basis-1/3 gap-4"):

                # --- Company Dropdown Selector ---
                with Card():
                    with CardHeader():
                        CardTitle("Company Selector")
                    with CardContent():
                        Select(
                            name="company_selector",
                            value=header["symbol"],
                            placeholder="Select a company…",
                            onChange=CallTool("show_dashboard", arguments={"symbol": "{{value}}"}),
                            children=[
                                SelectOption(name, value=symbol, selected=(symbol == header["symbol"]))
                                for name, symbol in DROPDOWN_COMPANIES
                            ],
                        )
                        Muted("Selecting a company refreshes the entire dashboard via the show_dashboard MCP tool.")

                # --- Growth Status Indicator (color coded) ---
                with Card():
                    with CardHeader():
                        CardTitle("Growth Status")
                    with CardContent():
                        Badge(
                            f"{growth['status'].upper()} • {growth['score']}/10",
                            variant=growth["badge_variant"],
                        )
                        P(
                            "\U0001F7E2 Growth = healthy revenue/PAT growth, controlled debt, "
                            "stable promoter holding  •  \U0001F7E1 Neutral = mixed fundamentals  •  "
                            "\U0001F534 Weak = declining business metrics"
                        )
                        Separator()
                        Grid(css_class="grid-cols-2 gap-2", children=[
                            _metric_block("Date", metrics["date"] or "N/A"),
                            _metric_block("CMP", f"₹{metrics['cmp']:,.2f}"),
                            _metric_block("Fair Price", f"₹{metrics['fair_price']:,.2f}"),
                            _metric_block("Gap %", f"{metrics['gap_percentage']:+.2f}% ({gap_status})"),
                            _metric_block("Market Cap", _format_market_cap(metrics["market_cap"])),
                            _metric_block("PE Ratio", f"{metrics['pe_ratio']:.2f}" if metrics["pe_ratio"] else "N/A"),
                        ])

                # --- Company Information / Shareholding Pattern ---
                with Card():
                    with CardHeader():
                        CardTitle("Company Information")
                    with CardContent():
                        Markdown(f"**Company Name:** {info['company_name']}")
                        Separator()
                        Grid(css_class="grid-cols-2 gap-2", children=[
                            _metric_block("Promoter/Insider Holding", f"{info['promoter_holding']:.1f}%" if info['promoter_holding'] is not None else "N/A"),
                            _metric_block("Institutional Holding", f"{info['institutional_holding']:.1f}%" if info['institutional_holding'] is not None else "N/A"),
                            _metric_block("Institutional Holders", f"{info['institutional_holders_count']:,}" if info['institutional_holders_count'] is not None else "N/A"),
                        ])

            # ================= RIGHT PANEL =================
            with Column(css_class="basis-2/3 gap-4"):
                with Card():
                    with CardHeader():
                        CardTitle("Quarterly Fundamentals")
                        CardDescription("All values in ₹ Crores. TTM = Trailing Twelve Months.")
                    with CardContent():
                        if quarterly:
                            columns = [
                                DataTableColumn(key="quarter", header="Quarter", sortable=True),
                                DataTableColumn(key="net_sales", header="Net Sales", sortable=True, align="right"),
                                DataTableColumn(key="ttm_gp", header="TTM GP", sortable=True, align="right"),
                                DataTableColumn(key="gpm", header="GPM %", sortable=True, align="right"),
                                DataTableColumn(key="interest", header="Interest", sortable=True, align="right"),
                                DataTableColumn(key="ebitda", header="EBITDA", sortable=True, align="right"),
                                DataTableColumn(key="tax", header="Tax", sortable=True, align="right"),
                                DataTableColumn(key="pat", header="PAT", sortable=True, align="right"),
                                DataTableColumn(key="npm", header="NPM %", sortable=True, align="right"),
                                DataTableColumn(key="market_cap", header="Market Cap", sortable=True, align="right"),
                                DataTableColumn(key="ttm_pe", header="TTM PE", sortable=True, align="right"),
                                DataTableColumn(key="recommendation", header="Recommendation", sortable=True),
                            ]

                            display_rows = [
                                {
                                    "quarter": q.get("quarter", "N/A"),
                                    "net_sales": f"{q.get('net_sales', 0):,.1f}",
                                    "ttm_gp": f"{q['ttm_gp']:,.1f}" if q.get("ttm_gp") is not None else "N/A",
                                    "gpm": f"{q['gpm']:.1f}" if q.get("gpm") is not None else "N/A",
                                    "interest": f"{q.get('interest', 0):,.1f}",
                                    "ebitda": f"{q.get('ebitda', 0):,.1f}",
                                    "tax": f"{q.get('tax', 0):,.1f}",
                                    "pat": f"{q.get('pat', 0):,.1f}",
                                    "npm": f"{q.get('npm', 0):.1f}",
                                    "market_cap": f"{q.get('market_cap', 0):,.0f}",
                                    "ttm_pe": f"{q.get('ttm_pe', 0):.1f}" if q.get("ttm_pe") else "N/A",
                                    "recommendation": q.get("recommendation", "N/A"),
                                }
                                for q in quarterly
                            ]

                            DataTable(columns=columns, rows=display_rows, search=True, paginated=True, pageSize=8)
                        else:
                            P("No quarterly data available for this symbol.")

        # ================= BOTTOM PANEL =================
        Separator()

        # --- Interactive Candlestick Chart ---
        with Card():
            with CardHeader():
                CardTitle("\U0001F56F️ Interactive Daily Candlestick Chart")
                CardDescription("Open • High • Low • Close — supports zoom, pan, hover and date-range filtering.")
            with CardContent():
                Embed(html=_build_candlestick_html(candles, header["company_name"]), width="100%", height="440px")

        with Row():
            # --- AI Analysis ---
            with Column(css_class="basis-1/2"):
                with Card():
                    with CardHeader():
                        CardTitle("\U0001F916 AI Analysis")
                    with CardContent():
                        P(data["ai_summary"])
                        Separator()
                        Badge(f"Recommendation: {data['recommendation']}", variant=growth["badge_variant"])

            # --- Fair Price Estimation ---
            with Column(css_class="basis-1/2"):
                with Card():
                    with CardHeader():
                        CardTitle("\U0001F4B0 Fair Price Estimation")
                    with CardContent():
                        Grid(css_class="grid-cols-2 gap-3", children=[
                            Metric(label="Fair Price", value=f"₹{fair['fair_price']:,.2f}"),
                            Metric(label="Current Price (CMP)", value=f"₹{fair['current_price']:,.2f}"),
                            Metric(
                                label="Undervalued %" if fair["is_undervalued"] else "Overvalued %",
                                value=f"{abs(fair['gap_percentage']):.2f}%",
                                trend="up" if fair["is_undervalued"] else "down",
                                trendSentiment="positive" if fair["is_undervalued"] else "negative",
                            ),
                            Metric(label="Valuation Status", value=gap_status),
                        ])
                        Separator()
                        Muted(f"Method: {fair['valuation_method']}")
                        Muted("Formula: Gap % = ((Fair Price − CMP) / Fair Price) × 100")

    return app


def _metric_block(label: str, value: str):
    """Small helper building a label/value pair as a Prefab component for grids."""
    from prefab_ui.components import Column, Muted, Markdown
    return Column(children=[Muted(label), Markdown(f"**{value}**")])
