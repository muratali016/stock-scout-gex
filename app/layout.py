from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash.dash_table.Format import Format, Scheme, Sign, Group
from config import SECTOR_ETFS, CACHE_TTL_MINUTES, MAG7_SYMBOLS
from app.ai_data import VOLUME_AI_MODELS, VOLUME_AI_DEFAULT_MODEL

_initial_tickers: list[str] = []
_initial_indicators: list[str] = []

# =========================================================================
# Shared style constants
# =========================================================================
CELL_DARK = "#1a1a2e"
HEADER_DARK = "#16213e"
GREEN = "#00d47e"
RED = "#ff4757"
CYAN = "#4ecdc4"

PERF_COLS = ["chg", "perf_1d", "perf_1w", "perf_1m", "perf_3m"]

_shared_header_style = {
    "backgroundColor": HEADER_DARK, "color": "#e0e0e0",
    "fontWeight": "700", "fontSize": "0.82rem", "textAlign": "center",
    "border": "none", "borderBottom": f"2px solid {CYAN}", "padding": "12px 8px",
}
_shared_cell_style = {
    "backgroundColor": CELL_DARK, "color": "#d0d0d0", "border": "none",
    "borderBottom": "1px solid rgba(255,255,255,0.04)",
    "fontSize": "0.85rem", "padding": "10px 10px", "textAlign": "center",
    "fontFamily": "'Segoe UI', 'Consolas', monospace",
}


VOL_HIST_TABLE_COLUMNS = [
    {"name": "Time",      "id": "ts",        "type": "text"},
    {"name": "Open",      "id": "open",      "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Close",     "id": "close",     "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Bar %",     "id": "bar_chg",   "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed,
                      sign=Sign.positive)},
    {"name": "Range",     "id": "range",     "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Volume",    "id": "volume",    "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "% Sess",    "id": "pct_sess",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Cum Vol",   "id": "cum_vol",   "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Vol Z",     "id": "vol_z",     "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Rel Vol",   "id": "rel_vol",   "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Buy %",     "id": "buy_share", "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"name": "Delta $",   "id": "delta",     "type": "numeric",
     "format": Format(group=Group.yes, sign=Sign.positive)},
    {"name": "Cum \u0394 $", "id": "cum_delta", "type": "numeric",
     "format": Format(group=Group.yes, sign=Sign.positive)},
    {"name": "VWAP",      "id": "vwap",      "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "vs VWAP",   "id": "vwap_diff", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed,
                      sign=Sign.positive)},
]

OPT_SCR_SUMMARY_COLUMNS = [
    {"name": "Expiration", "id": "expiration", "type": "text"},
    {"name": "Call Volume", "id": "call_volume", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Put Volume", "id": "put_volume", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Call OI", "id": "call_oi", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Put OI", "id": "put_oi", "type": "numeric",
     "format": Format(group=Group.yes)},
]

OPT_SCR_TOP_COLUMNS = [
    {"name": "Strike", "id": "strike", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Volume", "id": "volume", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Open Interest", "id": "openInterest", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "IV", "id": "impliedVolatility", "type": "numeric",
     "format": Format(precision=4, scheme=Scheme.fixed)},
    {"name": "ITM", "id": "inTheMoney", "type": "text"},
]

OPT_BIG_MONEY_COLUMNS = [
    {"name": "Expiration", "id": "expiration", "type": "text"},
    {"name": "Type", "id": "option_type", "type": "text"},
    {"name": "Strike", "id": "strike", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Volume", "id": "volume", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Open Interest", "id": "open_interest", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Last", "id": "last_price", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Bid", "id": "bid", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Ask", "id": "ask", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Premium $", "id": "premium_notional", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Vol/OI", "id": "vol_oi", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Bias", "id": "side_bias", "type": "text"},
]


def _vol_hist_conditional_styles():
    return [
        {"if": {"column_id": "bar_chg",
                "filter_query": "{bar_chg} > 0"},
         "color": GREEN, "fontWeight": "600"},
        {"if": {"column_id": "bar_chg",
                "filter_query": "{bar_chg} < 0"},
         "color": RED, "fontWeight": "600"},
        {"if": {"column_id": "delta",
                "filter_query": "{delta} > 0"},
         "color": GREEN, "fontWeight": "600"},
        {"if": {"column_id": "delta",
                "filter_query": "{delta} < 0"},
         "color": RED, "fontWeight": "600"},
        {"if": {"column_id": "cum_delta",
                "filter_query": "{cum_delta} > 0"},
         "color": GREEN},
        {"if": {"column_id": "cum_delta",
                "filter_query": "{cum_delta} < 0"},
         "color": RED},
        {"if": {"column_id": "buy_share",
                "filter_query": "{buy_share} >= 65"},
         "color": GREEN, "fontWeight": "600"},
        {"if": {"column_id": "buy_share",
                "filter_query": "{buy_share} <= 35"},
         "color": RED, "fontWeight": "600"},
        {"if": {"column_id": "vol_z",
                "filter_query": "{vol_z} >= 3"},
         "backgroundColor": "rgba(255,165,2,0.18)",
         "color": "#ffa502", "fontWeight": "700"},
        {"if": {"column_id": "vol_z",
                "filter_query": "{vol_z} >= 2 && {vol_z} < 3"},
         "backgroundColor": "rgba(78,205,196,0.12)",
         "color": CYAN, "fontWeight": "700"},
        {"if": {"column_id": "rel_vol",
                "filter_query": "{rel_vol} >= 2"},
         "color": "#ffa502", "fontWeight": "700"},
        {"if": {"column_id": "rel_vol",
                "filter_query": "{rel_vol} >= 1.5 && {rel_vol} < 2"},
         "color": CYAN, "fontWeight": "700"},
        {"if": {"column_id": "vwap_diff",
                "filter_query": "{vwap_diff} > 0"},
         "color": GREEN},
        {"if": {"column_id": "vwap_diff",
                "filter_query": "{vwap_diff} < 0"},
         "color": RED},
        {"if": {"state": "active"},
         "backgroundColor": "#0f3460",
         "border": f"1px solid {CYAN}"},
    ]


_VOL_HIST_CELL_CONDITIONAL = [
    {"if": {"column_id": "ts"},
     "fontFamily": "Consolas, monospace",
     "color": "#bbb", "minWidth": "110px",
     "textAlign": "left", "fontWeight": "600"},
    {"if": {"column_id": "vwap_diff"},
     "fontWeight": "600"},
]


def _perf_conditional_styles():
    rules = []
    for col in PERF_COLS:
        rules.append({"if": {"column_id": col, "filter_query": f"{{{col}}} > 0"},
                       "color": GREEN, "fontWeight": "600"})
        rules.append({"if": {"column_id": col, "filter_query": f"{{{col}}} < 0"},
                       "color": RED, "fontWeight": "600"})
    rules.append({"if": {"column_id": "trend", "filter_query": '{trend} = "\u2713"'},
                   "color": GREEN, "fontWeight": "bold", "textAlign": "center"})
    rules.append({"if": {"column_id": "trend", "filter_query": '{trend} = "\u2717"'},
                   "color": RED, "fontWeight": "bold", "textAlign": "center"})
    rules.append({"if": {"state": "active"},
                   "backgroundColor": "#0f3460", "border": f"1px solid {CYAN}"})
    return rules


# =========================================================================
# Tab 1 — Sector ETFs
# =========================================================================

ETF_TABLE_COLUMNS = [
    {"name": "Ticker",   "id": "ticker",   "type": "text"},
    {"name": "Sector",   "id": "sector",   "type": "text"},
    {"name": "Industries", "id": "industries", "type": "text"},
    {"name": "Price",    "id": "price",    "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Chg %",    "id": "chg",      "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "1D %",     "id": "perf_1d",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "1W %",     "id": "perf_1w",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "1M %",     "id": "perf_1m",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "3M %",     "id": "perf_3m",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "ADR %",    "id": "adr",      "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Vol ($M)", "id": "vol",      "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed, group=Group.yes)},
    {"name": "Trend",    "id": "trend",    "type": "text"},
]

HOLDINGS_TABLE_COLUMNS = [
    {"name": "Symbol", "id": "symbol", "type": "text"},
    {"name": "Name", "id": "name", "type": "text"},
    {"name": "Weight %", "id": "weight", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "1D %", "id": "perf_1d", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "1W %", "id": "perf_1w", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "1M %", "id": "perf_1m", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
]


def _build_sector_tab():
    sector_options = [{"label": "All Sectors", "value": "ALL"}] + [
        {"label": v["sector"], "value": k} for k, v in SECTOR_ETFS.items()
    ]
    sort_options = [
        {"label": "1M Performance", "value": "perf_1m"},
        {"label": "3M Performance", "value": "perf_3m"},
        {"label": "Daily Change",   "value": "chg"},
        {"label": "ADR %",          "value": "adr"},
        {"label": "Volume",         "value": "vol"},
        {"label": "Ticker (A-Z)",   "value": "ticker"},
    ]

    return html.Div([
        dbc.Row(id="summary-cards", className="mb-4 gx-3"),
        dbc.Row([
            dbc.Col([
                dbc.Label("Sector", className="text-muted small mb-1"),
                dbc.Select(id="sector-filter",
                           options=[{"label": o["label"], "value": o["value"]} for o in sector_options],
                           value="ALL"),
            ], md=4, sm=6),
            dbc.Col([
                dbc.Label("Sort by", className="text-muted small mb-1"),
                dbc.Select(id="sort-by",
                           options=[{"label": o["label"], "value": o["value"]} for o in sort_options],
                           value="perf_1m"),
            ], md=3, sm=6),
            dbc.Col([
                dbc.Label("Order", className="text-muted small mb-1"),
                dbc.RadioItems(id="sort-order",
                               options=[{"label": "Desc", "value": "desc"},
                                        {"label": "Asc", "value": "asc"}],
                               value="desc", inline=True, className="mt-1"),
            ], md=3, sm=6, className="d-flex flex-column"),
        ], className="mb-4"),
        dbc.Row([dbc.Col([
            dcc.Loading(id="table-loading", type="dot", color=CYAN,
                        children=dash_table.DataTable(
                            id="etf-table", columns=ETF_TABLE_COLUMNS, data=[],
                            sort_action="native",
                            style_table={"overflowX": "auto", "borderRadius": "8px"},
                            style_header=_shared_header_style,
                            style_cell=_shared_cell_style,
                            style_cell_conditional=[
                                {"if": {"column_id": "ticker"}, "fontWeight": "700",
                                 "color": "#fff", "textAlign": "left",
                                 "width": "55px", "minWidth": "55px", "maxWidth": "55px"},
                                {"if": {"column_id": "sector"}, "textAlign": "left",
                                 "width": "120px", "minWidth": "100px"},
                                {"if": {"column_id": "industries"}, "textAlign": "left",
                                 "fontSize": "0.75rem", "color": "#999",
                                 "width": "180px", "minWidth": "140px", "whiteSpace": "normal"},
                                {"if": {"column_id": "trend"}, "width": "50px",
                                 "minWidth": "50px", "maxWidth": "50px"},
                            ],
                            style_data_conditional=_perf_conditional_styles(),
                            style_as_list_view=True, page_size=15, cell_selectable=True,
                        )),
        ])], className="mb-4"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5(id="chart-title", className="mb-0",
                                           style={"fontWeight": "600"}),
                                   style={"backgroundColor": HEADER_DARK, "border": "none"}),
                    dbc.CardBody([
                        html.Iframe(id="etf-tv-chart", src="", style={
                            "width": "100%", "height": "500px", "border": "none",
                            "borderRadius": "4px",
                        }),
                    ], style={"padding": "0.5rem"}),
                ], id="chart-card",
                   style={"display": "none", "backgroundColor": CELL_DARK,
                          "border": "1px solid rgba(255,255,255,0.06)", "borderRadius": "8px"}),
            ], md=8),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(
                        html.Div([
                            html.H5(id="holdings-title", children="Holdings",
                                    className="mb-0",
                                    style={"fontWeight": "600", "fontSize": "0.95rem"}),
                        ]),
                        style={"backgroundColor": HEADER_DARK, "border": "none"},
                    ),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id="holdings-table",
                            columns=HOLDINGS_TABLE_COLUMNS,
                            data=[],
                            sort_action="native",
                            row_selectable="single",
                            selected_rows=[],
                            style_table={"overflowX": "auto", "borderRadius": "6px",
                                         "maxHeight": "320px", "overflowY": "auto"},
                            style_header={**_shared_header_style, "fontSize": "0.76rem",
                                          "padding": "8px 6px"},
                            style_cell={**_shared_cell_style, "fontSize": "0.76rem",
                                        "padding": "7px 6px"},
                            style_cell_conditional=[
                                {"if": {"column_id": "symbol"}, "fontWeight": "700",
                                 "color": "#fff", "textAlign": "left", "width": "58px",
                                 "minWidth": "58px"},
                                {"if": {"column_id": "name"}, "textAlign": "left",
                                 "fontSize": "0.72rem", "color": "#aaa", "whiteSpace": "normal"},
                            ],
                            style_data_conditional=_perf_conditional_styles(),
                        ),
                        html.Div([
                            dbc.Button("Screen Selected", id="holdings-screen-one-btn",
                                       color="info", outline=True, size="sm",
                                       className="me-2", style={"fontWeight": "600"}),
                            dbc.Button("Screen All Holdings", id="holdings-screen-all-btn",
                                       color="info", size="sm",
                                       style={"fontWeight": "600"}),
                        ], style={"display": "flex"}),
                    ], style={"padding": "0.75rem"}),
                ], id="holdings-card",
                   style={"display": "none", "backgroundColor": CELL_DARK,
                          "border": "1px solid rgba(255,255,255,0.06)", "borderRadius": "8px"}),
            ], md=4),
        ]),
        dcc.Store(id="table-data-store"),
        dcc.Store(id="holdings-symbols-store", data=[]),
    ])


# =========================================================================
# Tab 2 — Screened Stocks
# =========================================================================

SCREENER_COLUMNS = [
    {"name": "Symbol",   "id": "symbol",        "type": "text"},
    {"name": "Name",     "id": "name",          "type": "text"},
    {"name": "Sector",   "id": "sector",        "type": "text"},
    {"name": "Industry", "id": "industry",      "type": "text"},
    {"name": "Price",    "id": "close",         "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Chg %",    "id": "chg",           "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "1D %",     "id": "perf_1d",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "Abs Str",  "id": "abs_strength",  "type": "numeric",
     "format": Format(precision=0, scheme=Scheme.fixed)},
    {"name": "RMV-15",   "id": "rmv_15",        "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"name": "1W %",     "id": "perf_1w",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "1M %",     "id": "perf_1m",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "3M %",     "id": "perf_3m",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "ADR %",    "id": "adr_pct",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Vol ($M)", "id": "avg_dollar_vol", "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed, group=Group.yes)},
]


def _screener_conditional_styles():
    rules = _perf_conditional_styles()
    # Abs Strength gradient: higher = greener
    for lo, hi, color in [(80, 100, GREEN), (60, 80, "#7ec8a0"), (1, 40, RED)]:
        rules.append({
            "if": {"column_id": "abs_strength",
                   "filter_query": f"{{abs_strength}} >= {lo} && {{abs_strength}} <= {hi}"},
            "color": color, "fontWeight": "700",
        })
    # RMV: lower = tighter = highlighted in cyan
    rules.append({
        "if": {"column_id": "rmv_15", "filter_query": "{rmv_15} < 75"},
        "color": CYAN, "fontWeight": "700",
    })
    return rules


def _build_screener_tab():
    sort_options = [
        {"label": "Abs Strength", "value": "abs_strength"},
        {"label": "RMV-15 (tightest)", "value": "rmv_15"},
        {"label": "1M Performance", "value": "perf_1m"},
        {"label": "3M Performance", "value": "perf_3m"},
        {"label": "ADR %", "value": "adr_pct"},
        {"label": "Symbol (A-Z)", "value": "symbol"},
    ]

    return html.Div([
        # --- Add Stocks Input ---
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Add Tickers", className="text-muted small mb-1"),
                        dbc.Input(
                            id="scr-ticker-input", type="text",
                            placeholder="e.g.  AAPL, MSFT, NVDA, TSLA, AMZN",
                            debounce=False,
                            style={"backgroundColor": "#16213e", "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=7, sm=12),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        html.Div([
                            dbc.Button("Screen", id="scr-add-btn", color="info",
                                       className="me-2", style={"fontWeight": "600"}),
                            dbc.Button("Clear All", id="scr-clear-btn", color="secondary",
                                       outline=True, size="sm"),
                        ], className="d-flex align-items-center"),
                    ], md=3, sm=6, className="d-flex flex-column"),
                    dbc.Col([
                        html.Div(id="scr-status-text",
                                 style={"fontSize": "0.8rem", "color": "#888",
                                        "paddingTop": "28px"}),
                    ], md=2, sm=6),
                ], align="end"),
            ], style={"padding": "12px 18px"}),
        ], style={"backgroundColor": "#16213e", "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-4"),

        dbc.Row(id="scr-summary-cards", className="mb-4 gx-3"),
        dbc.Row([
            dbc.Col([
                dbc.Label("Sector", className="text-muted small mb-1"),
                dbc.Select(id="scr-sector-filter", value="ALL"),
            ], md=3, sm=6),
            dbc.Col([
                dbc.Label("Sort by", className="text-muted small mb-1"),
                dbc.Select(id="scr-sort-by",
                           options=[{"label": o["label"], "value": o["value"]} for o in sort_options],
                           value="abs_strength"),
            ], md=3, sm=6),
            dbc.Col([
                dbc.Label("Order", className="text-muted small mb-1"),
                dbc.RadioItems(id="scr-sort-order",
                               options=[{"label": "Desc", "value": "desc"},
                                        {"label": "Asc", "value": "asc"}],
                               value="desc", inline=True, className="mt-1"),
            ], md=2, sm=6, className="d-flex flex-column"),
            dbc.Col([
                dbc.Label("Vol Contraction Only", className="text-muted small mb-1"),
                dbc.Switch(id="scr-vol-contraction", value=False),
            ], md=2, sm=6),
        ], className="mb-4"),
        dbc.Row([dbc.Col([
            dcc.Loading(id="scr-table-loading", type="dot", color=CYAN,
                        children=dash_table.DataTable(
                            id="scr-table", columns=SCREENER_COLUMNS, data=[],
                            sort_action="native",
                            style_table={"overflowX": "auto", "borderRadius": "8px"},
                            style_header=_shared_header_style,
                            style_cell=_shared_cell_style,
                            style_cell_conditional=[
                                {"if": {"column_id": "symbol"}, "fontWeight": "700",
                                 "color": "#fff", "textAlign": "left",
                                 "width": "65px", "minWidth": "60px"},
                                {"if": {"column_id": "name"}, "textAlign": "left",
                                 "width": "140px", "minWidth": "100px", "whiteSpace": "normal",
                                 "fontSize": "0.78rem", "color": "#bbb"},
                                {"if": {"column_id": "sector"}, "textAlign": "left",
                                 "width": "110px", "minWidth": "90px", "fontSize": "0.78rem"},
                                {"if": {"column_id": "industry"}, "textAlign": "left",
                                 "width": "130px", "minWidth": "100px", "whiteSpace": "normal",
                                 "fontSize": "0.75rem", "color": "#999"},
                            ],
                            style_data_conditional=_screener_conditional_styles(),
                            style_as_list_view=True, page_size=25, cell_selectable=True,
                        )),
        ])], className="mb-4"),
        dbc.Row([dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5(id="scr-chart-title", className="mb-0",
                                       style={"fontWeight": "600"}),
                               style={"backgroundColor": HEADER_DARK, "border": "none"}),
                dbc.CardBody([
                    html.Iframe(id="scr-tv-chart", src="", style={
                        "width": "100%", "height": "500px", "border": "none",
                        "borderRadius": "4px",
                    }),
                ], style={"padding": "0.5rem"}),
            ], id="scr-chart-card",
               style={"display": "none", "backgroundColor": CELL_DARK,
                      "border": "1px solid rgba(255,255,255,0.06)", "borderRadius": "8px"}),
        ])]),
        dcc.Store(id="scr-data-store"),
        dcc.Store(id="scr-ticker-store", data=_initial_tickers, storage_type="local"),
    ])


# =========================================================================
# Tab 3 — Full TradingView
# =========================================================================

INDICATOR_CATALOG = {
    "EMA":    {"study_id": "MAExp@tv-basicstudies",              "default": 9,  "has_length": True},
    "SMA":    {"study_id": "MASimple@tv-basicstudies",           "default": 20, "has_length": True},
    "RSI":    {"study_id": "RSI@tv-basicstudies",                "default": 14, "has_length": True},
    "MACD":   {"study_id": "MACD@tv-basicstudies",               "default": None, "has_length": False},
    "BB":     {"study_id": "BB@tv-basicstudies",                  "default": 20, "has_length": True},
    "VWAP":   {"study_id": "VWAP@tv-basicstudies",               "default": None, "has_length": False},
    "Stoch":  {"study_id": "Stochastic@tv-basicstudies",         "default": 14, "has_length": True},
    "ATR":    {"study_id": "ATR@tv-basicstudies",                 "default": 14, "has_length": True},
    "ADX":    {"study_id": "directionalmovement@tv-basicstudies", "default": 14, "has_length": True},
    "Ichimoku": {"study_id": "IchimokuCloud@tv-basicstudies",    "default": None, "has_length": False},
    "CCI":    {"study_id": "CCI@tv-basicstudies",                 "default": 20, "has_length": True},
    "SuperT": {"study_id": "Supertrend@tv-basicstudies",          "default": None, "has_length": False},
}


def _build_tradingview_tab():
    dropdown_opts = [{"label": k, "value": k} for k in INDICATOR_CATALOG]

    return html.Div([
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Indicator", className="text-muted small mb-1"),
                        dbc.Select(id="tv-ind-type", value="EMA",
                                   options=[{"label": o["label"], "value": o["value"]}
                                            for o in dropdown_opts]),
                    ], md=2, sm=4),
                    dbc.Col([
                        dbc.Label("Period", className="text-muted small mb-1"),
                        dbc.Input(id="tv-ind-period", type="number", value=9, min=1, max=500,
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0"}),
                    ], md=1, sm=3),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        html.Div([
                            dbc.Button("Add", id="tv-add-ind-btn", color="info",
                                       size="sm", className="me-2",
                                       style={"fontWeight": "600"}),
                            dbc.Button("Apply", id="tv-apply-btn", color="success",
                                       size="sm", style={"fontWeight": "600"}),
                        ], className="d-flex"),
                    ], md=2, sm=5, className="d-flex flex-column"),
                    dbc.Col([
                        dbc.Label("Active Indicators", className="text-muted small mb-1"),
                        html.Div(id="tv-active-pills",
                                 style={"display": "flex", "flexWrap": "wrap",
                                        "gap": "6px", "minHeight": "32px",
                                        "alignItems": "center"}),
                    ], md=7),
                ], align="end"),
            ], style={"padding": "10px 18px"}),
        ], style={"backgroundColor": "#16213e",
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-2"),

        html.Iframe(
            id="tv-main-chart",
            srcDoc="",
            style={
                "width": "100%",
                "height": "calc(100vh - 200px)",
                "border": "none",
                "borderRadius": "8px",
            },
            sandbox="allow-scripts allow-same-origin allow-popups allow-forms allow-popups-to-escape-sandbox",
        ),
        dcc.Store(id="tv-indicators-store", data=_initial_indicators),
    ])


# =========================================================================
# Tab 4 — Trade (Alpaca)
# =========================================================================

POSITION_COLUMNS = [
    {"name": "Symbol",       "id": "symbol",        "type": "text"},
    {"name": "Qty",          "id": "qty",           "type": "text"},
    {"name": "Cost Basis $", "id": "cost_basis",    "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Mkt Value $",  "id": "market_value",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "P/L $",        "id": "unrealized_pl", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "Return %",     "id": "return_pct",    "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
]

OPTIONS_COLUMNS = [
    {"name": "C/P",    "id": "type",          "type": "text"},
    {"name": "Strike", "id": "strike",        "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "M",      "id": "moneyness",     "type": "text"},
    {"name": "Bid",    "id": "bid",           "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Ask",    "id": "ask",           "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Delta",  "id": "delta",         "type": "numeric",
     "format": Format(precision=4, scheme=Scheme.fixed)},
    {"name": "Gamma",  "id": "gamma",         "type": "numeric",
     "format": Format(precision=4, scheme=Scheme.fixed)},
    {"name": "Theta",  "id": "theta",         "type": "numeric",
     "format": Format(precision=4, scheme=Scheme.fixed)},
    {"name": "Vega",   "id": "vega",          "type": "numeric",
     "format": Format(precision=4, scheme=Scheme.fixed)},
    {"name": "Rho",    "id": "rho",           "type": "numeric",
     "format": Format(precision=4, scheme=Scheme.fixed)},
    {"name": "IV %",   "id": "iv",            "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Option Symbol", "id": "option_symbol", "type": "text"},
]


# =========================================================================
# Risk Engine — Debit Spread Builder (sources from the live Options Chain)
# =========================================================================


def _safe_float(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _row_mid(row: dict) -> float | None:
    """Return mid price ((bid+ask)/2) for an options-chain row, or None
    when the quote is unusable."""
    bid_f = _safe_float(row.get("bid"))
    ask_f = _safe_float(row.get("ask"))
    if bid_f is None and ask_f is None:
        return None
    if bid_f is None or bid_f <= 0:
        return ask_f if ask_f and ask_f > 0 else None
    if ask_f is None or ask_f <= 0:
        return bid_f
    if ask_f < bid_f:
        return None
    return round((bid_f + ask_f) / 2, 4)


# Strategy metadata used by both layout (dropdown / pill colors) and by
# the Risk Engine callbacks (Est. PnL move multiplier, header label).
#
# `move_mult`:  factor applied to the user-entered Move ($) when computing
#               Est. PnL.  Always +1 — the user enters the LITERAL signed
#               underlying move ( +1 = up $1, -1 = down $1 ) and the
#               strategy's own net_delta sign produces the correct
#               directional P/L automatically.
#                 - Bull Call (Δ > 0):  +move ⇒ profit, -move ⇒ loss
#                 - Bear Put  (Δ < 0):  +move ⇒ loss,   -move ⇒ profit
#                 - Bull Put  (Δ > 0):  +move ⇒ profit, -move ⇒ loss
#                 - Bear Call (Δ < 0):  +move ⇒ loss,   -move ⇒ profit
#                 - Iron Condor (Δ ≈ 0): both directions ≈ flat (theta-driven)
STRATEGY_META: dict[str, dict] = {
    "bull_call": {"label": "Bull Call",   "kind": "debit",  "n_legs": 2,
                  "move_mult": +1, "directional": True,
                  "pill_class": "strategy-pill bull-call"},
    "bear_put":  {"label": "Bear Put",    "kind": "debit",  "n_legs": 2,
                  "move_mult": +1, "directional": True,
                  "pill_class": "strategy-pill bear-put"},
    "bull_put":  {"label": "Bull Put",    "kind": "credit", "n_legs": 2,
                  "move_mult": +1, "directional": True,
                  "pill_class": "strategy-pill bull-put"},
    "bear_call": {"label": "Bear Call",   "kind": "credit", "n_legs": 2,
                  "move_mult": +1, "directional": True,
                  "pill_class": "strategy-pill bear-call"},
    "iron_condor": {"label": "Iron Condor", "kind": "credit", "n_legs": 4,
                    "move_mult": +1, "directional": False,
                    "pill_class": "strategy-pill iron-condor"},
}


def _legs_by_type(chain_rows: list[dict], target_type: str) -> list[dict]:
    """Extract usable option legs of a given type ("CALL" or "PUT") from
    a chain payload — returns dicts with strike, mid, symbol, delta."""
    legs: list[dict] = []
    for r in chain_rows or []:
        if str(r.get("type") or "").upper() != target_type:
            continue
        try:
            strike = float(r.get("strike"))
        except (TypeError, ValueError):
            continue
        mid = _row_mid(r)
        if mid is None or mid <= 0:
            continue
        legs.append({
            "strike": strike,
            "mid": mid,
            "symbol": r.get("option_symbol") or "",
            "delta": _safe_float(r.get("delta")),
        })
    legs.sort(key=lambda x: x["strike"])
    return legs


def _leg(symbol: str, side: str, intent: str) -> dict:
    return {"symbol": symbol, "side": side, "ratio_qty": 1,
            "position_intent": intent}


def _net_delta_pair(long_d, short_d) -> float | None:
    if long_d is None or short_d is None:
        return None
    return round(float(long_d) - float(short_d), 4)


# ── 2-leg debit spreads ───────────────────────────────────────────────

def _bull_call_candidates(call_legs: list[dict]) -> list[dict]:
    """Buy lower call + sell higher call (debit, bullish)."""
    rows: list[dict] = []
    for i in range(len(call_legs)):
        for j in range(i + 1, len(call_legs)):
            lo, hi = call_legs[i], call_legs[j]
            width = round(hi["strike"] - lo["strike"], 2)
            if width <= 0:
                continue
            net = round(lo["mid"] - hi["mid"], 2)
            if net <= 0 or net >= width:
                continue
            max_profit = round(width - net, 2)
            if max_profit <= 0:
                continue
            rows.append({
                "strategy": "Bull Call", "kind": "debit", "n_legs": 2,
                "strikes_label": f"{_fmt_strike(lo['strike'])} / {_fmt_strike(hi['strike'])}",
                "lower_strike": lo["strike"],
                "width": width,
                "net": net,
                "max_profit": max_profit,
                "max_loss": net,
                "target_rr": round(max_profit / net, 2),
                "net_delta": _net_delta_pair(lo["delta"], hi["delta"]),
                "legs": [
                    _leg(lo["symbol"], "buy",  "buy_to_open"),
                    _leg(hi["symbol"], "sell", "sell_to_open"),
                ],
            })
    return rows


def _bear_put_candidates(put_legs: list[dict]) -> list[dict]:
    """Buy higher put + sell lower put (debit, bearish)."""
    rows: list[dict] = []
    for i in range(len(put_legs)):
        for j in range(i + 1, len(put_legs)):
            lo, hi = put_legs[i], put_legs[j]
            width = round(hi["strike"] - lo["strike"], 2)
            if width <= 0:
                continue
            net = round(hi["mid"] - lo["mid"], 2)
            if net <= 0 or net >= width:
                continue
            max_profit = round(width - net, 2)
            if max_profit <= 0:
                continue
            rows.append({
                "strategy": "Bear Put", "kind": "debit", "n_legs": 2,
                "strikes_label": f"{_fmt_strike(hi['strike'])} / {_fmt_strike(lo['strike'])}",
                "lower_strike": lo["strike"],
                "width": width,
                "net": net,
                "max_profit": max_profit,
                "max_loss": net,
                "target_rr": round(max_profit / net, 2),
                "net_delta": _net_delta_pair(hi["delta"], lo["delta"]),
                "legs": [
                    _leg(hi["symbol"], "buy",  "buy_to_open"),
                    _leg(lo["symbol"], "sell", "sell_to_open"),
                ],
            })
    return rows


# ── 2-leg credit spreads ──────────────────────────────────────────────

def _bull_put_candidates(put_legs: list[dict]) -> list[dict]:
    """Sell higher put + buy lower put (credit, bullish)."""
    rows: list[dict] = []
    for i in range(len(put_legs)):
        for j in range(i + 1, len(put_legs)):
            lo, hi = put_legs[i], put_legs[j]
            width = round(hi["strike"] - lo["strike"], 2)
            if width <= 0:
                continue
            credit = round(hi["mid"] - lo["mid"], 2)
            if credit <= 0 or credit >= width:
                continue
            max_loss = round(width - credit, 2)
            if max_loss <= 0:
                continue
            rows.append({
                "strategy": "Bull Put", "kind": "credit", "n_legs": 2,
                "strikes_label": f"{_fmt_strike(lo['strike'])} / {_fmt_strike(hi['strike'])}",
                "lower_strike": lo["strike"],
                "width": width,
                "net": credit,
                "max_profit": credit,
                "max_loss": max_loss,
                "target_rr": round(credit / max_loss, 2),
                "net_delta": _net_delta_pair(lo["delta"], hi["delta"]),
                "legs": [
                    _leg(lo["symbol"], "buy",  "buy_to_open"),
                    _leg(hi["symbol"], "sell", "sell_to_open"),
                ],
            })
    return rows


def _bear_call_candidates(call_legs: list[dict]) -> list[dict]:
    """Sell lower call + buy higher call (credit, bearish)."""
    rows: list[dict] = []
    for i in range(len(call_legs)):
        for j in range(i + 1, len(call_legs)):
            lo, hi = call_legs[i], call_legs[j]
            width = round(hi["strike"] - lo["strike"], 2)
            if width <= 0:
                continue
            credit = round(lo["mid"] - hi["mid"], 2)
            if credit <= 0 or credit >= width:
                continue
            max_loss = round(width - credit, 2)
            if max_loss <= 0:
                continue
            rows.append({
                "strategy": "Bear Call", "kind": "credit", "n_legs": 2,
                "strikes_label": f"{_fmt_strike(lo['strike'])} / {_fmt_strike(hi['strike'])}",
                "lower_strike": lo["strike"],
                "width": width,
                "net": credit,
                "max_profit": credit,
                "max_loss": max_loss,
                "target_rr": round(credit / max_loss, 2),
                "net_delta": _net_delta_pair(hi["delta"], lo["delta"]),
                "legs": [
                    _leg(hi["symbol"], "buy",  "buy_to_open"),
                    _leg(lo["symbol"], "sell", "sell_to_open"),
                ],
            })
    return rows


# ── 4-leg Iron Condor ─────────────────────────────────────────────────

def _iron_condor_candidates(call_legs: list[dict], put_legs: list[dict],
                             spot: float | None) -> list[dict]:
    """OTM Bull-Put credit + OTM Bear-Call credit, equal-width wings.

    Requires the underlying spot price to enforce OTM-ness on both shorts."""
    if not call_legs or not put_legs or not spot or spot <= 0:
        return []

    otm_puts  = [l for l in put_legs  if l["strike"] < spot]
    otm_calls = [l for l in call_legs if l["strike"] > spot]
    if len(otm_puts) < 2 or len(otm_calls) < 2:
        return []

    # Pre-compute candidate put-credit and call-credit wings.
    put_wings: list[dict] = []
    for j in range(1, len(otm_puts)):
        for i in range(j):
            lp, sp = otm_puts[i], otm_puts[j]   # long lower, short higher
            w = round(sp["strike"] - lp["strike"], 2)
            credit = round(sp["mid"] - lp["mid"], 2)
            if w <= 0 or credit <= 0:
                continue
            put_wings.append({"lp": lp, "sp": sp, "width": w, "credit": credit})

    call_wings: list[dict] = []
    for i in range(len(otm_calls)):
        for j in range(i + 1, len(otm_calls)):
            sc, lc = otm_calls[i], otm_calls[j]  # short lower, long higher
            w = round(lc["strike"] - sc["strike"], 2)
            credit = round(sc["mid"] - lc["mid"], 2)
            if w <= 0 or credit <= 0:
                continue
            call_wings.append({"sc": sc, "lc": lc, "width": w, "credit": credit})

    rows: list[dict] = []
    for pw in put_wings:
        for cw in call_wings:
            if abs(pw["width"] - cw["width"]) > 1e-6:
                continue   # equal-width wings only (standard IC)
            wing = pw["width"]
            credit = round(pw["credit"] + cw["credit"], 2)
            if credit <= 0 or credit >= wing:
                continue
            max_loss = round(wing - credit, 2)
            if max_loss <= 0:
                continue

            lp, sp = pw["lp"], pw["sp"]
            sc, lc = cw["sc"], cw["lc"]

            deltas = [lp["delta"], sp["delta"], sc["delta"], lc["delta"]]
            if any(d is None for d in deltas):
                net_delta = None
            else:
                # Position-delta = +long_put - short_put - short_call + long_call
                net_delta = round(
                    float(lp["delta"]) - float(sp["delta"])
                    - float(sc["delta"]) + float(lc["delta"]),
                    4,
                )

            rows.append({
                "strategy": "Iron Condor", "kind": "credit", "n_legs": 4,
                "strikes_label": (
                    f"{_fmt_strike(lp['strike'])}/{_fmt_strike(sp['strike'])} "
                    f"\u2502 {_fmt_strike(sc['strike'])}/{_fmt_strike(lc['strike'])}"
                ),
                "lower_strike": lp["strike"],
                "width": wing,
                "net": credit,
                "max_profit": credit,
                "max_loss": max_loss,
                "target_rr": round(credit / max_loss, 2),
                "net_delta": net_delta,
                "legs": [
                    _leg(lp["symbol"], "buy",  "buy_to_open"),
                    _leg(sp["symbol"], "sell", "sell_to_open"),
                    _leg(sc["symbol"], "sell", "sell_to_open"),
                    _leg(lc["symbol"], "buy",  "buy_to_open"),
                ],
            })
    return rows


# ── Public dispatcher ─────────────────────────────────────────────────

def build_candidates(
    chain_rows: list[dict],
    strategy: str,
    spot: float | None = None,
) -> list[dict]:
    """Return every viable candidate for `strategy` in the unified shape
    consumed by the Risk Engine table.  `spot` is required for Iron
    Condor (to enforce OTM short legs)."""
    if not chain_rows:
        return []
    call_legs = _legs_by_type(chain_rows, "CALL")
    put_legs  = _legs_by_type(chain_rows, "PUT")

    if strategy == "bull_call":
        rows = _bull_call_candidates(call_legs)
    elif strategy == "bear_put":
        rows = _bear_put_candidates(put_legs)
    elif strategy == "bull_put":
        rows = _bull_put_candidates(put_legs)
    elif strategy == "bear_call":
        rows = _bear_call_candidates(call_legs)
    elif strategy == "iron_condor":
        rows = _iron_condor_candidates(call_legs, put_legs, spot)
    else:
        rows = []

    rows.sort(key=lambda r: (r["width"], r["net"]))
    return rows


# Back-compat alias — older callers may still import the old name.
build_spread_candidates_from_chain = build_candidates


def _fmt_strike(s: float) -> str:
    """Format a strike: integer if whole, else trim trailing zeros."""
    if abs(s - round(s)) < 1e-6:
        return f"{int(round(s))}"
    return f"{s:.2f}".rstrip("0").rstrip(".")


def _build_trade_tab():
    return html.Div([
        # ── Environment switch ──────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div(id="trade-env-badge",
                                 children="PAPER TRADING",
                                 style={"fontWeight": "700", "fontSize": "0.95rem",
                                        "padding": "6px 16px", "borderRadius": "6px",
                                        "display": "inline-block",
                                        "backgroundColor": "rgba(0,212,126,0.15)",
                                        "color": GREEN, "border": f"1px solid {GREEN}"}),
                    ], md=3, className="d-flex align-items-center"),
                    dbc.Col([
                        dbc.RadioItems(
                            id="trade-env-toggle",
                            options=[{"label": "Paper", "value": "paper"},
                                     {"label": "Live",  "value": "live"}],
                            value="paper", inline=True, className="mt-1",
                        ),
                    ], md=2, className="d-flex align-items-center"),
                    dbc.Col([
                        html.Div([
                            html.Span("Equity: ", className="text-muted", style={"fontSize": "0.8rem"}),
                            html.Span(id="trade-equity", children="$0.00",
                                      style={"fontWeight": "700", "color": "#fff", "fontSize": "0.95rem"}),
                        ], className="me-4", style={"display": "inline-block"}),
                        html.Div([
                            html.Span("Buying Power: ", className="text-muted", style={"fontSize": "0.8rem"}),
                            html.Span(id="trade-buying-power", children="$0.00",
                                      style={"fontWeight": "600", "color": "#d0d0d0"}),
                        ], className="me-4", style={"display": "inline-block"}),
                        html.Div([
                            html.Span("Cash: ", className="text-muted", style={"fontSize": "0.8rem"}),
                            html.Span(id="trade-cash", children="$0.00",
                                      style={"fontWeight": "600", "color": "#d0d0d0"}),
                        ], style={"display": "inline-block"}),
                    ], md=5, className="d-flex align-items-center"),
                    dbc.Col([
                        html.Div([
                            html.Span("Auto:", className="text-muted",
                                      style={"fontSize": "0.8rem", "marginRight": "6px"}),
                            dbc.Select(
                                id="trade-auto-refresh",
                                value="Off",
                                options=[{"label": v, "value": v}
                                         for v in ("Off", "1s", "5s", "10s", "30s", "60s")],
                                style={"backgroundColor": "#1a1a2e",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "color": "#e0e0e0", "width": "80px",
                                       "display": "inline-block", "fontSize": "0.82rem"},
                            ),
                            dbc.Button("Refresh", id="trade-refresh-btn", color="info",
                                       outline=True, size="sm", className="ms-2",
                                       style={"fontWeight": "600"}),
                        ], className="d-flex align-items-center justify-content-end"),
                    ], md=3, className="d-flex align-items-center justify-content-end"),
                ]),
            ], style={"padding": "10px 18px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Two-column: Positions + Trade Controls ──────────────────────
        dbc.Row([
            # Left: Positions table
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(
                        html.H5("Open Positions", className="mb-0",
                                style={"fontWeight": "600", "fontSize": "0.95rem"}),
                        style={"backgroundColor": HEADER_DARK, "border": "none"},
                    ),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id="trade-positions-table",
                            columns=POSITION_COLUMNS,
                            data=[],
                            style_table={"overflowX": "auto", "borderRadius": "6px"},
                            style_header=_shared_header_style,
                            style_cell={**_shared_cell_style, "fontSize": "0.82rem",
                                        "padding": "8px 8px"},
                            style_cell_conditional=[
                                {"if": {"column_id": "symbol"}, "fontWeight": "700",
                                 "color": "#fff", "textAlign": "left", "width": "130px"},
                            ],
                            style_data_conditional=[
                                {"if": {"column_id": "unrealized_pl",
                                        "filter_query": "{unrealized_pl} > 0"},
                                 "color": GREEN, "fontWeight": "600"},
                                {"if": {"column_id": "unrealized_pl",
                                        "filter_query": "{unrealized_pl} < 0"},
                                 "color": RED, "fontWeight": "600"},
                                {"if": {"column_id": "return_pct",
                                        "filter_query": "{return_pct} > 0"},
                                 "color": GREEN, "fontWeight": "600"},
                                {"if": {"column_id": "return_pct",
                                        "filter_query": "{return_pct} < 0"},
                                 "color": RED, "fontWeight": "600"},
                                {"if": {"state": "active"},
                                 "backgroundColor": "#0f3460",
                                 "border": f"1px solid {CYAN}"},
                            ],
                            style_as_list_view=True, page_size=10,
                            cell_selectable=True, row_selectable="single",
                        ),
                    ], style={"padding": "0.5rem"}),
                ], style={"backgroundColor": CELL_DARK,
                          "border": "1px solid rgba(255,255,255,0.06)",
                          "borderRadius": "8px"}),
            ], md=7),

            # Right: Trade controls
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(
                        html.H5("Trade Controls", className="mb-0",
                                style={"fontWeight": "600", "fontSize": "0.95rem"}),
                        style={"backgroundColor": HEADER_DARK, "border": "none"},
                    ),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Symbol", className="text-muted small mb-1"),
                                dbc.Input(id="trade-symbol", type="text",
                                          placeholder="AAPL",
                                          style={"backgroundColor": "#1a1a2e",
                                                 "border": "1px solid rgba(255,255,255,0.12)",
                                                 "color": "#e0e0e0", "fontWeight": "700"}),
                            ], md=6),
                            dbc.Col([
                                dbc.Label("Quantity", className="text-muted small mb-1"),
                                dbc.Input(id="trade-qty", type="number", value=1, min=1,
                                          style={"backgroundColor": "#1a1a2e",
                                                 "border": "1px solid rgba(255,255,255,0.12)",
                                                 "color": "#e0e0e0"}),
                            ], md=6),
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Order Type", className="text-muted small mb-1"),
                                dbc.Select(id="trade-order-type", value="Market",
                                           options=[{"label": "Market", "value": "Market"},
                                                    {"label": "Limit",  "value": "Limit"}],
                                           style={"backgroundColor": "#1a1a2e",
                                                  "border": "1px solid rgba(255,255,255,0.12)",
                                                  "color": "#e0e0e0"}),
                            ], md=4),
                            dbc.Col([
                                dbc.Label("Limit Price", className="text-muted small mb-1"),
                                dbc.Input(id="trade-limit-price", type="number",
                                          disabled=True, placeholder="--",
                                          style={"backgroundColor": "#1a1a2e",
                                                 "border": "1px solid rgba(255,255,255,0.12)",
                                                 "color": "#e0e0e0"}),
                            ], md=4),
                            dbc.Col([
                                dbc.Label("Time in Force", className="text-muted small mb-1"),
                                dbc.Select(id="trade-tif", value="DAY",
                                           options=[{"label": v, "value": v}
                                                    for v in ("DAY", "GTC", "OPG", "IOC", "FOK", "CLS")],
                                           style={"backgroundColor": "#1a1a2e",
                                                  "border": "1px solid rgba(255,255,255,0.12)",
                                                  "color": "#e0e0e0"}),
                            ], md=4),
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Button("BUY", id="trade-buy-btn",
                                           color="success", className="w-100",
                                           style={"fontWeight": "700", "fontSize": "0.95rem"}),
                            ], md=6),
                            dbc.Col([
                                dbc.Button("SELL", id="trade-sell-btn",
                                           color="danger", className="w-100",
                                           style={"fontWeight": "700", "fontSize": "0.95rem"}),
                            ], md=6),
                        ], className="mb-3"),
                        html.Hr(style={"borderColor": "rgba(255,255,255,0.08)"}),
                        dbc.Button("CLOSE ALL POSITIONS", id="trade-close-all-btn",
                                   color="warning", outline=True, size="sm",
                                   className="w-100",
                                   style={"fontWeight": "700"}),
                        html.Hr(style={"borderColor": "rgba(255,255,255,0.08)"}),
                        html.Div("CLOSE MULTI-LEG SPREAD", className="text-muted small mb-1",
                                 style={"fontWeight": "700", "letterSpacing": "0.5px"}),
                        dbc.Select(id="trade-mleg-order-select", options=[], value=None,
                                   placeholder="Refresh to load filled spreads",
                                   style={"backgroundColor": "#1a1a2e",
                                          "border": "1px solid rgba(255,255,255,0.12)",
                                          "color": "#e0e0e0", "fontSize": "0.78rem"}),
                        dbc.Input(id="trade-mleg-close-price", type="number", min=0.01,
                                  step=0.01, placeholder="Closing net limit price",
                                  className="mt-2",
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0", "fontSize": "0.8rem"}),
                        dbc.Row([
                            dbc.Col(dbc.Button("REFRESH SPREADS", id="trade-mleg-refresh-btn",
                                               color="info", outline=True, size="sm",
                                               className="w-100 mt-2"), md=6),
                            dbc.Col(dbc.Button("CLOSE SELECTED SPREAD", id="trade-mleg-close-btn",
                                               color="danger", outline=True, size="sm",
                                               className="w-100 mt-2"), md=6),
                        ]),
                    ], style={"padding": "14px"}),
                ], style={"backgroundColor": CELL_DARK,
                          "border": "1px solid rgba(255,255,255,0.06)",
                          "borderRadius": "8px"}),

                # Activity log
                dbc.Card([
                    dbc.CardHeader(
                        html.H5("Activity Log", className="mb-0",
                                style={"fontWeight": "600", "fontSize": "0.85rem"}),
                        style={"backgroundColor": HEADER_DARK, "border": "none"},
                    ),
                    dbc.CardBody([
                        html.Div(id="trade-log",
                                 style={"maxHeight": "120px", "overflowY": "auto",
                                        "fontSize": "0.78rem", "color": "#aaa",
                                        "fontFamily": "Consolas, monospace",
                                        "whiteSpace": "pre-wrap"}),
                    ], style={"padding": "8px 12px"}),
                ], style={"backgroundColor": CELL_DARK,
                          "border": "1px solid rgba(255,255,255,0.06)",
                          "borderRadius": "8px"}, className="mt-3"),
            ], md=5),
        ], className="mb-3"),

        # ── Options chain (load this FIRST — feeds the Risk Engine) ─────
        dbc.Card([
            dbc.CardHeader(
                dbc.Row([
                    dbc.Col(
                        html.H5("Options Chain", className="mb-0",
                                style={"fontWeight": "600", "fontSize": "0.95rem"}),
                        md=8, className="d-flex align-items-center"),
                    dbc.Col(
                        html.Div([
                            html.Span("STEP 1",
                                      style={"fontSize": "0.65rem",
                                             "letterSpacing": "2px",
                                             "padding": "3px 9px",
                                             "borderRadius": "3px",
                                             "color": CYAN,
                                             "backgroundColor": "rgba(78,205,196,0.12)",
                                             "border": f"1px solid {CYAN}",
                                             "fontWeight": "800"}),
                            html.Span("Load chain → feeds Risk Engine below",
                                      style={"marginLeft": "10px",
                                             "fontSize": "0.78rem",
                                             "color": "#888"}),
                        ], className="d-flex align-items-center justify-content-end"),
                        md=4),
                ]),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Symbol", className="text-muted small mb-1"),
                        dbc.Input(id="opt-symbol", type="text", placeholder="SPY",
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0", "fontWeight": "700"}),
                    ], md=2, sm=4),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        dbc.Button("Load Dates", id="opt-load-dates-btn",
                                   color="info", size="sm",
                                   style={"fontWeight": "600"}),
                    ], md=2, sm=4, className="d-flex flex-column"),
                    dbc.Col([
                        html.Span(id="opt-current-price",
                                  style={"fontWeight": "700", "color": "#b388ff",
                                         "fontSize": "0.95rem", "paddingTop": "26px",
                                         "display": "inline-block"}),
                    ], md=2, sm=4),
                    dbc.Col([
                        dbc.Label("Expiration", className="text-muted small mb-1"),
                        dbc.Select(id="opt-exp-date", placeholder="--",
                                   style={"backgroundColor": "#1a1a2e",
                                          "border": "1px solid rgba(255,255,255,0.12)",
                                          "color": "#e0e0e0"}),
                    ], md=2, sm=4),
                    dbc.Col([
                        dbc.Label("Strikes +/-", className="text-muted small mb-1"),
                        dbc.Input(id="opt-spread", type="number", value=5, min=1, max=30,
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0"}),
                    ], md=1, sm=2),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        dbc.Button("Load Chain", id="opt-load-chain-btn",
                                   color="success", size="sm",
                                   style={"fontWeight": "600"}),
                    ], md=2, sm=4, className="d-flex flex-column"),
                ], align="end", className="mb-3"),

                dcc.Store(id="opt-chain-raw-store", data=[]),
                dcc.Loading(
                    id="opt-chain-loading", type="dot", color=CYAN,
                    children=dash_table.DataTable(
                        id="opt-chain-table",
                        columns=OPTIONS_COLUMNS,
                        data=[],
                        style_table={"overflowX": "auto", "borderRadius": "6px"},
                        style_header=_shared_header_style,
                        style_cell={**_shared_cell_style, "fontSize": "0.8rem",
                                    "padding": "7px 6px"},
                        style_cell_conditional=[
                            {"if": {"column_id": "type"}, "fontWeight": "700", "width": "50px"},
                            {"if": {"column_id": "moneyness"}, "fontWeight": "700",
                             "width": "52px", "letterSpacing": "0.5px",
                             "fontSize": "0.72rem"},
                            {"if": {"column_id": "option_symbol"}, "textAlign": "left",
                             "fontSize": "0.72rem", "color": "#999"},
                        ],
                        style_data_conditional=[
                            {"if": {"column_id": "type",
                                    "filter_query": '{type} = "CALL"'},
                             "color": GREEN, "fontWeight": "700"},
                            {"if": {"column_id": "type",
                                    "filter_query": '{type} = "PUT"'},
                             "color": RED, "fontWeight": "700"},
                            {"if": {"column_id": "moneyness",
                                    "filter_query": '{moneyness} = "ITM"'},
                             "color": "#ffd166",
                             "backgroundColor": "rgba(255,209,102,0.10)"},
                            {"if": {"column_id": "moneyness",
                                    "filter_query": '{moneyness} = "ATM"'},
                             "color": CYAN,
                             "backgroundColor": "rgba(78,205,196,0.12)"},
                            {"if": {"column_id": "moneyness",
                                    "filter_query": '{moneyness} = "OTM"'},
                             "color": "#9aa5b8",
                             "backgroundColor": "rgba(154,165,184,0.08)"},
                            {"if": {"state": "active"},
                             "backgroundColor": "#0f3460",
                             "border": f"1px solid {CYAN}"},
                        ],
                        style_as_list_view=True, page_size=30,
                        cell_selectable=True, row_selectable="single",
                    ),
                ),
            ], style={"padding": "0.75rem"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Risk Engine — Debit Spread Builder (sources from chain above) ─
        dbc.Card([
            dbc.CardHeader(
                dbc.Row([
                    dbc.Col(
                        html.Div([
                            html.Span("STEP 2",
                                      style={"fontSize": "0.65rem",
                                             "letterSpacing": "2px",
                                             "padding": "3px 9px",
                                             "borderRadius": "3px",
                                             "color": CYAN,
                                             "backgroundColor": "rgba(78,205,196,0.12)",
                                             "border": f"1px solid {CYAN}",
                                             "fontWeight": "800",
                                             "marginRight": "10px"}),
                            html.Span("RISK ENGINE",
                                      style={"fontWeight": "800",
                                             "letterSpacing": "2px",
                                             "fontSize": "0.78rem",
                                             "color": CYAN}),
                            html.Span(" \u2022 ",
                                      style={"color": "rgba(255,255,255,0.25)",
                                             "margin": "0 8px"}),
                            html.Span("Debit Spread Builder",
                                      style={"fontWeight": "600",
                                             "fontSize": "0.95rem",
                                             "color": "#e0e0e0"}),
                        ]),
                        md=6, className="d-flex align-items-center"),
                    dbc.Col(
                        html.Div(id="risk-status-pill",
                                 children=[
                                     html.Span("AWAITING CHAIN",
                                               style={"fontSize": "0.68rem",
                                                      "letterSpacing": "1.5px",
                                                      "padding": "3px 10px",
                                                      "borderRadius": "3px",
                                                      "color": "#888",
                                                      "backgroundColor": "rgba(255,255,255,0.05)",
                                                      "border": "1px solid rgba(255,255,255,0.18)",
                                                      "fontWeight": "700"}),
                                 ],
                                 className="d-flex align-items-center justify-content-end"),
                        md=6),
                ]),
                style={"backgroundColor": HEADER_DARK, "border": "none",
                       "padding": "10px 16px"},
            ),
            dbc.CardBody([
                # ── Source line (read-only — mirrors loaded chain) ──────
                html.Div(id="risk-source-display",
                         children=html.Div([
                             html.Span("\u26a0 ", style={"color": "#ffa502",
                                                          "marginRight": "4px"}),
                             html.Span("No options chain loaded.",
                                       style={"color": "#d0d0d0",
                                              "fontWeight": "600"}),
                             html.Span(" Use ",
                                       style={"color": "#888"}),
                             html.Span("Step 1",
                                       style={"color": CYAN, "fontWeight": "700"}),
                             html.Span(" above to load an options chain — "
                                       "the Risk Engine will populate automatically.",
                                       style={"color": "#888"}),
                         ]),
                         style={"padding": "10px 14px",
                                "backgroundColor": "#0f1729",
                                "borderRadius": "5px",
                                "border": "1px solid rgba(255,255,255,0.06)",
                                "fontSize": "0.85rem",
                                "marginBottom": "12px"}),

                # ── Moneyness filter (ITM / ATM / OTM) ─ controls which
                # legs the spread builder is allowed to use.  Rows in the
                # Step 1 chain table are still all classified & visible.
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.Span("MONEYNESS",
                                      style={"fontSize": "0.7rem",
                                             "letterSpacing": "2px",
                                             "fontWeight": "800",
                                             "color": "#888",
                                             "marginRight": "14px"}),
                            dbc.Checklist(
                                id="risk-moneyness-filter",
                                options=[
                                    {"label": "ITM", "value": "ITM"},
                                    {"label": "ATM", "value": "ATM"},
                                    {"label": "OTM", "value": "OTM"},
                                ],
                                value=["ITM", "ATM", "OTM"],
                                inline=True,
                                className="moneyness-checklist",
                                inputClassName="moneyness-input",
                                labelClassName="moneyness-label",
                            ),
                        ], className="d-flex align-items-center"),
                    ], md=6, sm=12),
                    dbc.Col([
                        dbc.Label("ATM tolerance",
                                  className="text-muted small mb-1"),
                        dbc.InputGroup([
                            dbc.InputGroupText(
                                "\u00b1$",
                                style={"backgroundColor": "#0a0f20",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "borderRight": "none",
                                       "color": CYAN,
                                       "fontWeight": "800",
                                       "fontFamily": "'Consolas', monospace"}),
                            dbc.Input(
                                id="risk-atm-tol",
                                type="number",
                                value=1.00,
                                step=0.25,
                                min=0,
                                debounce=False,
                                style={"backgroundColor": "#0f1729",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "borderLeft": "none",
                                       "color": CYAN,
                                       "fontWeight": "700",
                                       "fontFamily": "'Consolas', monospace",
                                       "fontSize": "0.9rem"},
                            ),
                        ]),
                    ], md=2, sm=6),
                    dbc.Col([
                        html.Div("Available legs",
                                 className="text-muted",
                                 style={"fontSize": "0.65rem",
                                        "letterSpacing": "1.5px",
                                        "textAlign": "right",
                                        "fontWeight": "700"}),
                        html.Div(id="risk-moneyness-count",
                                 children="\u2014",
                                 style={"textAlign": "right",
                                        "fontFamily": "'Consolas', monospace",
                                        "fontSize": "0.86rem",
                                        "fontWeight": "700",
                                        "color": "#aaa",
                                        "marginTop": "2px",
                                        "letterSpacing": "0.5px"}),
                    ], md=4, sm=12,
                       className="d-flex flex-column justify-content-center"),
                ], align="center", className="mb-3 risk-moneyness-row"),

                # ── Net Delta range filter ─ keep only spreads whose
                # combined long-vs-short delta falls in [min, max].
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.Span("NET \u0394",
                                      style={"fontSize": "0.7rem",
                                             "letterSpacing": "2px",
                                             "fontWeight": "800",
                                             "color": "#888",
                                             "marginRight": "14px"}),
                            html.Span("range filter",
                                      style={"fontSize": "0.72rem",
                                             "color": "#666",
                                             "fontStyle": "italic"}),
                        ], className="d-flex align-items-center"),
                    ], md=3, sm=12,
                       className="d-flex align-items-center"),
                    dbc.Col([
                        dbc.Label("Min", className="text-muted small mb-1"),
                        dbc.InputGroup([
                            dbc.InputGroupText(
                                "\u0394",
                                style={"backgroundColor": "#0a0f20",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "borderRight": "none",
                                       "color": CYAN,
                                       "fontWeight": "800",
                                       "fontFamily": "'Consolas', monospace"}),
                            dbc.Input(
                                id="risk-delta-min",
                                type="number",
                                value=-1.00,
                                step=0.05,
                                debounce=False,
                                style={"backgroundColor": "#0f1729",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "borderLeft": "none",
                                       "color": CYAN,
                                       "fontWeight": "700",
                                       "fontFamily": "'Consolas', monospace",
                                       "fontSize": "0.9rem"},
                            ),
                        ]),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Max", className="text-muted small mb-1"),
                        dbc.InputGroup([
                            dbc.InputGroupText(
                                "\u0394",
                                style={"backgroundColor": "#0a0f20",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "borderRight": "none",
                                       "color": CYAN,
                                       "fontWeight": "800",
                                       "fontFamily": "'Consolas', monospace"}),
                            dbc.Input(
                                id="risk-delta-max",
                                type="number",
                                value=1.00,
                                step=0.05,
                                debounce=False,
                                style={"backgroundColor": "#0f1729",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "borderLeft": "none",
                                       "color": CYAN,
                                       "fontWeight": "700",
                                       "fontFamily": "'Consolas', monospace",
                                       "fontSize": "0.9rem"},
                            ),
                        ]),
                    ], md=2, sm=6),
                    dbc.Col([
                        html.Div("Δ range hint",
                                 className="text-muted",
                                 style={"fontSize": "0.65rem",
                                        "letterSpacing": "1.5px",
                                        "textAlign": "right",
                                        "fontWeight": "700"}),
                        html.Div(id="risk-delta-hint",
                                 children="any Δ (filter inactive)",
                                 style={"textAlign": "right",
                                        "fontFamily": "'Consolas', monospace",
                                        "fontSize": "0.78rem",
                                        "fontWeight": "700",
                                        "color": "#aaa",
                                        "marginTop": "2px",
                                        "letterSpacing": "0.5px"}),
                    ], md=5, sm=12,
                       className="d-flex flex-column justify-content-center"),
                ], align="end", className="mb-3 risk-delta-row"),

                # ── Strategy + Move Sensitivity + Candidate count row ───
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Strategy", className="text-muted small mb-1"),
                        dbc.Select(
                            id="risk-strategy",
                            value="bull_call",
                            options=[
                                {"label": "Bull Call Spread  \u2014  Debit \u2022 Bullish",
                                 "value": "bull_call"},
                                {"label": "Bear Put Spread   \u2014  Debit \u2022 Bearish",
                                 "value": "bear_put"},
                                {"label": "Bull Put Spread   \u2014  Credit \u2022 Bullish",
                                 "value": "bull_put"},
                                {"label": "Bear Call Spread  \u2014  Credit \u2022 Bearish",
                                 "value": "bear_call"},
                                {"label": "Iron Condor       \u2014  Credit \u2022 Neutral (4 legs)",
                                 "value": "iron_condor"},
                            ],
                            className="risk-strategy-select",
                            style={"backgroundColor": "#0f1729",
                                   "border": "1px solid rgba(255,255,255,0.18)",
                                   "color": "#e0e0e0",
                                   "fontWeight": "700",
                                   "fontFamily": "'Consolas', monospace",
                                   "fontSize": "0.86rem"},
                        ),
                    ], md=6),
                    dbc.Col([
                        dbc.Label("Simulate Price Move ($)",
                                  className="text-muted small mb-1"),
                        dbc.InputGroup([
                            dbc.InputGroupText("$",
                                style={"backgroundColor": "#0a0f20",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "borderRight": "none",
                                       "color": CYAN,
                                       "fontWeight": "800",
                                       "fontFamily": "'Consolas', monospace"}),
                            dbc.Input(
                                id="risk-move-input",
                                type="number",
                                value=1.00,
                                step=0.05,
                                debounce=False,
                                style={"backgroundColor": "#0f1729",
                                       "border": "1px solid rgba(255,255,255,0.12)",
                                       "borderLeft": "none",
                                       "color": CYAN,
                                       "fontWeight": "700",
                                       "fontFamily": "'Consolas', monospace",
                                       "fontSize": "0.95rem"},
                            ),
                        ]),
                        html.Div(id="risk-move-hint",
                                 children="Projecting +$1.00 underlying move (bullish)",
                                 style={"fontSize": "0.7rem",
                                        "color": "#888",
                                        "marginTop": "3px",
                                        "fontFamily": "'Consolas', monospace"}),
                    ], md=3),
                    dbc.Col([
                        html.Div([
                            html.Div("Spreads passing RR",
                                     className="text-muted",
                                     style={"fontSize": "0.7rem",
                                            "letterSpacing": "1px",
                                            "textAlign": "right"}),
                            html.Div(id="risk-candidate-count",
                                     children="0 / 0",
                                     style={"fontWeight": "800",
                                            "fontSize": "1.4rem",
                                            "color": "#888",
                                            "textAlign": "right",
                                            "fontFamily": "'Consolas', monospace",
                                            "lineHeight": "1.1"}),
                        ]),
                    ], md=3, className="d-flex flex-column justify-content-center"),
                ], align="end", className="mb-3"),

                # ── RR Target slider panel ──────────────────────────────
                html.Div(id="risk-rr-panel", children=[
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Span("TARGET RISK : REWARD RATIO",
                                          style={"fontSize": "0.7rem",
                                                 "letterSpacing": "2px",
                                                 "color": "#888",
                                                 "fontWeight": "700",
                                                 "marginRight": "12px"}),
                                # Filter on/off toggle — when OFF, the
                                # RR slider is bypassed and every
                                # candidate (regardless of RR) appears
                                # in the table.
                                dbc.Switch(
                                    id="risk-rr-enable",
                                    value=True,
                                    label=html.Span(
                                        id="risk-rr-enable-label",
                                        children="filter ON",
                                        style={"fontSize": "0.7rem",
                                               "letterSpacing": "1.5px",
                                               "fontWeight": "700",
                                               "color": "#5fdba0"}),
                                    className="risk-rr-toggle d-inline-flex",
                                    style={"display": "inline-block",
                                           "verticalAlign": "middle"}),
                            ], className="d-flex align-items-center"),
                            html.Div([
                                html.Span("1 : ",
                                          style={"fontSize": "1.6rem",
                                                 "color": "#888",
                                                 "fontWeight": "300",
                                                 "marginRight": "4px",
                                                 "fontFamily": "'Consolas', monospace"}),
                                html.Span(id="risk-rr-display", children="1.2",
                                          style={"fontSize": "2.4rem",
                                                 "color": CYAN,
                                                 "fontWeight": "800",
                                                 "fontFamily": "'Consolas', monospace",
                                                 "letterSpacing": "1px"}),
                            ], style={"lineHeight": "1.1", "marginTop": "2px"}),
                            html.Div(id="risk-debit-cap",
                                     children="Max acceptable debit: $4.55 per $10 spread",
                                     style={"fontSize": "0.78rem",
                                            "color": "#888",
                                            "fontFamily": "'Consolas', monospace",
                                            "marginTop": "4px"}),
                        ], md=4),
                        dbc.Col([
                            dcc.Slider(
                                id="risk-rr-slider",
                                # Range extended below 1.0 so credit spreads
                                # (typical RR 0.2–0.8) are visible.  Marks
                                # are denser in the sub-1.0 region for fine
                                # control where credit-spread filters live.
                                min=0.1, max=5.0, step=0.05, value=1.2,
                                marks={
                                    0.1: {"label": "0.1", "style": {"color": "#5fdba0", "fontSize": "0.7rem", "fontWeight": "700"}},
                                    0.25: {"label": "0.25", "style": {"color": "#5fdba0", "fontSize": "0.7rem"}},
                                    0.5: {"label": "0.5", "style": {"color": "#5fdba0", "fontSize": "0.7rem", "fontWeight": "700"}},
                                    0.75: {"label": "0.75", "style": {"color": "#5fdba0", "fontSize": "0.7rem"}},
                                    1.0: {"label": "1.0", "style": {"color": "#aaa", "fontSize": "0.72rem", "fontWeight": "800"}},
                                    1.5: {"label": "1.5", "style": {"color": "#888", "fontSize": "0.72rem"}},
                                    2.0: {"label": "2.0", "style": {"color": "#888", "fontSize": "0.72rem"}},
                                    2.5: {"label": "2.5", "style": {"color": "#888", "fontSize": "0.72rem"}},
                                    3.0: {"label": "3.0", "style": {"color": "#888", "fontSize": "0.72rem"}},
                                    4.0: {"label": "4.0", "style": {"color": "#888", "fontSize": "0.72rem"}},
                                    5.0: {"label": "5.0", "style": {"color": "#888", "fontSize": "0.72rem"}},
                                },
                                tooltip={"placement": "top", "always_visible": False},
                                className="risk-rr-slider",
                                included=True,
                                updatemode="drag",
                            ),
                        ], md=8, className="d-flex flex-column justify-content-center"),
                    ]),
                ], style={"padding": "16px 20px",
                          "backgroundColor": "#0f1729",
                          "borderRadius": "6px",
                          "border": "1px solid rgba(78,205,196,0.18)",
                          "marginBottom": "14px"}),

                # ── Spreads Table ───────────────────────────────────────
                html.Div([
                    html.Table([
                        html.Thead(id="risk-spreads-thead"),
                        html.Tbody(id="risk-spreads-tbody"),
                    ], className="risk-spreads-table",
                       style={"width": "100%",
                              "borderCollapse": "collapse",
                              "fontFamily": "'Consolas', 'Segoe UI', monospace",
                              "fontSize": "0.85rem"}),
                    html.Div(id="risk-spreads-empty",
                             children=[],
                             style={"padding": "40px 20px",
                                    "textAlign": "center",
                                    "color": "#666",
                                    "fontSize": "0.85rem",
                                    "fontStyle": "italic"}),
                ], style={"backgroundColor": "#0f1729",
                          "borderRadius": "6px",
                          "border": "1px solid rgba(255,255,255,0.06)",
                          "overflow": "hidden"}),

                # Hidden stores
                dcc.Store(id="risk-candidates-store", data=[]),
                dcc.Store(id="risk-execute-payload", data=None),
                dcc.Store(id="trade-mleg-orders-store", data=[]),
                dcc.Store(id="risk-sort-store",
                          data={"col": "est_pnl", "dir": "desc"}),
            ], style={"padding": "14px 18px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"},
           className="mb-3"),

        # ── Execute payload preview modal ───────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(
                dbc.ModalTitle([
                    html.Span("MLEG ORDER PAYLOAD",
                              style={"fontWeight": "800", "letterSpacing": "2px",
                                     "fontSize": "0.9rem", "color": CYAN}),
                    html.Span("  (simulated)",
                              style={"color": "#888", "fontWeight": "400",
                                     "fontSize": "0.78rem", "marginLeft": "8px"}),
                ]),
                close_button=True,
                style={"backgroundColor": HEADER_DARK,
                       "borderBottom": f"1px solid {CYAN}"},
            ),
            dbc.ModalBody([
                html.Div(id="risk-execute-summary",
                         style={"marginBottom": "10px",
                                "fontSize": "0.85rem",
                                "color": "#d0d0d0"}),
                html.Div(id="risk-execute-env-banner",
                         style={"marginBottom": "10px",
                                "padding": "8px 12px",
                                "borderRadius": "5px",
                                "fontSize": "0.82rem",
                                "fontWeight": "700"}),

                # Order quantity selector — drives qty in the JSON
                # payload and scales the Total Cost / Max Reward /
                # Max Risk readouts below.
                html.Div([
                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Order Quantity (contracts)",
                                      className="small mb-1",
                                      style={"color": "#aaa",
                                             "letterSpacing": "1px",
                                             "fontWeight": "700"}),
                            dbc.InputGroup([
                                dbc.InputGroupText(
                                    "\u00d7",
                                    style={"backgroundColor": "#0a0f20",
                                           "border": "1px solid rgba(78,205,196,0.40)",
                                           "borderRight": "none",
                                           "color": CYAN,
                                           "fontWeight": "800",
                                           "fontSize": "1.0rem",
                                           "fontFamily": "'Consolas', monospace"}),
                                dbc.Input(
                                    id="risk-execute-qty",
                                    type="number",
                                    value=1,
                                    min=1,
                                    step=1,
                                    debounce=False,
                                    style={"backgroundColor": "#0f1729",
                                           "border": "1px solid rgba(78,205,196,0.40)",
                                           "borderLeft": "none",
                                           "color": CYAN,
                                           "fontWeight": "800",
                                           "fontFamily": "'Consolas', monospace",
                                           "fontSize": "1.05rem",
                                           "letterSpacing": "1px"},
                                ),
                                dbc.InputGroupText(
                                    "contracts",
                                    style={"backgroundColor": "#0a0f20",
                                           "border": "1px solid rgba(78,205,196,0.40)",
                                           "borderLeft": "none",
                                           "color": "#888",
                                           "fontWeight": "600",
                                           "fontSize": "0.78rem",
                                           "letterSpacing": "0.5px"}),
                            ]),
                            html.Div(
                                "Each contract controls 100 shares of the underlying. "
                                "Doubling qty doubles total capital at risk.",
                                style={"color": "#666", "fontSize": "0.7rem",
                                       "marginTop": "4px",
                                       "fontStyle": "italic"}),
                        ], md=5),
                        dbc.Col([
                            html.Div("SCALED TOTALS",
                                     style={"color": "#888",
                                            "fontSize": "0.65rem",
                                            "letterSpacing": "1.5px",
                                            "fontWeight": "700",
                                            "marginBottom": "4px"}),
                            html.Div(id="risk-execute-totals",
                                     children="\u2014",
                                     style={"fontFamily": "'Consolas', monospace",
                                            "fontSize": "0.82rem",
                                            "fontWeight": "700",
                                            "color": "#d0d0d0",
                                            "lineHeight": "1.6"}),
                        ], md=7,
                           className="d-flex flex-column justify-content-center"),
                    ], align="center"),
                ], style={"marginBottom": "12px",
                          "padding": "10px 12px",
                          "backgroundColor": "rgba(78,205,196,0.05)",
                          "border": "1px solid rgba(78,205,196,0.20)",
                          "borderRadius": "6px"}),

                html.Pre(id="risk-execute-json",
                         style={"backgroundColor": "#0a0a1a",
                                "color": "#a0e7df",
                                "padding": "14px 16px",
                                "borderRadius": "6px",
                                "border": "1px solid rgba(78,205,196,0.25)",
                                "fontSize": "0.78rem",
                                "fontFamily": "'Consolas', monospace",
                                "maxHeight": "360px",
                                "overflow": "auto",
                                "whiteSpace": "pre-wrap",
                                "wordBreak": "break-word",
                                "margin": 0}),
                html.Div("This is the exact body that will be POSTed to "
                         "/v2/orders. Submitting will place a real order on "
                         "the selected Alpaca account.",
                         style={"marginTop": "10px",
                                "fontSize": "0.72rem",
                                "color": "#888",
                                "fontStyle": "italic"}),
            ], style={"backgroundColor": CELL_DARK}),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="risk-execute-close", color="secondary",
                           outline=True, size="sm", className="me-auto"),
                dbc.Button("Submit to Alpaca", id="risk-execute-submit",
                           color="success", size="sm",
                           style={"fontWeight": "800", "letterSpacing": "1px",
                                  "minWidth": "180px"}),
            ], style={"backgroundColor": HEADER_DARK, "border": "none"}),
        ], id="risk-execute-modal", is_open=False, centered=True, size="lg"),

        # ── Toast confirmation (transient) ──────────────────────────────
        dbc.Toast(
            id="risk-execute-toast",
            header="Execute (mleg) — simulated",
            icon="success",
            duration=3500,
            is_open=False,
            dismissable=True,
            style={"position": "fixed", "top": "80px", "right": "24px",
                   "zIndex": 9999, "minWidth": "320px",
                   "backgroundColor": HEADER_DARK,
                   "border": f"1px solid {GREEN}",
                   "color": "#e0e0e0"},
        ),

        # Hidden stores & auto-refresh interval
        dcc.Store(id="trade-env-store", data="paper"),
        dcc.Store(id="opt-price-store", data=0),
        dcc.Store(id="trade-log-store", data=[]),
        dcc.Store(id="trade-confirm-action", data=None),
        dcc.Interval(id="trade-auto-interval", interval=1_000_000,
                     n_intervals=0, disabled=True),

        # Confirm modal
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Confirm Trade"), close_button=True),
            dbc.ModalBody(id="trade-confirm-body"),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="trade-confirm-cancel", color="secondary",
                           className="me-2"),
                dbc.Button("Confirm", id="trade-confirm-ok", color="danger",
                           style={"fontWeight": "700"}),
            ]),
        ], id="trade-confirm-modal", is_open=False, centered=True),
    ])


# =========================================================================
# Tab 5 — Price Alerts
# =========================================================================

ALERT_TABLE_COLUMNS = [
    {"name": "ID",        "id": "alert_id",        "type": "text"},
    {"name": "Symbol",    "id": "symbol",           "type": "text"},
    {"name": "Direction", "id": "direction",        "type": "text"},
    {"name": "Target $",  "id": "target_price",     "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Status",    "id": "status",           "type": "text"},
    {"name": "Triggered $", "id": "triggered_price", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Note",      "id": "note",             "type": "text"},
    {"name": "Created",   "id": "created_at",       "type": "text"},
]


def _build_alerts_tab():
    return html.Div([
        # ── Top bar: monitoring status + check interval ─────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div(id="alert-monitor-badge",
                                 children="MONITORING OFF",
                                 style={"fontWeight": "700", "fontSize": "0.9rem",
                                        "padding": "5px 14px", "borderRadius": "6px",
                                        "display": "inline-block",
                                        "backgroundColor": "rgba(255,255,255,0.06)",
                                        "color": "#888",
                                        "border": "1px solid rgba(255,255,255,0.1)"}),
                    ], md=3, className="d-flex align-items-center"),
                    dbc.Col([
                        html.Span("Check every:", className="text-muted",
                                  style={"fontSize": "0.8rem", "marginRight": "6px"}),
                        dbc.Select(
                            id="alert-check-interval",
                            value="Off",
                            options=[{"label": v, "value": v}
                                     for v in ("Off", "30s", "1m", "5m", "15m")],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0", "width": "90px",
                                   "display": "inline-block", "fontSize": "0.82rem"},
                        ),
                        dbc.Button("Check Now", id="alert-check-now-btn", color="info",
                                   outline=True, size="sm", className="ms-2",
                                   style={"fontWeight": "600"}),
                    ], md=4, className="d-flex align-items-center"),
                    dbc.Col([
                        html.Div([
                            html.Span("Active: ", className="text-muted",
                                      style={"fontSize": "0.8rem"}),
                            html.Span(id="alert-active-count", children="0",
                                      style={"fontWeight": "700", "color": CYAN,
                                             "fontSize": "0.95rem", "marginRight": "16px"}),
                            html.Span("Triggered: ", className="text-muted",
                                      style={"fontSize": "0.8rem"}),
                            html.Span(id="alert-triggered-count", children="0",
                                      style={"fontWeight": "700", "color": GREEN,
                                             "fontSize": "0.95rem"}),
                        ]),
                    ], md=3, className="d-flex align-items-center"),
                    dbc.Col([
                        html.Span(id="alert-last-check",
                                  style={"fontSize": "0.75rem", "color": "#666"}),
                    ], md=2, className="d-flex align-items-center justify-content-end"),
                ]),
            ], style={"padding": "10px 18px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Add alert form ──────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.H5("New Alert", className="mb-0",
                        style={"fontWeight": "600", "fontSize": "0.95rem"}),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Symbol", className="text-muted small mb-1"),
                        dbc.Input(id="alert-symbol", type="text", placeholder="AAPL",
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0", "fontWeight": "700"}),
                    ], md=2, sm=4),
                    dbc.Col([
                        dbc.Label("Direction", className="text-muted small mb-1"),
                        dbc.Select(id="alert-direction", value="above",
                                   options=[{"label": "Price Goes Above", "value": "above"},
                                            {"label": "Price Goes Below", "value": "below"}],
                                   style={"backgroundColor": "#1a1a2e",
                                          "border": "1px solid rgba(255,255,255,0.12)",
                                          "color": "#e0e0e0"}),
                    ], md=2, sm=4),
                    dbc.Col([
                        dbc.Label("Target Price $", className="text-muted small mb-1"),
                        dbc.Input(id="alert-target-price", type="number", min=0, step=0.01,
                                  placeholder="150.00",
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0"}),
                    ], md=2, sm=4),
                    dbc.Col([
                        dbc.Label("Note (optional)", className="text-muted small mb-1"),
                        dbc.Input(id="alert-note", type="text", placeholder="Breakout level",
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0"}),
                    ], md=3, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        html.Div([
                            dbc.Button("Add Alert", id="alert-add-btn", color="success",
                                       size="sm", style={"fontWeight": "600"}),
                        ]),
                    ], md=1, sm=3, className="d-flex flex-column"),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        html.Div([
                            dbc.Button("Delete Selected", id="alert-delete-btn",
                                       color="danger", outline=True, size="sm",
                                       style={"fontWeight": "600"}),
                        ]),
                    ], md=2, sm=3, className="d-flex flex-column"),
                ], align="end"),
            ], style={"padding": "12px 18px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Alerts table ────────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.H5("All Alerts", className="mb-0",
                        style={"fontWeight": "600", "fontSize": "0.95rem"}),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dash_table.DataTable(
                    id="alert-table",
                    columns=ALERT_TABLE_COLUMNS,
                    data=[],
                    style_table={"overflowX": "auto", "borderRadius": "6px"},
                    style_header=_shared_header_style,
                    style_cell={**_shared_cell_style, "fontSize": "0.82rem",
                                "padding": "8px 10px"},
                    style_cell_conditional=[
                        {"if": {"column_id": "alert_id"}, "width": "70px",
                         "fontSize": "0.72rem", "color": "#666"},
                        {"if": {"column_id": "symbol"}, "fontWeight": "700",
                         "color": "#fff", "textAlign": "left", "width": "80px"},
                        {"if": {"column_id": "note"}, "textAlign": "left",
                         "fontSize": "0.78rem", "color": "#999", "maxWidth": "200px",
                         "overflow": "hidden", "textOverflow": "ellipsis"},
                        {"if": {"column_id": "created_at"}, "fontSize": "0.72rem",
                         "color": "#777"},
                    ],
                    style_data_conditional=[
                        {"if": {"column_id": "status",
                                "filter_query": '{status} = "active"'},
                         "color": CYAN, "fontWeight": "700"},
                        {"if": {"column_id": "status",
                                "filter_query": '{status} = "triggered"'},
                         "color": GREEN, "fontWeight": "700"},
                        {"if": {"column_id": "direction",
                                "filter_query": '{direction} = "above"'},
                         "color": GREEN},
                        {"if": {"column_id": "direction",
                                "filter_query": '{direction} = "below"'},
                         "color": RED},
                        {"if": {"state": "active"},
                         "backgroundColor": "#0f3460",
                         "border": f"1px solid {CYAN}"},
                    ],
                    style_as_list_view=True, page_size=20,
                    cell_selectable=True, row_selectable="multi",
                ),
            ], style={"padding": "0.5rem"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Activity log ────────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.H5("Alert Log", className="mb-0",
                        style={"fontWeight": "600", "fontSize": "0.85rem"}),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                html.Div(id="alert-log",
                         style={"maxHeight": "160px", "overflowY": "auto",
                                "fontSize": "0.78rem", "color": "#aaa",
                                "fontFamily": "Consolas, monospace",
                                "whiteSpace": "pre-wrap"}),
            ], style={"padding": "8px 12px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}),

        # Hidden stores
        dcc.Store(id="alert-store", data=[]),
        dcc.Store(id="alert-log-store", data=[]),
        dcc.Interval(id="alert-check-interval-timer", interval=1_000_000,
                     n_intervals=0, disabled=True),
    ])


# =========================================================================
# Tab 6 — AI Trading Desk
# =========================================================================

def _build_ai_tab():
    return html.Div([
        # ── Data source controls ─────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.Span("AI Trading Desk",
                                      style={"fontWeight": "700", "fontSize": "1rem",
                                             "color": "#fff", "marginRight": "12px"}),
                            html.Span("Gemini 2.5 Flash Lite",
                                      style={"fontSize": "0.75rem", "color": "#888",
                                             "padding": "2px 8px", "borderRadius": "4px",
                                             "backgroundColor": "rgba(255,255,255,0.06)"}),
                        ]),
                    ], md=4, className="d-flex align-items-center"),
                    dbc.Col([
                        html.Div([
                            dbc.Checklist(
                                id="ai-data-sources",
                                options=[
                                    {"label": " S&P 500 Movers", "value": "sp500"},
                                    {"label": " Insider Buys", "value": "insider_buys"},
                                    {"label": " Insider Sales", "value": "insider_sales"},
                                ],
                                value=["sp500", "insider_buys"],
                                inline=True,
                                className="ai-data-checks",
                                style={"fontSize": "0.82rem"},
                            ),
                        ]),
                    ], md=5, className="d-flex align-items-center"),
                    dbc.Col([
                        html.Div([
                            dbc.Button("Load Data & Start", id="ai-load-data-btn",
                                       color="success", size="sm",
                                       style={"fontWeight": "600", "marginRight": "8px"}),
                            dbc.Button("Clear Chat", id="ai-clear-btn",
                                       color="secondary", outline=True, size="sm",
                                       style={"fontWeight": "600"}),
                        ], className="d-flex justify-content-end"),
                    ], md=3),
                ]),
            ], style={"padding": "10px 18px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Status bar ───────────────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                html.Div(id="ai-status",
                         children="Select data sources above and click Load Data & Start to begin.",
                         style={"fontSize": "0.8rem", "color": "#888"}),
            ], style={"padding": "8px 16px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Data preview (collapsible) ───────────────────────────────────
        dbc.Card([
            dbc.CardHeader([
                html.Div([
                    html.H5("Loaded Data Preview", className="mb-0",
                            style={"fontWeight": "600", "fontSize": "0.9rem",
                                   "display": "inline-block"}),
                    dbc.Button("Show / Hide", id="ai-toggle-preview-btn",
                               color="link", size="sm",
                               style={"fontSize": "0.75rem", "color": CYAN,
                                      "textDecoration": "none", "marginLeft": "12px"}),
                ]),
            ], style={"backgroundColor": HEADER_DARK, "border": "none"}),
            dbc.Collapse([
                dbc.CardBody([
                    html.Div(id="ai-data-preview",
                             children="No data loaded yet.",
                             style={"maxHeight": "300px", "overflowY": "auto",
                                    "fontSize": "0.75rem", "color": "#aaa",
                                    "fontFamily": "Consolas, monospace",
                                    "whiteSpace": "pre-wrap"}),
                ], style={"padding": "10px 14px"}),
            ], id="ai-preview-collapse", is_open=False),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Chat messages ────────────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                html.Div(id="ai-chat-messages",
                         children=[
                             html.Div(
                                 "Load market data to start chatting with the AI trading assistant.",
                                 className="ai-msg ai-msg-system",
                             ),
                         ],
                         style={"height": "calc(100vh - 430px)", "minHeight": "300px",
                                "overflowY": "auto", "padding": "12px 8px"}),
            ], style={"padding": "0"}),
        ], style={"backgroundColor": "#0e0e20",
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Input bar ────────────────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Input(id="ai-user-input", type="text",
                                  placeholder="Ask about market gaps, insider trades, momentum stocks...",
                                  debounce=False, n_submit=0,
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0", "fontSize": "0.9rem"}),
                    ], md=10, sm=9),
                    dbc.Col([
                        dbc.Button("Send", id="ai-send-btn", color="info",
                                   className="w-100",
                                   style={"fontWeight": "700"}),
                    ], md=2, sm=3),
                ]),
            ], style={"padding": "10px 14px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}),

        # Hidden stores
        dcc.Store(id="ai-context-store", data=""),
        dcc.Store(id="ai-history-store", data=[]),
        dcc.Store(id="ai-data-loaded", data=False),
        dcc.Loading(id="ai-loading", type="dot", color=CYAN,
                    parent_style={"position": "fixed", "top": "50%", "left": "50%",
                                  "transform": "translate(-50%, -50%)", "zIndex": "9999"},
                    children=html.Div(id="ai-loading-target")),
    ])


# =========================================================================
# Tab — VOLUME AI (Gemini 2.5 Pro squeeze analyst)
# =========================================================================

def _build_volume_ai_tab():
    return html.Div([
        # ── Header / model badge ─────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.Span("Volume AI \u2014 A+ Squeeze Analyst",
                                      style={"fontWeight": "700",
                                             "fontSize": "1rem",
                                             "color": "#fff",
                                             "marginRight": "12px"}),
                        ]),
                        html.Small(
                            "Grades 5-stage squeeze setups on order-flow data \u2014 "
                            "load a tape and ask questions.",
                            style={"color": "#888",
                                   "fontSize": "0.75rem",
                                   "display": "block",
                                   "marginTop": "4px"}),
                    ], md=7, className="d-flex flex-column justify-content-center"),
                    dbc.Col([
                        dbc.Label("Model",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vai-model",
                            value=VOLUME_AI_DEFAULT_MODEL,
                            options=[{"label": m, "value": m}
                                     for m in VOLUME_AI_MODELS],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(78,205,196,0.30)",
                                   "color": CYAN,
                                   "fontWeight": "700",
                                   "fontSize": "0.8rem"},
                        ),
                    ], md=5, sm=12),
                ], align="center"),
            ], style={"padding": "12px 18px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Tape load controls ───────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Symbol",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vai-symbol", type="text",
                            placeholder="TSLA",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0",
                                   "fontWeight": "700",
                                   "letterSpacing": "1px"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Timeframe",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vai-timeframe",
                            value="5m",
                            options=[
                                {"label": "1 minute",  "value": "1m"},
                                {"label": "5 minutes", "value": "5m"},
                                {"label": "10 minutes", "value": "10m"},
                                {"label": "15 minutes", "value": "15m"},
                                {"label": "30 minutes", "value": "30m"},
                                {"label": "1 hour",    "value": "1h"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Lookback",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vai-lookback",
                            value="1",
                            options=[
                                {"label": "Today",       "value": "1"},
                                {"label": "Last 2 days", "value": "2"},
                                {"label": "Last 5 days", "value": "5"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("From (PT, optional)",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vai-from", type="text",
                            placeholder="06:30",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("To (PT, optional)",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vai-to", type="text",
                            placeholder="13:00",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        html.Div([
                            dbc.Button("Load Tape",
                                       id="vai-load-btn",
                                       color="success", size="sm",
                                       style={"fontWeight": "700",
                                              "marginRight": "6px"}),
                            dbc.Button("Use Current",
                                       id="vai-use-current-btn",
                                       color="info", outline=True, size="sm",
                                       style={"fontWeight": "700",
                                              "marginRight": "6px"}),
                            dbc.Button("Clear",
                                       id="vai-clear-btn",
                                       color="secondary", outline=True,
                                       size="sm",
                                       style={"fontWeight": "700"}),
                        ], className="d-flex"),
                    ], md=2, sm=6),
                ], align="end"),
            ], style={"padding": "12px 18px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Status bar ───────────────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                html.Div(
                    id="vai-status",
                    children=("Load a tape with the controls above (or click "
                              "\u2018Use Current\u2019 to pull whatever is "
                              "loaded in the Volume History tab) to begin."),
                    style={"fontSize": "0.8rem", "color": "#888"},
                ),
            ], style={"padding": "8px 16px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Data preview (collapsible) ───────────────────────────────────
        dbc.Card([
            dbc.CardHeader([
                html.Div([
                    html.H5("Loaded Tape Preview", className="mb-0",
                            style={"fontWeight": "600", "fontSize": "0.9rem",
                                   "display": "inline-block"}),
                    dbc.Button("Show / Hide",
                               id="vai-toggle-preview-btn",
                               color="link", size="sm",
                               style={"fontSize": "0.75rem", "color": CYAN,
                                      "textDecoration": "none",
                                      "marginLeft": "12px"}),
                ]),
            ], style={"backgroundColor": HEADER_DARK, "border": "none"}),
            dbc.Collapse([
                dbc.CardBody([
                    html.Div(id="vai-data-preview",
                             children="No tape loaded yet.",
                             style={"maxHeight": "300px",
                                    "overflowY": "auto",
                                    "fontSize": "0.72rem",
                                    "color": "#aaa",
                                    "fontFamily": "Consolas, monospace",
                                    "whiteSpace": "pre"}),
                ], style={"padding": "10px 14px"}),
            ], id="vai-preview-collapse", is_open=False),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Chat messages ────────────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                html.Div(id="vai-chat-messages",
                         children=[
                             html.Div(
                                 ("Load a volume tape, then ask things like "
                                  "\u201cgrade this session\u201d, \u201cwhat "
                                  "stage are we in at 07:05?\u201d, or "
                                  "\u201cwalk me through the flush bar\u201d."),
                                 className="ai-msg ai-msg-system",
                             ),
                         ],
                         style={"height": "calc(100vh - 480px)",
                                "minHeight": "300px",
                                "overflowY": "auto",
                                "padding": "12px 8px"}),
            ], style={"padding": "0"}),
        ], style={"backgroundColor": "#0e0e20",
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Input bar ────────────────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Input(id="vai-user-input", type="text",
                                  placeholder=("Ask: grade this session, "
                                               "what stage, walk me through "
                                               "the flush bar..."),
                                  debounce=False, n_submit=0,
                                  style={"backgroundColor": "#1a1a2e",
                                         "border": "1px solid rgba(255,255,255,0.12)",
                                         "color": "#e0e0e0",
                                         "fontSize": "0.9rem"}),
                    ], md=10, sm=9),
                    dbc.Col([
                        dbc.Button("Send", id="vai-send-btn", color="info",
                                   className="w-100",
                                   style={"fontWeight": "700"}),
                    ], md=2, sm=3),
                ]),
            ], style={"padding": "10px 14px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}),

        # ── Volume History data table (mirror of what AI sees) ───────────
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.H5("Volume History \u2014 Bar Tape",
                            className="mb-0 d-inline-block",
                            style={"fontWeight": "600",
                                   "fontSize": "0.95rem",
                                   "color": "#fff"}),
                    html.Small(
                        "  same data the AI is reasoning over",
                        style={"marginLeft": "10px", "color": "#888",
                               "fontSize": "0.75rem"}),
                    html.Span(id="vai-table-count",
                              style={"marginLeft": "12px",
                                     "fontSize": "0.75rem",
                                     "color": CYAN,
                                     "fontWeight": "600"}),
                ]),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dash_table.DataTable(
                    id="vai-table",
                    columns=VOL_HIST_TABLE_COLUMNS,
                    data=[],
                    sort_action="native",
                    style_table={"overflowX": "auto",
                                 "maxHeight": "440px",
                                 "overflowY": "auto"},
                    style_header=_shared_header_style,
                    style_cell={**_shared_cell_style,
                                "fontSize": "0.74rem",
                                "padding": "6px 7px"},
                    style_cell_conditional=_VOL_HIST_CELL_CONDITIONAL,
                    style_data_conditional=_vol_hist_conditional_styles(),
                    style_as_list_view=True, page_size=80,
                    fixed_rows={"headers": True},
                ),
            ], style={"padding": "10px 14px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px",
                  "marginTop": "12px"}),

        # Hidden stores
        dcc.Store(id="vai-context-store", data=""),
        dcc.Store(id="vai-history-store", data=[]),
        dcc.Store(id="vai-data-loaded", data=False),
        dcc.Loading(id="vai-loading", type="dot", color=CYAN,
                    parent_style={"position": "fixed", "top": "50%",
                                  "left": "50%",
                                  "transform": "translate(-50%, -50%)",
                                  "zIndex": "9999"},
                    children=html.Div(id="vai-loading-target")),
    ])


# =========================================================================
# Tab 7 — Abnormal Volume Scanner
# =========================================================================

VOLUME_TABLE_COLUMNS = [
    {"name": "Symbol",      "id": "symbol",          "type": "text"},
    {"name": "Price",       "id": "price",           "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Chg %",       "id": "chg",             "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "VWAP",        "id": "vwap",            "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Today Vol",   "id": "today_vol",       "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Typical (so far)", "id": "typical_vol", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Rel Vol",     "id": "rel_vol",         "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "20D Avg Vol", "id": "avg_daily_vol",   "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Buy $ Vol",   "id": "buy_dollar_vol",  "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Sell $ Vol",  "id": "sell_dollar_vol", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Buy %",       "id": "buy_share",       "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"name": "Net Δ $",     "id": "net_delta",       "type": "numeric",
     "format": Format(group=Group.yes, sign=Sign.positive)},
    {"name": "Signal",      "id": "signal",          "type": "text"},
    {"name": "As of",       "id": "as_of",           "type": "text"},
]


def _volume_conditional_styles():
    return [
        # Buy / sell skew on Net Δ
        {"if": {"column_id": "net_delta", "filter_query": "{net_delta} > 0"},
         "color": GREEN, "fontWeight": "600"},
        {"if": {"column_id": "net_delta", "filter_query": "{net_delta} < 0"},
         "color": RED, "fontWeight": "600"},
        # Buy share heat
        {"if": {"column_id": "buy_share", "filter_query": "{buy_share} >= 60"},
         "color": GREEN, "fontWeight": "600"},
        {"if": {"column_id": "buy_share", "filter_query": "{buy_share} <= 40"},
         "color": RED, "fontWeight": "600"},
        # Rel Vol heat
        {"if": {"column_id": "rel_vol", "filter_query": "{rel_vol} >= 2.5"},
         "backgroundColor": "rgba(255,165,2,0.18)", "color": "#ffa502",
         "fontWeight": "700"},
        {"if": {"column_id": "rel_vol", "filter_query": "{rel_vol} >= 1.5 && {rel_vol} < 2.5"},
         "backgroundColor": "rgba(78,205,196,0.12)", "color": CYAN,
         "fontWeight": "700"},
        # Daily change
        {"if": {"column_id": "chg", "filter_query": "{chg} > 0"},
         "color": GREEN, "fontWeight": "600"},
        {"if": {"column_id": "chg", "filter_query": "{chg} < 0"},
         "color": RED, "fontWeight": "600"},
        # Signal pill
        {"if": {"column_id": "signal", "filter_query": '{signal} contains "EXTREME"'},
         "color": "#ffa502", "fontWeight": "700"},
        {"if": {"column_id": "signal", "filter_query": '{signal} contains "ABNORMAL"'},
         "color": CYAN, "fontWeight": "700"},
        {"if": {"column_id": "signal", "filter_query": '{signal} contains "BUY"'},
         "color": GREEN, "fontWeight": "700"},
        {"if": {"column_id": "signal", "filter_query": '{signal} contains "SELL"'},
         "color": RED, "fontWeight": "700"},
        {"if": {"state": "active"},
         "backgroundColor": "#0f3460", "border": f"1px solid {CYAN}"},
    ]


SPIKE_TABLE_COLUMNS = [
    {"name": "Time",       "id": "ts",          "type": "text"},
    {"name": "Symbol",     "id": "symbol",      "type": "text"},
    {"name": "Price",      "id": "price",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Bar Chg %",  "id": "chg_bar",     "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)},
    {"name": "5m Volume",  "id": "volume",      "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Vol Z",      "id": "vol_z",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Rel Vol",    "id": "rel_vol",     "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Buy $",      "id": "buy_dollar",  "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Sell $",     "id": "sell_dollar", "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Buy %",      "id": "buy_share",   "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"name": "Delta $",    "id": "delta",       "type": "numeric",
     "format": Format(group=Group.yes, sign=Sign.positive)},
    {"name": "Signal",     "id": "signal",      "type": "text"},
]


def _spike_conditional_styles():
    return [
        {"if": {"column_id": "delta", "filter_query": "{delta} > 0"},
         "color": GREEN, "fontWeight": "600"},
        {"if": {"column_id": "delta", "filter_query": "{delta} < 0"},
         "color": RED, "fontWeight": "600"},
        {"if": {"column_id": "buy_share", "filter_query": "{buy_share} >= 65"},
         "color": GREEN, "fontWeight": "600"},
        {"if": {"column_id": "buy_share", "filter_query": "{buy_share} <= 35"},
         "color": RED, "fontWeight": "600"},
        {"if": {"column_id": "vol_z", "filter_query": "{vol_z} >= 3"},
         "backgroundColor": "rgba(255,165,2,0.18)", "color": "#ffa502",
         "fontWeight": "700"},
        {"if": {"column_id": "vol_z", "filter_query": "{vol_z} >= 2 && {vol_z} < 3"},
         "backgroundColor": "rgba(78,205,196,0.12)", "color": CYAN,
         "fontWeight": "700"},
        {"if": {"column_id": "rel_vol", "filter_query": "{rel_vol} >= 3"},
         "color": "#ffa502", "fontWeight": "700"},
        {"if": {"column_id": "rel_vol", "filter_query": "{rel_vol} >= 1.8 && {rel_vol} < 3"},
         "color": CYAN, "fontWeight": "700"},
        {"if": {"column_id": "chg_bar", "filter_query": "{chg_bar} > 0"},
         "color": GREEN},
        {"if": {"column_id": "chg_bar", "filter_query": "{chg_bar} < 0"},
         "color": RED},
        {"if": {"column_id": "signal", "filter_query": '{signal} contains "EXTREME"'},
         "color": "#ffa502", "fontWeight": "700"},
        {"if": {"column_id": "signal", "filter_query": '{signal} contains "STRONG"'},
         "color": CYAN, "fontWeight": "700"},
        {"if": {"column_id": "signal", "filter_query": '{signal} contains "BUY"'},
         "color": GREEN, "fontWeight": "700"},
        {"if": {"column_id": "signal", "filter_query": '{signal} contains "SELL"'},
         "color": RED, "fontWeight": "700"},
        {"if": {"state": "active"},
         "backgroundColor": "#0f3460", "border": f"1px solid {CYAN}"},
    ]


def _build_volume_tab():
    default_text = ", ".join(MAG7_SYMBOLS)

    return html.Div([
        # ── Controls (row 1: universe) ────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Symbols",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vol-symbols-input", type="text",
                            value=default_text,
                            placeholder="e.g. AAPL, MSFT, NVDA, TSLA, AMZN",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0", "fontWeight": "600"},
                        ),
                    ], md=6, sm=12),
                    dbc.Col([
                        dbc.Label("Preset",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-preset",
                            value="MAG7",
                            options=[
                                {"label": "Magnificent 7", "value": "MAG7"},
                                {"label": "Custom (use input)", "value": "CUSTOM"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Auto-refresh",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-refresh-interval",
                            value="Off",
                            options=[{"label": v, "value": v}
                                     for v in ("Off", "30s", "1m", "5m")],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        dbc.Button("Scan Now", id="vol-scan-btn",
                                   color="info", className="w-100",
                                   style={"fontWeight": "700"}),
                    ], md=2, sm=6),
                ], align="end", className="mb-2"),

                # ── Controls (row 2: 5m spike options) ───────────────────
                html.Hr(style={"borderColor": "rgba(255,255,255,0.06)",
                               "margin": "8px 0"}),
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            dbc.Switch(
                                id="vol-spike-toggle",
                                label="Detect 5m Volume / Delta Spikes",
                                value=False,
                                style={"display": "inline-block",
                                       "fontWeight": "600",
                                       "color": "#fff", "fontSize": "0.85rem"},
                            ),
                        ]),
                    ], md=4, sm=12, className="d-flex align-items-center"),
                    dbc.Col([
                        dbc.Label("Sensitivity (vol z-score)",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-spike-z",
                            value="2.0",
                            options=[
                                {"label": "Loose (z \u2265 1.5)", "value": "1.5"},
                                {"label": "Default (z \u2265 2.0)", "value": "2.0"},
                                {"label": "Strict (z \u2265 2.5)", "value": "2.5"},
                                {"label": "Extreme (z \u2265 3.0)", "value": "3.0"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=3, sm=6),
                    dbc.Col([
                        dbc.Label("Lookback",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-spike-lookback",
                            value="1d",
                            options=[
                                {"label": "Today only", "value": "1d"},
                                {"label": "Last 5 days", "value": "5d"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Auto-scan spikes every",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-spike-refresh-interval",
                            value="Off",
                            options=[{"label": v, "value": v}
                                     for v in ("Off", "1m", "2m", "5m",
                                               "10m", "15m")],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        html.Div(id="vol-spike-status",
                                 style={"fontSize": "0.72rem", "color": "#666",
                                        "textAlign": "right",
                                        "paddingTop": "26px"}),
                    ], md=1, sm=12),
                ], align="end"),
            ], style={"padding": "12px 18px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Summary cards ─────────────────────────────────────────────────
        dbc.Row(id="vol-summary-cards", className="mb-3 gx-3"),

        # ── Status / last-scan ────────────────────────────────────────────
        html.Div(id="vol-status-text",
                 style={"fontSize": "0.78rem", "color": "#888",
                        "marginBottom": "8px"}),

        # ── Results table ─────────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.H5("Order-Flow Pressure",
                        className="mb-0",
                        style={"fontWeight": "600", "fontSize": "0.95rem"}),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dcc.Loading(
                    id="vol-table-loading", type="dot", color=CYAN,
                    children=dash_table.DataTable(
                        id="vol-table",
                        columns=VOLUME_TABLE_COLUMNS,
                        data=[],
                        sort_action="native",
                        style_table={"overflowX": "auto", "borderRadius": "6px"},
                        style_header=_shared_header_style,
                        style_cell={**_shared_cell_style, "fontSize": "0.82rem",
                                    "padding": "9px 8px"},
                        style_cell_conditional=[
                            {"if": {"column_id": "symbol"}, "fontWeight": "700",
                             "color": "#fff", "textAlign": "left", "width": "70px"},
                            {"if": {"column_id": "signal"}, "textAlign": "left",
                             "minWidth": "150px", "fontWeight": "700"},
                            {"if": {"column_id": "as_of"}, "fontSize": "0.72rem",
                             "color": "#777"},
                        ],
                        style_data_conditional=_volume_conditional_styles(),
                        style_as_list_view=True, page_size=20,
                        cell_selectable=True,
                    ),
                ),
            ], style={"padding": "0.5rem"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── 5-minute spike feed (visible only when toggle is on) ─────────
        html.Div(id="vol-spike-card-wrapper", style={"display": "none"},
                 children=[
            dbc.Card([
                dbc.CardHeader(
                    html.Div([
                        html.H5("5-Minute Volume / Delta Spikes",
                                className="mb-0 d-inline-block",
                                style={"fontWeight": "600",
                                       "fontSize": "0.95rem"}),
                        html.Span(id="vol-spike-count",
                                  style={"marginLeft": "10px",
                                         "fontSize": "0.78rem",
                                         "color": "#888"}),
                    ]),
                    style={"backgroundColor": HEADER_DARK, "border": "none"},
                ),
                dbc.CardBody([
                    dcc.Loading(
                        id="vol-spike-loading", type="dot", color=CYAN,
                        children=dash_table.DataTable(
                            id="vol-spike-table",
                            columns=SPIKE_TABLE_COLUMNS,
                            data=[],
                            sort_action="native",
                            style_table={"overflowX": "auto",
                                         "borderRadius": "6px",
                                         "maxHeight": "520px",
                                         "overflowY": "auto"},
                            style_header=_shared_header_style,
                            style_cell={**_shared_cell_style,
                                        "fontSize": "0.78rem",
                                        "padding": "7px 8px"},
                            style_cell_conditional=[
                                {"if": {"column_id": "ts"}, "fontFamily": "Consolas, monospace",
                                 "color": "#bbb", "width": "140px"},
                                {"if": {"column_id": "symbol"}, "fontWeight": "700",
                                 "color": "#fff", "width": "70px"},
                                {"if": {"column_id": "signal"},
                                 "textAlign": "left", "minWidth": "140px",
                                 "fontWeight": "700"},
                            ],
                            style_data_conditional=_spike_conditional_styles(),
                            style_as_list_view=True,
                            page_size=25, cell_selectable=True,
                            fixed_rows={"headers": True},
                        ),
                    ),
                ], style={"padding": "0.5rem"}),
            ], style={"backgroundColor": CELL_DARK,
                      "border": "1px solid rgba(255,255,255,0.06)",
                      "borderRadius": "8px"}, className="mb-3"),
        ]),

        # ── Volume History (chronological per-bar tape) ──────────────────
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.H5("Volume History",
                            className="mb-0 d-inline-block",
                            style={"fontWeight": "600",
                                   "fontSize": "0.95rem", "color": "#fff"}),
                    html.Small(
                        "  bar-by-bar tape of price + order-flow at every "
                        "interval (1m \u2192 1h)",
                        style={"marginLeft": "10px", "color": "#888",
                               "fontSize": "0.75rem"}),
                ]),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Symbol",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vol-hist-symbol", type="text",
                            placeholder="TSLA  (or pick from list)",
                            list="vol-hist-symbol-presets",
                            autoComplete="off",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0", "fontWeight": "700",
                                   "letterSpacing": "1px"},
                        ),
                        html.Datalist(
                            id="vol-hist-symbol-presets",
                            children=[
                                html.Option(value="AAPL",  label="Apple"),
                                html.Option(value="MSFT",  label="Microsoft"),
                                html.Option(value="GOOGL", label="Alphabet"),
                                html.Option(value="AMZN",  label="Amazon"),
                                html.Option(value="NVDA",  label="NVIDIA"),
                                html.Option(value="META",  label="Meta"),
                                html.Option(value="TSLA",  label="Tesla"),
                                html.Option(value="SPY",   label="S&P 500 ETF"),
                                html.Option(value="QQQ",   label="Nasdaq 100 ETF"),
                            ],
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Timeframe",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-hist-timeframe",
                            value="5m",
                            options=[
                                {"label": "1 minute",   "value": "1m"},
                                {"label": "5 minutes",  "value": "5m"},
                                {"label": "10 minutes", "value": "10m"},
                                {"label": "15 minutes", "value": "15m"},
                                {"label": "30 minutes", "value": "30m"},
                                {"label": "1 hour",     "value": "1h"},
                                {"label": "2 hours",    "value": "2h"},
                                {"label": "4 hours",    "value": "4h"},
                                {"label": "1 day",      "value": "1d"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Lookback",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-hist-lookback",
                            value="1",
                            options=[
                                {"label": "Today",       "value": "1"},
                                {"label": "Last 2 days", "value": "2"},
                                {"label": "Last 5 days", "value": "5"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("From (PT, optional)",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vol-hist-from", type="text",
                            placeholder="06:30",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("To (PT, optional)",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vol-hist-to", type="text",
                            placeholder="13:00",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        dbc.Button("Load Tape", id="vol-hist-load-btn",
                                   color="info", className="w-100",
                                   style={"fontWeight": "700"}),
                    ], md=2, sm=6),
                ], align="end", className="mb-3"),

                dbc.Row([
                    dbc.Col([
                        dbc.Label("Auto-refresh tape", className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-hist-refresh-interval",
                            value="Off",
                            options=[{"label": v, "value": v}
                                     for v in ("Off", "30s", "1m", "2m", "5m")],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=3, sm=6),
                ], className="mb-2"),

                # Status + sort order + download
                dbc.Row([
                    dbc.Col([
                        html.Div(id="vol-hist-status",
                                 style={"fontSize": "0.78rem",
                                        "color": "#888"}),
                    ], md=6, sm=12),
                    dbc.Col([
                        dbc.RadioItems(
                            id="vol-hist-order",
                            options=[
                                {"label": "Newest first", "value": "desc"},
                                {"label": "Oldest first", "value": "asc"},
                            ],
                            value="asc", inline=True,
                            inputStyle={"marginRight": "4px",
                                         "marginLeft": "10px"},
                            labelStyle={"fontSize": "0.78rem",
                                         "color": "#aaa"},
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-download me-1"),
                             "CSV"],
                            id="vol-hist-download-btn",
                            color="secondary", outline=True, size="sm",
                            className="ms-3",
                            style={"fontWeight": "600",
                                   "fontSize": "0.75rem"},
                        ),
                        dcc.Download(id="vol-hist-download"),
                    ], md=6, sm=12,
                       className="d-flex justify-content-end align-items-center"),
                ], className="mb-2"),

                # Summary cards
                dbc.Row(id="vol-hist-summary", className="mb-3 gx-3"),

                # Bar tape table
                dcc.Loading(
                    id="vol-hist-loading", type="dot", color=CYAN,
                    children=dash_table.DataTable(
                        id="vol-hist-table",
                        columns=VOL_HIST_TABLE_COLUMNS,
                        data=[],
                        sort_action="native",
                        style_table={"overflowX": "auto",
                                     "maxHeight": "560px",
                                     "overflowY": "auto"},
                        style_header=_shared_header_style,
                        style_cell={**_shared_cell_style,
                                    "fontSize": "0.74rem",
                                    "padding": "6px 7px"},
                        style_cell_conditional=_VOL_HIST_CELL_CONDITIONAL,
                        style_data_conditional=_vol_hist_conditional_styles(),
                        style_as_list_view=True, page_size=80,
                        fixed_rows={"headers": True},
                    ),
                ),
            ], style={"padding": "14px 18px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Volume Profile (TradingView + POC/Value Area) ────────────────
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.H5("Volume Profile",
                            className="mb-0 d-inline-block",
                            style={"fontWeight": "600",
                                   "fontSize": "0.95rem", "color": "#fff"}),
                    html.Small(
                        "  TradingView chart + profile from loaded Volume History",
                        style={"marginLeft": "10px", "color": "#888",
                               "fontSize": "0.75rem"}),
                ]),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Session Day", className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-prof-session",
                            value="ALL",
                            options=[{"label": "All loaded days", "value": "ALL"}],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=3, sm=6),
                    dbc.Col([
                        dbc.Label("Profile Bins", className="text-muted small mb-1"),
                        dbc.Input(id="vol-prof-bins", type="number", value=36,
                                  min=12, max=120, step=1),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Value Area %", className="text-muted small mb-1"),
                        dbc.Input(id="vol-prof-va-pct", type="number", value=70,
                                  min=50, max=99, step=1),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        dbc.Button("Build Volume Profile", id="vol-prof-build-btn",
                                   color="info", className="w-100",
                                   style={"fontWeight": "700"}),
                    ], md=3, sm=6),
                    dbc.Col([
                        html.Div(id="vol-prof-status",
                                 style={"fontSize": "0.78rem", "color": "#888",
                                        "paddingTop": "26px"}),
                    ], md=2, sm=12),
                ], align="end", className="mb-3"),

                dbc.Row(id="vol-prof-summary", className="mb-3 gx-3"),

                dbc.Row([
                    dbc.Col([
                        dcc.Graph(
                            id="vol-prof-price-chart",
                            figure=go.Figure(layout={
                                "template": "plotly_dark",
                                "paper_bgcolor": "#1a1a2e",
                                "plot_bgcolor": "#1a1a2e",
                                "height": 430,
                                "margin": {"t": 30, "b": 35, "l": 45, "r": 15},
                                "annotations": [{
                                    "text": "Build profile to load Alpaca price chart",
                                    "xref": "paper", "yref": "paper",
                                    "x": 0.5, "y": 0.5,
                                    "showarrow": False,
                                    "font": {"color": "#666", "size": 12},
                                }],
                                "xaxis": {"visible": False},
                                "yaxis": {"visible": False},
                            }),
                            config={"displaylogo": False, "scrollZoom": True},
                            style={"height": "430px"},
                        ),
                    ], md=8, sm=12),
                    dbc.Col([
                        dcc.Graph(
                            id="vol-prof-hist-chart",
                            figure=go.Figure(layout={
                                "template": "plotly_dark",
                                "paper_bgcolor": "#1a1a2e",
                                "plot_bgcolor": "#1a1a2e",
                                "height": 430,
                                "margin": {"t": 25, "b": 40, "l": 30, "r": 15},
                                "annotations": [{
                                    "text": "Click 'Build Volume Profile' after loading Volume History",
                                    "xref": "paper", "yref": "paper",
                                    "x": 0.5, "y": 0.5,
                                    "showarrow": False,
                                    "font": {"color": "#666", "size": 12},
                                }],
                                "xaxis": {"visible": False},
                                "yaxis": {"visible": False},
                            }),
                            config={"displaylogo": False},
                            style={"height": "430px"},
                        ),
                    ], md=4, sm=12),
                ], className="g-3"),

                html.Div(id="vol-prof-zones", className="mt-3",
                         style={"fontSize": "0.8rem", "color": "#bbb"}),
            ], style={"padding": "14px 18px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Move Investigator ─────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.H5("Move Investigator",
                            className="mb-0 d-inline-block",
                            style={"fontWeight": "600",
                                   "fontSize": "0.95rem", "color": "#fff"}),
                    html.Small(
                        "  why did it move? \u2014 enter a symbol and an "
                        "optional time window (PT)",
                        style={"marginLeft": "10px", "color": "#888",
                               "fontSize": "0.75rem"}),
                ]),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                # Controls
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Symbol",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vol-inv-symbol", type="text",
                            placeholder="TSLA",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0",
                                   "fontWeight": "700",
                                   "letterSpacing": "1px"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Start (PT)",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vol-inv-start", type="text",
                            placeholder="07:20  or  2026-04-30 07:20",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=3, sm=6),
                    dbc.Col([
                        dbc.Label("End (PT)",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="vol-inv-end", type="text",
                            placeholder="11:30  or  2026-04-30 11:30",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=3, sm=6),
                    dbc.Col([
                        dbc.Label("Lookback",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="vol-inv-lookback",
                            value="2",
                            options=[
                                {"label": "Today", "value": "1"},
                                {"label": "Last 2 days", "value": "2"},
                                {"label": "Last 5 days", "value": "5"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        dbc.Button("Investigate", id="vol-inv-run-btn",
                                   color="warning", className="w-100",
                                   style={"fontWeight": "700"}),
                    ], md=2, sm=6),
                ], align="end", className="mb-3"),

                # Status
                html.Div(id="vol-inv-status",
                         style={"fontSize": "0.78rem", "color": "#888",
                                "marginBottom": "10px"}),

                # Window summary cards
                dbc.Row(id="vol-inv-summary", className="mb-3 gx-3"),

                # Chart
                dcc.Loading(
                    id="vol-inv-chart-loading", type="dot", color=CYAN,
                    children=dcc.Graph(
                        id="vol-inv-chart",
                        figure=go.Figure(layout={
                            "template": "plotly_dark",
                            "paper_bgcolor": "#1a1a2e",
                            "plot_bgcolor": "#1a1a2e",
                            "height": 560,
                            "margin": {"t": 20, "b": 30, "l": 50, "r": 20},
                            "annotations": [{
                                "text": "Enter a symbol and click Investigate",
                                "xref": "paper", "yref": "paper",
                                "x": 0.5, "y": 0.5,
                                "showarrow": False,
                                "font": {"color": "#666", "size": 14},
                            }],
                            "xaxis": {"visible": False},
                            "yaxis": {"visible": False},
                        }),
                        config={"displaylogo": False, "scrollZoom": True},
                        style={"height": "560px"},
                    ),
                ),

                # Bottom row: spikes + news
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.H6("5m Spikes in Window",
                                    style={"fontWeight": "600",
                                           "fontSize": "0.85rem",
                                           "color": "#fff",
                                           "marginBottom": "8px",
                                           "marginTop": "12px"}),
                            dash_table.DataTable(
                                id="vol-inv-spike-table",
                                columns=[
                                    {"name": "Time",   "id": "ts",        "type": "text"},
                                    {"name": "Price",  "id": "price",     "type": "numeric",
                                     "format": Format(precision=2, scheme=Scheme.fixed)},
                                    {"name": "Vol Z",  "id": "vol_z",     "type": "numeric",
                                     "format": Format(precision=2, scheme=Scheme.fixed)},
                                    {"name": "Rel",    "id": "rel_vol",   "type": "numeric",
                                     "format": Format(precision=2, scheme=Scheme.fixed)},
                                    {"name": "Buy %",  "id": "buy_share", "type": "numeric",
                                     "format": Format(precision=1, scheme=Scheme.fixed)},
                                    {"name": "Delta $", "id": "delta",    "type": "numeric",
                                     "format": Format(group=Group.yes, sign=Sign.positive)},
                                    {"name": "Signal", "id": "signal",    "type": "text"},
                                ],
                                data=[],
                                sort_action="native",
                                style_table={"overflowX": "auto", "maxHeight": "320px",
                                              "overflowY": "auto"},
                                style_header=_shared_header_style,
                                style_cell={**_shared_cell_style,
                                            "fontSize": "0.76rem",
                                            "padding": "6px 8px"},
                                style_cell_conditional=[
                                    {"if": {"column_id": "ts"},
                                     "fontFamily": "Consolas, monospace",
                                     "color": "#bbb"},
                                    {"if": {"column_id": "signal"},
                                     "textAlign": "left",
                                     "fontWeight": "700"},
                                ],
                                style_data_conditional=_spike_conditional_styles(),
                                style_as_list_view=True, page_size=15,
                                fixed_rows={"headers": True},
                            ),
                        ]),
                    ], md=7, sm=12),
                    dbc.Col([
                        html.Div([
                            html.H6("Recent News",
                                    style={"fontWeight": "600",
                                           "fontSize": "0.85rem",
                                           "color": "#fff",
                                           "marginBottom": "8px",
                                           "marginTop": "12px"}),
                            html.Div(id="vol-inv-news",
                                     style={"maxHeight": "320px",
                                            "overflowY": "auto",
                                            "padding": "4px"}),
                        ]),
                    ], md=5, sm=12),
                ]),
            ], style={"padding": "14px 18px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Methodology blurb ─────────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.Strong("How it works:  ",
                                style={"color": "#fff"}),
                    "Today's cumulative session volume is compared against the "
                    "average cumulative volume at the same time-of-day across the "
                    "previous 5 sessions. ",
                    html.Span("Rel Vol \u2265 1.5x ", style={"color": CYAN,
                                                              "fontWeight": "600"}),
                    "is flagged as ",
                    html.Span("ABNORMAL", style={"color": CYAN,
                                                  "fontWeight": "700"}),
                    "; ",
                    html.Span("Rel Vol \u2265 2.5x ", style={"color": "#ffa502",
                                                              "fontWeight": "600"}),
                    "as ",
                    html.Span("EXTREME", style={"color": "#ffa502",
                                                "fontWeight": "700"}),
                    ". The ",
                    html.Strong("5-minute spike detector", style={"color": "#fff"}),
                    " flags individual 5m bars whose volume z-score exceeds the "
                    "selected threshold against a trailing 20-bar baseline (~100 "
                    "min); each bar's buy / sell pressure comes from the 1-minute "
                    "sub-bars inside it. The ",
                    html.Strong("Move Investigator",
                                 style={"color": "#fff"}),
                    " correlates an intraday move with order-flow + news: "
                    "candles, VWAP, per-minute volume colored by direction, "
                    "and a session-aware cumulative-delta curve. Tick-rule "
                    "classification is used throughout (close > open = buy, "
                    "close < open = sell) since level-2 order-book data is "
                    "not available via yfinance.",
                ], style={"fontSize": "0.78rem", "color": "#aaa",
                          "lineHeight": "1.5"}),
            ], style={"padding": "10px 14px"}),
        ], style={"backgroundColor": "#0e0e20",
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}),

        # Hidden bits
        dcc.Store(id="vol-data-store", data=[]),
        dcc.Store(id="vol-spike-store", data=[]),
        dcc.Store(id="vol-inv-timeline-store", data=None),
        dcc.Store(id="vol-hist-store", data=[]),
        dcc.Interval(id="vol-refresh-timer",
                     interval=1_000_000, n_intervals=0, disabled=True),
        dcc.Interval(id="vol-spike-refresh-timer",
                     interval=1_000_000, n_intervals=0, disabled=True),
        dcc.Interval(id="vol-hist-refresh-timer",
                     interval=1_000_000, n_intervals=0, disabled=True),
    ])


OVERNIGHT_BOARD_COLUMNS = [
    {"name": "Symbol",   "id": "symbol",   "type": "text"},
    {"name": "Spot",     "id": "spot",     "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Day %",    "id": "chg_pct",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed,
                      sign=Sign.positive)},
    {"name": "Range %",  "id": "range_pos","type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"name": "Bias",     "id": "bias_score","type": "numeric"},
    {"name": "Label",    "id": "bias_label","type": "text"},
    {"name": "Call $M",  "id": "call_notional_m", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Put $M",   "id": "put_notional_m",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "C/P",      "id": "cp_ratio", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Call Agg", "id": "call_agg", "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"name": "Put Agg",  "id": "put_agg",  "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"name": "Top Call", "id": "top_call_strike", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "C Vol/OI", "id": "top_call_vol_oi", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Top Put",  "id": "top_put_strike",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "P Vol/OI", "id": "top_put_vol_oi",  "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "LH Δ $",   "id": "last_hour_delta", "type": "numeric",
     "format": Format(group=Group.yes, sign=Sign.positive)},
    {"name": "LH RelVol","id": "last_hour_rel",   "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "News 6h",  "id": "news_count",      "type": "numeric"},
]


OVERNIGHT_FLOW_COLUMNS = [
    {"name": "Expiry",  "id": "expiry",    "type": "text"},
    {"name": "DTE",     "id": "dte",       "type": "numeric"},
    {"name": "Strike",  "id": "strike",    "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "OTM %",   "id": "moneyness", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed,
                      sign=Sign.positive)},
    {"name": "Volume",  "id": "volume",    "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "OI",      "id": "oi",        "type": "numeric",
     "format": Format(group=Group.yes)},
    {"name": "Vol/OI",  "id": "vol_oi",    "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Last",    "id": "last",      "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Bid",     "id": "bid",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Ask",     "id": "ask",       "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"name": "Agg %",   "id": "agg",       "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"name": "$K",      "id": "notional_k","type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed,
                      group=Group.yes)},
    {"name": "IV %",    "id": "iv",        "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
]


def _overnight_board_conditional() -> list[dict]:
    return [
        {"if": {"filter_query": "{bias_score} >= 40", "column_id": "bias_label"},
         "color": "#00d47e", "fontWeight": "700"},
        {"if": {"filter_query": "{bias_score} >= 15 && {bias_score} < 40",
                "column_id": "bias_label"},
         "color": "#7ee0a8", "fontWeight": "600"},
        {"if": {"filter_query": "{bias_score} <= -40", "column_id": "bias_label"},
         "color": "#ff4757", "fontWeight": "700"},
        {"if": {"filter_query": "{bias_score} <= -15 && {bias_score} > -40",
                "column_id": "bias_label"},
         "color": "#ff8a93", "fontWeight": "600"},
        {"if": {"filter_query": "{bias_score} > -15 && {bias_score} < 15",
                "column_id": "bias_label"},
         "color": "#888"},

        {"if": {"filter_query": "{bias_score} >= 40", "column_id": "bias_score"},
         "backgroundColor": "rgba(0,212,126,0.20)", "color": "#00ff95",
         "fontWeight": "700"},
        {"if": {"filter_query": "{bias_score} >= 15 && {bias_score} < 40",
                "column_id": "bias_score"},
         "backgroundColor": "rgba(0,212,126,0.10)", "color": "#7ee0a8"},
        {"if": {"filter_query": "{bias_score} <= -40", "column_id": "bias_score"},
         "backgroundColor": "rgba(255,71,87,0.20)", "color": "#ff6b6b",
         "fontWeight": "700"},
        {"if": {"filter_query": "{bias_score} <= -15 && {bias_score} > -40",
                "column_id": "bias_score"},
         "backgroundColor": "rgba(255,71,87,0.10)", "color": "#ff8a93"},

        {"if": {"filter_query": "{chg_pct} > 0", "column_id": "chg_pct"},
         "color": "#00d47e"},
        {"if": {"filter_query": "{chg_pct} < 0", "column_id": "chg_pct"},
         "color": "#ff4757"},
        {"if": {"filter_query": "{range_pos} >= 80", "column_id": "range_pos"},
         "color": "#00d47e", "fontWeight": "600"},
        {"if": {"filter_query": "{range_pos} <= 20", "column_id": "range_pos"},
         "color": "#ff4757", "fontWeight": "600"},

        {"if": {"filter_query": "{call_agg} >= 65", "column_id": "call_agg"},
         "color": "#00d47e", "fontWeight": "600"},
        {"if": {"filter_query": "{put_agg} >= 65", "column_id": "put_agg"},
         "color": "#ff4757", "fontWeight": "600"},

        {"if": {"filter_query": "{cp_ratio} >= 1.5", "column_id": "cp_ratio"},
         "color": "#00d47e", "fontWeight": "600"},
        {"if": {"filter_query": "{cp_ratio} < 0.67", "column_id": "cp_ratio"},
         "color": "#ff4757", "fontWeight": "600"},

        {"if": {"filter_query": "{last_hour_delta} > 0",
                "column_id": "last_hour_delta"}, "color": "#00d47e"},
        {"if": {"filter_query": "{last_hour_delta} < 0",
                "column_id": "last_hour_delta"}, "color": "#ff4757"},

        {"if": {"filter_query": "{last_hour_rel} >= 1.5",
                "column_id": "last_hour_rel"}, "color": "#ffa502",
         "fontWeight": "600"},
    ]


def _overnight_flow_conditional() -> list[dict]:
    return [
        {"if": {"filter_query": "{vol_oi} >= 1.0", "column_id": "vol_oi"},
         "color": "#ffa502", "fontWeight": "700"},
        {"if": {"filter_query": "{vol_oi} >= 0.5 && {vol_oi} < 1.0",
                "column_id": "vol_oi"}, "color": "#ffd084"},
        {"if": {"filter_query": "{agg} >= 70", "column_id": "agg"},
         "color": "#00d47e", "fontWeight": "700"},
        {"if": {"filter_query": "{agg} >= 60 && {agg} < 70", "column_id": "agg"},
         "color": "#7ee0a8"},
        {"if": {"filter_query": "{agg} <= 30", "column_id": "agg"},
         "color": "#ff4757", "fontWeight": "700"},
        {"if": {"filter_query": "{agg} > 30 && {agg} <= 40", "column_id": "agg"},
         "color": "#ff8a93"},
        {"if": {"filter_query": "{moneyness} >= 0", "column_id": "moneyness"},
         "color": "#7ed0ff"},
        {"if": {"filter_query": "{moneyness} < 0", "column_id": "moneyness"},
         "color": "#d0a0ff"},
    ]


def _build_gex_tab():
    """Standalone GEX workspace, intentionally independent of Volume Scanner."""
    def _empty_graph(message: str, height: int):
        return go.Figure(layout={
            "template": "plotly_dark",
            "paper_bgcolor": "#1a1a2e",
            "plot_bgcolor": "#1a1a2e",
            "height": height,
            "margin": {"t": 36, "b": 45, "l": 55, "r": 20},
            "annotations": [{
                "text": message, "xref": "paper", "yref": "paper",
                "x": 0.5, "y": 0.5, "showarrow": False,
                "font": {"color": "#6e7a8a", "size": 12},
            }],
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
        })

    input_style = {
        "backgroundColor": "#1a1a2e",
        "border": "1px solid rgba(255,255,255,0.12)",
        "color": "#e0e0e0",
    }

    return html.Div([
        html.Div([
            html.H3("GEX Heatmap & Dealer Gamma",
                    style={"fontWeight": "800", "color": "#fff",
                           "letterSpacing": "0.7px", "marginBottom": "4px"}),
            html.P(
                "Independent options-chain gamma workspace with strike × expiry "
                "heatmap, call/put decomposition, scenario-based gamma flip and "
                "intraday replay.",
                style={"color": "#888", "fontSize": "0.82rem",
                       "marginBottom": "14px"}),
        ]),

        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Symbol", className="text-muted small mb-1"),
                        dbc.Input(id="gex-symbol", type="text", value="SPY",
                                  placeholder="SPY, QQQ, NVDA...",
                                  debounce=True,
                                  style={**input_style, "fontWeight": "700"}),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Mode", className="text-muted small mb-1"),
                        dbc.RadioItems(
                            id="gex-mode",
                            options=[
                                {"label": "Snapshot", "value": "snapshot"},
                                {"label": "Intraday Replay", "value": "replay"},
                            ],
                            value="snapshot", inline=True,
                            inputStyle={"marginRight": "4px"},
                            labelStyle={"fontSize": "0.78rem", "color": "#ccc",
                                        "marginRight": "12px"},
                        ),
                    ], md=3, sm=12),
                    dbc.Col([
                        dbc.Label("Replay Day", className="text-muted small mb-1"),
                        dcc.DatePickerSingle(id="gex-day",
                                             display_format="YYYY-MM-DD",
                                             placeholder="YYYY-MM-DD",
                                             style={"width": "100%"}),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Chart / Replay Bars",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="gex-timeframe", value="5m",
                            options=[
                                {"label": "1 minute", "value": "1m"},
                                {"label": "5 minutes", "value": "5m"},
                                {"label": "15 minutes", "value": "15m"},
                                {"label": "30 minutes", "value": "30m"},
                            ], style=input_style),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        dbc.Button("Build GEX", id="gex-build-btn",
                                   color="info", className="w-100",
                                   style={"fontWeight": "800"}),
                    ], md=3, sm=12),
                ], align="end", className="mb-2"),
                html.Hr(style={"borderColor": "rgba(255,255,255,0.06)",
                               "margin": "10px 0"}),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Expirations", className="text-muted small mb-1"),
                        dbc.Input(id="gex-max-exps", type="number", value=12,
                                  min=1, max=30, step=1),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Strike Window ± %",
                                  className="text-muted small mb-1"),
                        dbc.Input(id="gex-window-pct", type="number", value=20,
                                  min=2, max=60, step=1),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Strike Bin", className="text-muted small mb-1"),
                        dbc.Input(id="gex-strike-bin", type="number",
                                  placeholder="native", min=0, step=0.5),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Risk-free Rate %",
                                  className="text-muted small mb-1"),
                        dbc.Input(id="gex-risk-free", type="number", value=4.5,
                                  min=0, max=20, step=0.1),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Chart Range", className="text-muted small mb-1"),
                        dbc.Select(
                            id="gex-chart-period", value="1d",
                            options=[
                                {"label": "1 trading day", "value": "1d"},
                                {"label": "5 trading days", "value": "5d"},
                            ], style=input_style),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Chart Refresh",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="gex-refresh-interval", value="off",
                            options=[
                                {"label": "Off", "value": "off"},
                                {"label": "Every 30 seconds", "value": "30s"},
                                {"label": "Every 1 minute", "value": "1m"},
                                {"label": "Every 2 minutes", "value": "2m"},
                                {"label": "Every 5 minutes", "value": "5m"},
                            ], style=input_style),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Contract DTEs (empty = all)",
                                  className="text-muted small mb-1"),
                        dcc.Dropdown(
                            id="gex-dtes", value=[], multi=True,
                            options=(
                                [{"label": f"{d} DTE", "value": d}
                                 for d in range(0, 31)]
                                + [{"label": f"{d} DTE", "value": d}
                                   for d in (45, 60, 90, 120, 180, 365)]
                            ),
                            placeholder="All available DTEs",
                            className="dash-dropdown gex-dte-dropdown",
                            style={"fontSize": "0.82rem"},
                        ),
                    ], md=4, sm=12, className="mt-2"),
                    dbc.Col([
                        html.Div(id="gex-status",
                                 style={"fontSize": "0.76rem", "color": "#888",
                                        "paddingTop": "8px"}),
                    ], md=8, sm=12, className="mt-2"),
                ], align="end"),
            ], style={"padding": "14px 18px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        dcc.Interval(id="gex-auto-refresh", interval=30_000,
                     n_intervals=0, disabled=True),
        dcc.Store(id="gex-market-store", data={}),

        dbc.Row(id="gex-summary", className="mb-3 gx-3"),

        dcc.Loading(type="dot", color=CYAN, children=[
            dcc.Graph(id="gex-market-chart",
                      figure=_empty_graph(
                          "Build GEX to load candles, volume and gamma levels", 670),
                      config={"displaylogo": False, "scrollZoom": True,
                              "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
                      style={"height": "670px", "marginBottom": "14px",
                             "border": "1px solid rgba(78,205,196,0.14)",
                             "borderRadius": "8px", "overflow": "hidden"}),
            dcc.Graph(id="gex-timeseries",
                      figure=_empty_graph(
                          "Intraday replay displays net GEX and spot here", 280),
                      config={"displaylogo": False},
                      style={"height": "280px", "marginBottom": "10px"}),
            dcc.Graph(id="gex-history-cloud",
                      figure=_empty_graph(
                          "Choose Intraday Replay to build the modeled GEX wall cloud", 560),
                      config={"displaylogo": False, "scrollZoom": True,
                              "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
                      style={"height": "560px", "marginBottom": "12px",
                             "border": "1px solid rgba(78,205,196,0.12)",
                             "borderRadius": "8px", "overflow": "hidden"}),

            dbc.Row([
                dbc.Col([
                    dcc.Graph(id="gex-heatmap",
                              figure=_empty_graph(
                                  "Choose a symbol and click Build GEX", 560),
                              config={"displaylogo": False, "scrollZoom": True},
                              style={"height": "560px"}),
                ], md=8, sm=12),
                dbc.Col([
                    dcc.Graph(id="gex-profile",
                              figure=_empty_graph("Call / put / net GEX by strike", 560),
                              config={"displaylogo": False},
                              style={"height": "560px"}),
                ], md=4, sm=12),
            ], className="g-3"),

            dbc.Row([
                dbc.Col([
                    dcc.Graph(id="gex-scenario",
                              figure=_empty_graph(
                                  "Whole-chain GEX repriced across spot levels", 360),
                              config={"displaylogo": False},
                              style={"height": "360px"}),
                ], md=6, sm=12),
                dbc.Col([
                    dcc.Graph(id="gex-expiry-profile",
                              figure=_empty_graph("Net GEX by expiration", 360),
                              config={"displaylogo": False},
                              style={"height": "360px"}),
                ], md=6, sm=12),
            ], className="g-3 mt-1"),
        ]),

        dbc.Card([
            dbc.CardHeader(
                html.H5("Strike Detail",
                        className="mb-0",
                        style={"fontWeight": "700", "fontSize": "0.95rem"}),
                style={"backgroundColor": HEADER_DARK, "border": "none"}),
            dbc.CardBody([
                dash_table.DataTable(
                    id="gex-levels-table",
                    columns=[
                        {"name": "Strike", "id": "strike", "type": "numeric",
                         "format": Format(precision=2, scheme=Scheme.fixed)},
                        {"name": "Call GEX $M / 1%", "id": "call_gex"},
                        {"name": "Put GEX $M / 1%", "id": "put_gex"},
                        {"name": "Net GEX $M / 1%", "id": "net_gex"},
                        {"name": "Call OI", "id": "call_oi"},
                        {"name": "Put OI", "id": "put_oi"},
                    ],
                    data=[], sort_action="native", page_size=20,
                    style_table={"overflowX": "auto", "maxHeight": "460px",
                                 "overflowY": "auto"},
                    style_header=_shared_header_style,
                    style_cell={**_shared_cell_style, "fontSize": "0.78rem",
                                "padding": "7px 8px"},
                    style_data_conditional=[
                        {"if": {"filter_query": "{net_gex} > 0",
                                "column_id": "net_gex"},
                         "color": GREEN, "fontWeight": "700"},
                        {"if": {"filter_query": "{net_gex} < 0",
                                "column_id": "net_gex"},
                         "color": RED, "fontWeight": "700"},
                    ],
                    fixed_rows={"headers": True},
                ),
            ], style={"padding": "8px 12px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mt-3 mb-3"),

        html.Div(id="gex-walls", className="mb-2",
                 style={"fontSize": "0.8rem", "color": "#bbb"}),
        dbc.Alert([
            html.Strong("Comparison note: "),
            "Values use yfinance end-of-day open interest and displayed IV, "
            "Black–Scholes gamma, 100-share contracts, and the standard "
            "call-positive / put-negative convention. GEX is dollars of delta "
            "change for a 1% underlying move. Vendor totals can differ because "
            "of fresher/proprietary OI, IV cleaning, dividend/borrow models, "
            "dealer-sign estimates, contract filters, and index-vs-ETF coverage.",
        ], color="secondary",
           style={"backgroundColor": "rgba(78,205,196,0.07)",
                  "border": "1px solid rgba(78,205,196,0.18)",
                  "color": "#9ba8b7", "fontSize": "0.75rem"}),
    ])


def _build_gex_alpaca_tab():
    """Exact GEX workspace clone with IDs isolated for the Alpaca feed."""
    workspace = _build_gex_tab()
    for component in workspace._traverse():
        component_id = getattr(component, "id", None)
        if isinstance(component_id, str) and component_id.startswith("gex-"):
            component.id = f"gex-alpaca-{component_id[4:]}"
        children = getattr(component, "children", None)
        if children == "GEX Heatmap & Dealer Gamma":
            component.children = "GEX Alpaca — Dealer Gamma"
        elif isinstance(children, list):
            component.children = [
                child.replace(
                    "Values use yfinance end-of-day open interest and displayed IV",
                    "Values use Alpaca contract open interest and Alpaca-sourced or quote-derived IV",
                ) if isinstance(child, str) else child
                for child in children
            ]

    return html.Div([
        dbc.Alert([
            html.Strong("ALPACA COMPARISON FEED  "),
            "Option OI, quotes, IV inputs and underlying prices are sourced "
            "through your Alpaca API credentials. The calculation uses the "
            "same call-positive / put-negative GEX convention as the yfinance tab.",
        ], color="info", className="mb-3",
           style={"backgroundColor": "rgba(78,205,196,0.08)",
                  "border": "1px solid rgba(78,205,196,0.22)",
                  "color": "#b8d9d6", "fontSize": "0.78rem"}),
        workspace,
    ])


def _build_iv_walls_tab():
    """IV concentration workspace with selectable yfinance/Alpaca source."""
    def empty_figure(message: str, height: int = 430):
        figure = go.Figure()
        figure.add_annotation(
            text=message, x=.5, y=.5, xref="paper", yref="paper",
            showarrow=False, font={"color": "#6e7a8a", "size": 12})
        figure.update_layout(
            template="plotly_dark", paper_bgcolor=CELL_DARK,
            plot_bgcolor=CELL_DARK, height=height,
            margin={"t": 42, "b": 45, "l": 55, "r": 20},
            xaxis={"visible": False}, yaxis={"visible": False})
        return figure

    input_style = {
        "backgroundColor": CELL_DARK,
        "border": "1px solid rgba(255,255,255,0.12)",
        "color": "#e0e0e0",
    }
    dte_options = ([
        {"label": f"{value} DTE", "value": value}
        for value in range(0, 31)
    ] + [
        {"label": f"{value} DTE", "value": value}
        for value in (45, 60, 90, 120, 180, 365)
    ])
    return html.Div([
        html.Div([
            html.H3("IV Walls",
                    style={"fontWeight": "800", "color": "#fff",
                           "letterSpacing": ".7px", "marginBottom": "4px"}),
            html.P(
                "Find strikes with concentrated open-interest-weighted vega. "
                "Switch between yfinance and Alpaca to compare the same wall model.",
                style={"color": "#888", "fontSize": ".82rem",
                       "marginBottom": "14px"}),
        ]),
        dbc.Card(dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Symbol", className="text-muted small mb-1"),
                    dbc.Input(id="ivw-symbol", value="SPY", debounce=True,
                              style={**input_style, "fontWeight": "700"}),
                ], md=2, sm=6),
                dbc.Col([
                    dbc.Label("Data Source", className="text-muted small mb-1"),
                    dbc.Select(id="ivw-provider", value="yfinance",
                               options=[
                                   {"label": "yfinance", "value": "yfinance"},
                                   {"label": "Alpaca API", "value": "alpaca"},
                               ], style=input_style),
                ], md=2, sm=6),
                dbc.Col([
                    dbc.Label("Expirations", className="text-muted small mb-1"),
                    dbc.Input(id="ivw-max-exps", type="number", value=8,
                              min=1, max=20, step=1, style=input_style),
                ], md=2, sm=6),
                dbc.Col([
                    dbc.Label("Strike Window ± %", className="text-muted small mb-1"),
                    dbc.Input(id="ivw-window-pct", type="number", value=15,
                              min=2, max=60, step=1, style=input_style),
                ], md=2, sm=6),
                dbc.Col([
                    dbc.Label("Risk-free Rate %", className="text-muted small mb-1"),
                    dbc.Input(id="ivw-risk-free", type="number", value=4.5,
                              min=0, max=20, step=.1, style=input_style),
                ], md=2, sm=6),
                dbc.Col([
                    dbc.Label(" ", className="small mb-1"),
                    dbc.Button("Find IV Walls", id="ivw-build-btn", color="info",
                               className="w-100", style={"fontWeight": "800"}),
                ], md=2, sm=6),
            ], align="end"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Contract DTEs (empty = all)",
                              className="text-muted small mb-1"),
                    dcc.Dropdown(id="ivw-dtes", options=dte_options, value=[],
                                 multi=True, placeholder="All available DTEs",
                                 className="dash-dropdown gex-dte-dropdown"),
                ], md=5, sm=12),
                dbc.Col(html.Div(id="ivw-status",
                                 style={"fontSize": ".76rem", "color": "#888",
                                        "paddingTop": "24px"}), md=7, sm=12),
            ], className="mt-2", align="end"),
        ], style={"padding": "14px 18px"}),
        style={"backgroundColor": HEADER_DARK,
               "border": "1px solid rgba(255,255,255,.06)",
               "borderRadius": "8px"}, className="mb-3"),

        dbc.Row(id="ivw-summary", className="mb-3 gx-3"),
        dcc.Loading(type="dot", color=CYAN, children=[
            dcc.Graph(
                id="ivw-market-chart",
                figure=empty_figure(
                    "Build IV Walls to overlay the current walls on price", 650),
                config={"displaylogo": False, "scrollZoom": True,
                        "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
                style={"height": "650px", "marginBottom": "14px",
                       "border": "1px solid rgba(78,205,196,.14)",
                       "borderRadius": "8px", "overflow": "hidden"}),
        ]),
        dcc.Loading(type="dot", color=CYAN, children=[
            dbc.Row([
                dbc.Col(dcc.Graph(
                    id="ivw-profile", figure=empty_figure("Build IV Walls to see strike concentration", 520),
                    config={"displaylogo": False, "scrollZoom": True}), md=8, sm=12),
                dbc.Col(dcc.Graph(
                    id="ivw-skew", figure=empty_figure("Vega-weighted IV by strike", 520),
                    config={"displaylogo": False}), md=4, sm=12),
            ], className="g-3"),
            dbc.Row([
                dbc.Col(dcc.Graph(
                    id="ivw-heatmap", figure=empty_figure("Strike × expiration IV walls", 420),
                    config={"displaylogo": False}), md=7, sm=12),
                dbc.Col(dcc.Graph(
                    id="ivw-term", figure=empty_figure("IV term structure", 420),
                    config={"displaylogo": False}), md=5, sm=12),
            ], className="g-3 mt-1"),
        ]),
        dbc.Card([
            dbc.CardHeader(html.H5(
                "Ranked IV Walls", className="mb-0",
                style={"fontWeight": "700", "fontSize": ".95rem"}),
                style={"backgroundColor": HEADER_DARK, "border": "none"}),
            dbc.CardBody(dash_table.DataTable(
                id="ivw-table",
                columns=[
                    {"name": "Rank", "id": "rank"},
                    {"name": "Side", "id": "side"},
                    {"name": "Strike", "id": "strike"},
                    {"name": "Distance %", "id": "distance_pct"},
                    {"name": "Vega $ / 1 IV pt", "id": "vex"},
                    {"name": "Weighted IV %", "id": "iv_pct"},
                    {"name": "Open Interest", "id": "oi"},
                    {"name": "Expirations", "id": "expirations"},
                ], data=[], sort_action="native", page_size=16,
                style_table={"overflowX": "auto"},
                style_header=_shared_header_style,
                style_cell={**_shared_cell_style, "fontSize": ".78rem"},
                style_data_conditional=[
                    {"if": {"filter_query": '{side} = "CALL"'},
                     "color": GREEN},
                    {"if": {"filter_query": '{side} = "PUT"'},
                     "color": RED},
                ],
            ), style={"padding": "8px 12px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,.06)",
                  "borderRadius": "8px"}, className="mt-3 mb-3"),
        dbc.Alert([
            html.Strong("Model definition: "),
            "An IV wall is ranked by open-interest-weighted Black–Scholes vega: "
            "estimated contract value change for a one-percentage-point IV move. "
            "It is a concentration map—not a directly published exchange field, "
            "dealer position, guaranteed support/resistance level, or trade signal.",
        ], color="secondary",
           style={"backgroundColor": "rgba(78,205,196,.07)",
                  "border": "1px solid rgba(78,205,196,.18)",
                  "color": "#9ba8b7", "fontSize": ".75rem"}),
    ])


def _build_overnight_tab():
    return html.Div([
        # ── Header / intro ─────────────────────────────────────────────
        html.Div([
            html.H3("Overnight Positioning",
                    style={"fontWeight": "800", "color": "#fff",
                           "letterSpacing": "1px", "marginBottom": "4px"}),
            html.P(
                "Scan late-day options flow + EOD tape to spot positioning "
                "that historically leads to overnight gaps. OI is one session "
                "stale (yfinance limit) — today's signal is volume × bid-ask "
                "aggression × $ notional × day's-range location.",
                style={"color": "#888", "fontSize": "0.82rem",
                       "marginBottom": "14px"}),
        ]),

        # ── Setup card ─────────────────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Symbols (comma-separated)",
                                  className="text-muted small mb-1"),
                        dbc.Input(
                            id="on-symbols", type="text",
                            value="SPY, QQQ, NVDA, TSLA, AAPL, META",
                            placeholder="SPY, QQQ, NVDA, TSLA",
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0",
                                   "fontWeight": "600",
                                   "letterSpacing": "0.5px"}),
                    ], md=5, sm=12),
                    dbc.Col([
                        dbc.Label("Max DTE",
                                  className="text-muted small mb-1"),
                        dbc.Select(
                            id="on-dte-max", value="5",
                            options=[
                                {"label": "Today only (0DTE)", "value": "0"},
                                {"label": "≤ 1 day",  "value": "1"},
                                {"label": "≤ 2 days", "value": "2"},
                                {"label": "≤ 3 days", "value": "3"},
                                {"label": "≤ 5 days", "value": "5"},
                                {"label": "≤ 10 days", "value": "10"},
                            ],
                            style={"backgroundColor": "#1a1a2e",
                                   "border": "1px solid rgba(255,255,255,0.12)",
                                   "color": "#e0e0e0"},
                        ),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Min Vol/OI",
                                  className="text-muted small mb-1"),
                        dbc.Input(id="on-vol-oi-min", type="number",
                                  value=0.30, min=0, max=5, step=0.05),
                    ], md=1, sm=6),
                    dbc.Col([
                        dbc.Label("Min Agg %",
                                  className="text-muted small mb-1"),
                        dbc.Input(id="on-agg-min", type="number",
                                  value=60, min=0, max=100, step=5),
                    ], md=1, sm=6),
                    dbc.Col([
                        dbc.Label("Min $K",
                                  className="text-muted small mb-1"),
                        dbc.Input(id="on-min-notional-k", type="number",
                                  value=50, min=0, step=10),
                    ], md=1, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small mb-1"),
                        dbc.Button("Scan Overnight",
                                   id="on-scan-btn",
                                   color="warning",
                                   className="w-100",
                                   style={"fontWeight": "700"}),
                    ], md=2, sm=12),
                ], className="g-2 mb-2", align="end"),

                dbc.Row([
                    dbc.Col([
                        dbc.Checklist(
                            id="on-include-itm",
                            options=[{"label": "Include ITM rows", "value": "y"}],
                            value=[],
                            switch=True,
                            inputStyle={"marginRight": "6px"},
                            labelStyle={"fontSize": "0.78rem", "color": "#aaa"},
                        ),
                    ], md=3),
                    dbc.Col([
                        html.Small(
                            "Tip: run this in the final 30–60 min of the "
                            "session for the cleanest read. yfinance options "
                            "data is delayed ~15 min.",
                            style={"color": "#666", "fontSize": "0.72rem",
                                   "fontStyle": "italic"}),
                    ], md=9),
                ], className="g-2"),

                html.Div(id="on-status",
                         className="mt-2",
                         style={"fontSize": "0.78rem", "color": "#888"}),
            ], style={"padding": "14px 16px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Bias board ─────────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.H5("Overnight Bias Board",
                            className="mb-0 d-inline-block",
                            style={"fontWeight": "700",
                                   "fontSize": "0.95rem", "color": "#fff"}),
                    html.Small(
                        "  click a row to drill into the per-strike flow",
                        style={"marginLeft": "10px", "color": "#888",
                               "fontSize": "0.74rem"}),
                ]),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dcc.Loading(
                    id="on-board-loading", type="dot", color=CYAN,
                    children=dash_table.DataTable(
                        id="on-board-table",
                        columns=OVERNIGHT_BOARD_COLUMNS,
                        data=[],
                        sort_action="native",
                        sort_by=[{"column_id": "bias_score",
                                  "direction": "desc"}],
                        row_selectable="single",
                        selected_rows=[],
                        style_table={"overflowX": "auto",
                                     "maxHeight": "440px",
                                     "overflowY": "auto"},
                        style_header={**_shared_header_style,
                                      "fontSize": "0.74rem",
                                      "padding": "8px 6px"},
                        style_cell={**_shared_cell_style,
                                    "fontSize": "0.76rem",
                                    "padding": "6px 7px",
                                    "minWidth": "55px",
                                    "maxWidth": "120px"},
                        style_data_conditional=_overnight_board_conditional(),
                        style_as_list_view=True,
                        page_size=30,
                        fixed_rows={"headers": True},
                    ),
                ),
            ], style={"padding": "10px 14px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Detail panel — per-strike call + put flow ──────────────────
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.H5("Per-Strike Flow Detail",
                            className="mb-0 d-inline-block",
                            id="on-detail-title",
                            style={"fontWeight": "700",
                                   "fontSize": "0.95rem", "color": "#fff"}),
                    html.Small(
                        id="on-detail-sub",
                        children="select a symbol in the board to populate",
                        style={"marginLeft": "10px", "color": "#888",
                               "fontSize": "0.74rem"}),
                ]),
                style={"backgroundColor": HEADER_DARK, "border": "none"},
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div("CALL FLOW (bullish loaders)",
                                 style={"fontSize": "0.78rem",
                                        "fontWeight": "700",
                                        "color": "#00d47e",
                                        "marginBottom": "6px",
                                        "letterSpacing": "1px"}),
                        dash_table.DataTable(
                            id="on-detail-calls-table",
                            columns=OVERNIGHT_FLOW_COLUMNS,
                            data=[],
                            sort_action="native",
                            sort_by=[{"column_id": "notional_k",
                                      "direction": "desc"}],
                            style_table={"overflowX": "auto",
                                         "maxHeight": "380px",
                                         "overflowY": "auto"},
                            style_header={**_shared_header_style,
                                          "fontSize": "0.72rem",
                                          "padding": "6px 5px"},
                            style_cell={**_shared_cell_style,
                                        "fontSize": "0.74rem",
                                        "padding": "5px 5px"},
                            style_data_conditional=_overnight_flow_conditional(),
                            style_as_list_view=True,
                            page_size=15,
                            fixed_rows={"headers": True},
                        ),
                    ], md=6, sm=12),
                    dbc.Col([
                        html.Div("PUT FLOW (bearish loaders)",
                                 style={"fontSize": "0.78rem",
                                        "fontWeight": "700",
                                        "color": "#ff4757",
                                        "marginBottom": "6px",
                                        "letterSpacing": "1px"}),
                        dash_table.DataTable(
                            id="on-detail-puts-table",
                            columns=OVERNIGHT_FLOW_COLUMNS,
                            data=[],
                            sort_action="native",
                            sort_by=[{"column_id": "notional_k",
                                      "direction": "desc"}],
                            style_table={"overflowX": "auto",
                                         "maxHeight": "380px",
                                         "overflowY": "auto"},
                            style_header={**_shared_header_style,
                                          "fontSize": "0.72rem",
                                          "padding": "6px 5px"},
                            style_cell={**_shared_cell_style,
                                        "fontSize": "0.74rem",
                                        "padding": "5px 5px"},
                            style_data_conditional=_overnight_flow_conditional(),
                            style_as_list_view=True,
                            page_size=15,
                            fixed_rows={"headers": True},
                        ),
                    ], md=6, sm=12),
                ], className="g-3"),

                html.Div(id="on-detail-notes", className="mt-3",
                         style={"fontSize": "0.78rem", "color": "#bbb"}),
            ], style={"padding": "12px 14px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # ── Legend / cheat-sheet ───────────────────────────────────────
        dbc.Card([
            dbc.CardBody([
                html.Div("How to read this", style={"fontWeight": "700",
                                                     "color": "#ddd",
                                                     "fontSize": "0.85rem",
                                                     "marginBottom": "8px"}),
                html.Ul([
                    html.Li([
                        html.B("Bias score "),
                        "= (call_score − put_score) / (call_score + put_score) "
                        "× 100, where each side's score sums notional × "
                        "aggression for rows that pass the Vol/OI + Agg "
                        "filter. EOD range-location adds ±10."
                    ], style={"color": "#bbb", "fontSize": "0.78rem"}),
                    html.Li([
                        html.B("Vol/OI "),
                        "above 1.0 = today's volume exceeded yesterday's "
                        "settlement OI → fresh positioning. On just-listed "
                        "expirations the ratio can be very large because OI "
                        "starts near zero — corroborate with $ notional."
                    ], style={"color": "#bbb", "fontSize": "0.78rem"}),
                    html.Li([
                        html.B("Aggression % "),
                        "= where the last print landed in the bid-ask spread "
                        "(0 = sold to bid / bearish; 100 = bought at ask / "
                        "bullish). Vol-weighted by side on the board."
                    ], style={"color": "#bbb", "fontSize": "0.78rem"}),
                    html.Li([
                        html.B("Range % "),
                        "= where spot finished within the day's high-low. "
                        "Close-on-highs + bullish flow = high-conviction gap-up "
                        "setup. Close-on-lows + bearish flow = gap-down."
                    ], style={"color": "#bbb", "fontSize": "0.78rem"}),
                    html.Li([
                        html.B("LH Δ $ / LH RelVol "),
                        "= last-hour buy-minus-sell dollar delta, and "
                        "last-hour volume vs the prior-days same-time-of-day "
                        "baseline. Late-session momentum often carries "
                        "overnight."
                    ], style={"color": "#bbb", "fontSize": "0.78rem"}),
                ], style={"marginBottom": "0", "paddingLeft": "18px"}),
            ], style={"padding": "12px 16px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        # Hidden store for per-symbol full detail
        dcc.Store(id="on-detail-store", data={}),
    ])


def _build_options_screener_tab():
    return html.Div([
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Ticker", className="text-muted small mb-1"),
                        dbc.Input(id="opt-scr-ticker", type="text", value="META",
                                  maxLength=10),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Expirations (comma-separated)", className="text-muted small mb-1"),
                        dbc.Input(id="opt-scr-expirations", type="text",
                                  value="2026-05-08,2026-05-11,2026-05-13,2026-05-15,2026-05-18"),
                    ], md=7, sm=12),
                    dbc.Col([
                        dbc.Label("Top N", className="text-muted small mb-1"),
                        dbc.Input(id="opt-scr-top-n", type="number", value=10,
                                  min=1, max=100, step=1),
                    ], md=1, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="text-muted small mb-1"),
                        dbc.Button("Run Options Volume", id="opt-scr-run-btn",
                                   color="info", className="w-100"),
                    ], md=2, sm=6),
                ], className="gx-2 gy-2"),
                html.Div(id="opt-scr-status", className="mt-3",
                         style={"fontSize": "0.82rem", "color": "#aaa"}),
            ], style={"padding": "12px 14px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Per-Expiration Vol/OI",
                                   style={"fontSize": "0.8rem",
                                          "fontWeight": "700",
                                          "color": "#ddd",
                                          "backgroundColor": "#0e0e20",
                                          "borderBottom": "1px solid rgba(255,255,255,0.06)"}),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id="opt-scr-summary-table",
                            columns=OPT_SCR_SUMMARY_COLUMNS,
                            data=[],
                            style_table={"overflowX": "auto", "borderRadius": "6px"},
                            style_header=_shared_header_style,
                            style_cell=_shared_cell_style,
                            style_data_conditional=_vol_hist_conditional_styles(),
                            page_size=8,
                            cell_selectable=True,
                        ),
                    ], style={"padding": "10px 12px"}),
                ], style={"backgroundColor": CELL_DARK,
                          "border": "1px solid rgba(255,255,255,0.06)",
                          "borderRadius": "8px"}),
            ], md=6, sm=12),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Most Active Calls (Selected Expiry)",
                                   style={"fontSize": "0.8rem",
                                          "fontWeight": "700",
                                          "color": "#ddd",
                                          "backgroundColor": "#0e0e20",
                                          "borderBottom": "1px solid rgba(255,255,255,0.06)"}),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id="opt-scr-top-table",
                            columns=OPT_SCR_TOP_COLUMNS,
                            data=[],
                            style_table={"overflowX": "auto", "borderRadius": "6px"},
                            style_header=_shared_header_style,
                            style_cell=_shared_cell_style,
                            page_size=10,
                            cell_selectable=True,
                        ),
                        html.Div(id="opt-scr-itm-otm", className="mt-2",
                                 style={"fontSize": "0.8rem", "color": "#bbb"}),
                    ], style={"padding": "10px 12px"}),
                ], style={"backgroundColor": CELL_DARK,
                          "border": "1px solid rgba(255,255,255,0.06)",
                          "borderRadius": "8px"}),
            ], md=6, sm=12),
        ], className="g-3 mb-3"),

        dbc.Card([
            dbc.CardBody([
                html.Div("Big Money Moves",
                         style={"fontWeight": "700", "fontSize": "0.92rem",
                                "color": "#ddd", "marginBottom": "10px"}),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Underlying", className="text-muted small mb-1"),
                        dbc.Input(id="opt-bm-ticker", type="text", value="META",
                                  maxLength=10),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("Min Premium ($)", className="text-muted small mb-1"),
                        dbc.Input(id="opt-bm-min-premium", type="number",
                                  value=100000, min=1000, step=1000),
                    ], md=3, sm=6),
                    dbc.Col([
                        dbc.Label("Top Contracts", className="text-muted small mb-1"),
                        dbc.Input(id="opt-bm-limit", type="number",
                                  value=30, min=5, max=100, step=1),
                    ], md=2, sm=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="text-muted small mb-1"),
                        dbc.Button("Scan Big Money", id="opt-bm-run-btn",
                                   color="warning", className="w-100"),
                    ], md=2, sm=6),
                ], className="gx-2 gy-2"),
                html.Div(id="opt-bm-status", className="mt-3",
                         style={"fontSize": "0.82rem", "color": "#aaa"}),
            ], style={"padding": "12px 14px"}),
        ], style={"backgroundColor": HEADER_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}, className="mb-3"),

        dbc.Card([
            dbc.CardBody([
                dash_table.DataTable(
                    id="opt-bm-table",
                    columns=OPT_BIG_MONEY_COLUMNS,
                    data=[],
                    style_table={"overflowX": "auto", "borderRadius": "6px",
                                 "maxHeight": "420px", "overflowY": "auto"},
                    style_header=_shared_header_style,
                    style_cell=_shared_cell_style,
                    style_data_conditional=_vol_hist_conditional_styles(),
                    page_size=20,
                    cell_selectable=True,
                ),
            ], style={"padding": "10px 12px"}),
        ], style={"backgroundColor": CELL_DARK,
                  "border": "1px solid rgba(255,255,255,0.06)",
                  "borderRadius": "8px"}),
    ])


# =========================================================================
# Root layout
# =========================================================================

def build_layout(saved_tickers: list[str] | None = None,
                  saved_indicators: list[str] | None = None):
    global _initial_tickers, _initial_indicators
    _initial_tickers = saved_tickers or []
    _initial_indicators = saved_indicators or []

    sidebar = html.Div([
        # Brand
        html.Div([
            html.H4("STOCK SCOUT",
                     style={"fontWeight": "800", "letterSpacing": "2px",
                            "margin": 0, "color": "#fff",
                            "fontFamily": "'Segoe UI', sans-serif",
                            "fontSize": "1.05rem"}),
            html.Small("Quantitative Screener",
                       style={"opacity": 0.45, "letterSpacing": "1px",
                              "fontSize": "0.65rem"}),
        ], style={"padding": "20px 18px 16px",
                  "borderBottom": "1px solid rgba(255,255,255,0.06)"}),

        # Vertical nav
        html.Div([
            html.Button("Sector ETFs",     id="nav-tab-sectors",  n_clicks=0,
                        className="sidebar-link active"),
            html.Button("Screened Stocks",  id="nav-tab-screener", n_clicks=0,
                        className="sidebar-link"),
            html.Button("Volume Scanner",   id="nav-tab-volume",   n_clicks=0,
                        className="sidebar-link"),
            html.Button("GEX Heatmap",      id="nav-tab-gex",      n_clicks=0,
                        className="sidebar-link"),
            html.Button("GEX Alpaca",       id="nav-tab-gex-alpaca", n_clicks=0,
                        className="sidebar-link"),
            html.Button("IV Walls",         id="nav-tab-iv-walls", n_clicks=0,
                        className="sidebar-link"),
            html.Button("VOLUME AI",        id="nav-tab-volume-ai", n_clicks=0,
                        className="sidebar-link"),
            html.Button("Overnight",        id="nav-tab-overnight", n_clicks=0,
                        className="sidebar-link"),
            html.Button("Options Screener", id="nav-tab-options-screener", n_clicks=0,
                        className="sidebar-link"),
            html.Button("TradingView",      id="nav-tab-tradingview", n_clicks=0,
                        className="sidebar-link"),
            html.Button("Trade",            id="nav-tab-trade",    n_clicks=0,
                        className="sidebar-link"),
            html.Button("Alerts",           id="nav-tab-alerts",   n_clicks=0,
                        className="sidebar-link"),
            html.Button("AI Chat",          id="nav-tab-ai",       n_clicks=0,
                        className="sidebar-link"),
        ], className="sidebar-pills"),

        # Refresh area at bottom
        html.Div([
            html.Span(id="last-updated-text",
                      style={"opacity": 0.4, "fontSize": "0.68rem",
                             "display": "block", "marginBottom": "6px"}),
            dbc.Button("Refresh", id="refresh-btn", size="sm",
                       color="info", outline=True, className="w-100",
                       style={"fontSize": "0.75rem"}),
        ], style={"padding": "12px 18px", "marginTop": "auto",
                  "borderTop": "1px solid rgba(255,255,255,0.06)"}),
    ], className="sidebar-nav")

    content = html.Div([
        html.Div(_build_sector_tab(),      id="page-tab-sectors",     className="tab-page",
                 style={"display": "block"}),
        html.Div(_build_screener_tab(),     id="page-tab-screener",    className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_volume_tab(),       id="page-tab-volume",      className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_gex_tab(),          id="page-tab-gex",         className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_gex_alpaca_tab(),   id="page-tab-gex-alpaca",  className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_iv_walls_tab(),     id="page-tab-iv-walls",    className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_volume_ai_tab(),    id="page-tab-volume-ai",   className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_overnight_tab(),    id="page-tab-overnight",   className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_options_screener_tab(), id="page-tab-options-screener", className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_tradingview_tab(),  id="page-tab-tradingview", className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_trade_tab(),        id="page-tab-trade",       className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_alerts_tab(),       id="page-tab-alerts",      className="tab-page",
                 style={"display": "none"}),
        html.Div(_build_ai_tab(),           id="page-tab-ai",          className="tab-page",
                 style={"display": "none"}),
    ], className="main-content", style={"flex": "1", "padding": "20px 24px",
                                        "overflowY": "auto"})

    return html.Div([
        sidebar,
        content,

        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Activate Alpaca features"),
                            close_button=False),
            dbc.ModalBody([
                html.P(
                    "This section uses Alpaca. Enter a paper or live key pair "
                    "to activate it. All yfinance and public-data sections work "
                    "without Alpaca.",
                    style={"color": "#aeb8c2", "fontSize": ".86rem"}),
                dbc.Label("Account environment", className="text-muted small"),
                dbc.Select(
                    id="alpaca-key-environment", value="paper",
                    options=[
                        {"label": "Paper (recommended)", "value": "paper"},
                        {"label": "Live", "value": "live"},
                    ], className="mb-3"),
                dbc.Label("Alpaca API key", className="text-muted small"),
                dbc.Input(id="alpaca-key-id", type="text", autocomplete="off",
                          placeholder="Enter your Alpaca key ID",
                          className="mb-3"),
                dbc.Label("Alpaca secret key", className="text-muted small"),
                dbc.Input(id="alpaca-secret-key", type="password",
                          autocomplete="new-password",
                          placeholder="Enter your Alpaca secret key",
                          className="mb-2"),
                html.Div(
                    "Saved only to this computer's ignored .env file. "
                    "Credentials are never placed in the browser store.",
                    style={"fontSize": ".72rem", "color": "#71808d",
                           "marginBottom": "10px"}),
                html.Div(id="alpaca-key-status",
                         style={"fontSize": ".78rem", "color": "#ffbd69"}),
            ]),
            dbc.ModalFooter([
                dbc.Button("Continue without Alpaca", id="alpaca-key-cancel",
                           color="secondary", outline=True),
                dbc.Button("Validate & Activate", id="alpaca-key-save",
                           color="info", style={"fontWeight": "700"}),
            ]),
        ], id="alpaca-key-modal", is_open=False, centered=True,
           backdrop="static", keyboard=False),

        # Hidden store that callbacks write to for navigation
        dcc.Store(id="main-tabs", data="tab-sectors"),
        dcc.Store(id="alpaca-credentials-ready", data={}),

        dcc.Interval(id="refresh-interval", interval=CACHE_TTL_MINUTES * 60 * 1000,
                     n_intervals=0),
    ], style={"display": "flex", "minHeight": "100vh",
              "backgroundColor": "#0a0a1a"})
