"""Layout for the focused three-product market MVP."""

from __future__ import annotations

from dash import dash_table, dcc, html
import dash_bootstrap_components as dbc

from market_mvp.charts import empty_figure
from market_mvp.config import APP_NAME, APP_TAGLINE, DEFAULT_UNIVERSE


def _page_title(kicker: str, title: str, description: str, badge: str | None = None):
    return html.Div([
        html.Div([
            html.Span(kicker, className="eyebrow"),
            html.Span(badge, className="access-badge") if badge else None,
        ], className="page-kicker-row"),
        html.H1(title),
        html.P(description, className="page-description"),
    ], className="page-heading")


def _control(label: str, component, width: str = "control"):
    return html.Div([html.Label(label), component], className=width)


def _gex_page():
    dte_options = ([
        {"label": "0 DTE", "value": 0},
        {"label": "1 DTE", "value": 1},
        {"label": "2 DTE", "value": 2},
        {"label": "3 DTE", "value": 3},
        {"label": "5 DTE", "value": 5},
        {"label": "7 DTE", "value": 7},
        {"label": "14 DTE", "value": 14},
        {"label": "21 DTE", "value": 21},
        {"label": "30 DTE", "value": 30},
        {"label": "45 DTE", "value": 45},
        {"label": "60 DTE", "value": 60},
        {"label": "90 DTE", "value": 90},
    ])
    return html.Section([
        _page_title(
            "DEALER POSITIONING", "Gamma Exposure",
            "Estimated option positioning mapped directly against price. Find the levels where gamma may pin, accelerate or reject price.",
            "FREE",
        ),
        html.Div([
            _control("Symbol", dbc.Input(id="mvp-gex-symbol", value="SPY",
                                          debounce=True, className="dark-input")),
            _control("Contract DTE", dcc.Dropdown(
                id="mvp-gex-dtes", options=dte_options, value=[0], multi=True,
                placeholder="All available DTEs", className="dark-dropdown")),
            _control("Expirations", dbc.Input(id="mvp-gex-expirations", type="number",
                                               min=1, max=20, step=1, value=12,
                                               className="dark-input")),
            _control("Strike window", dcc.Dropdown(
                id="mvp-gex-window",
                options=[{"label": f"±{n}%", "value": n} for n in (5, 10, 15, 20, 30)],
                value=15, clearable=False, className="dark-dropdown")),
            _control("Auto refresh", dcc.Dropdown(
                id="mvp-gex-refresh",
                options=[
                    {"label": "Off", "value": "off"},
                    {"label": "30 seconds", "value": "30s"},
                    {"label": "1 minute", "value": "1m"},
                    {"label": "2 minutes", "value": "2m"},
                    {"label": "5 minutes", "value": "5m"},
                ], value="off", clearable=False, className="dark-dropdown")),
            html.Button("Build GEX", id="mvp-gex-build", n_clicks=0,
                        className="primary-button"),
        ], className="control-bar"),
        dcc.Interval(id="mvp-gex-timer", interval=30_000, disabled=True,
                     n_intervals=0),
        html.Div(id="mvp-gex-status", className="status-line"),
        html.Div(id="mvp-gex-metrics", className="metric-grid"),
        html.Div([
            dcc.Loading(dcc.Graph(
                id="mvp-gex-market", figure=empty_figure("Choose a symbol and build GEX", 610),
                config={"displaylogo": False, "scrollZoom": True})),
        ], className="chart-panel chart-panel-hero"),
        html.Div([
            html.Div(dcc.Graph(id="mvp-gex-heatmap",
                               figure=empty_figure("Expiration heatmap", 440),
                               config={"displaylogo": False}), className="chart-panel"),
            html.Div(dcc.Graph(id="mvp-gex-profile",
                               figure=empty_figure("Strike profile", 440),
                               config={"displaylogo": False}), className="chart-panel"),
        ], className="two-column"),
        html.Div([
            html.Div([
                html.Span("METHOD"),
                html.Strong("Estimated GEX"),
                html.P("Call-positive / put-negative dealer-positioning convention. Values show estimated delta change for a 1% underlying move."),
            ], className="method-card"),
            html.Div([
                html.Span("IMPORTANT"),
                html.Strong("Not observed inventory"),
                html.P("Open interest and implied volatility can be delayed. Levels are model outputs—not guaranteed support or resistance."),
            ], className="method-card warning"),
        ], className="two-column method-grid"),
    ], id="mvp-page-gex", className="product-page")


VOLUME_COLUMNS = [
    {"name": "SYMBOL", "id": "symbol"},
    {"name": "PRICE", "id": "price", "type": "numeric"},
    {"name": "CHG %", "id": "chg", "type": "numeric"},
    {"name": "RVOL", "id": "rel_vol", "type": "numeric"},
    {"name": "TODAY VOL", "id": "today_vol", "type": "numeric"},
    {"name": "TYPICAL NOW", "id": "typical_vol", "type": "numeric"},
    {"name": "VWAP", "id": "vwap", "type": "numeric"},
    {"name": "BUY % EST.", "id": "buy_share", "type": "numeric"},
    {"name": "DIRECTIONAL $ EST.", "id": "net_delta", "type": "numeric"},
    {"name": "SIGNAL", "id": "signal"},
    {"name": "AS OF", "id": "as_of"},
]


def _screener_page():
    return html.Section([
        _page_title(
            "MARKET DISCOVERY", "Volume Screener",
            "Scan a focused universe for time-adjusted relative volume and estimated buying or selling pressure.",
            "BETA",
        ),
        html.Div([
            _control("Symbols", dbc.Textarea(
                id="mvp-volume-symbols", value=", ".join(DEFAULT_UNIVERSE),
                rows=2, className="dark-input symbol-area"), "control control-wide"),
            html.Button("Run scan", id="mvp-volume-scan", n_clicks=0,
                        className="primary-button"),
        ], className="control-bar"),
        html.Div(id="mvp-volume-status", className="status-line"),
        html.Div(id="mvp-volume-metrics", className="metric-grid"),
        html.Div([
            dash_table.DataTable(
                id="mvp-volume-table", columns=VOLUME_COLUMNS, data=[],
                sort_action="native", filter_action="native", page_size=25,
                style_table={"overflowX": "auto"},
                style_header={"backgroundColor": "#0a0f14", "color": "#72838f",
                              "fontWeight": "700", "border": "none",
                              "fontSize": "11px", "letterSpacing": ".05em"},
                style_cell={"backgroundColor": "#0d1218", "color": "#dce7eb",
                            "border": "1px solid #17212a", "padding": "12px 10px",
                            "fontFamily": "Inter, sans-serif", "fontSize": "12px",
                            "textAlign": "right", "minWidth": "92px"},
                style_cell_conditional=[
                    {"if": {"column_id": "symbol"}, "textAlign": "left", "fontWeight": "800"},
                    {"if": {"column_id": "signal"}, "textAlign": "left"},
                    {"if": {"column_id": "as_of"}, "textAlign": "left"},
                ],
                style_data_conditional=[
                    {"if": {"filter_query": "{chg} > 0", "column_id": "chg"}, "color": "#31d08b"},
                    {"if": {"filter_query": "{chg} < 0", "column_id": "chg"}, "color": "#ff5573"},
                    {"if": {"filter_query": "{rel_vol} >= 1.5", "column_id": "rel_vol"},
                     "color": "#f4bd4b", "fontWeight": "800"},
                    {"if": {"filter_query": "{net_delta} > 0", "column_id": "net_delta"}, "color": "#31d08b"},
                    {"if": {"filter_query": "{net_delta} < 0", "column_id": "net_delta"}, "color": "#ff5573"},
                    {"if": {"state": "active"}, "backgroundColor": "#14212a", "border": "1px solid #37d8d2"},
                ],
            ),
        ], className="table-panel"),
        html.P("Select a row to send that symbol to Volume Detail.", className="table-hint"),
    ], id="mvp-page-screener", className="product-page page-hidden")


SPIKE_COLUMNS = [
    {"name": "TIME", "id": "ts"},
    {"name": "PRICE", "id": "price"},
    {"name": "VOL Z", "id": "vol_z"},
    {"name": "RVOL", "id": "rel_vol"},
    {"name": "BUY % EST.", "id": "buy_share"},
    {"name": "DIRECTIONAL $ EST.", "id": "delta"},
    {"name": "SIGNAL", "id": "signal"},
]


def _detail_page():
    return html.Section([
        _page_title(
            "SETUP VALIDATION", "Volume Detail",
            "Inspect price, VWAP, participation, volume distribution and estimated directional pressure for one symbol.",
            "BETA",
        ),
        html.Div([
            _control("Symbol", dbc.Input(id="mvp-detail-symbol", value="SPY",
                                          debounce=True, className="dark-input")),
            _control("Timeframe", dcc.Dropdown(
                id="mvp-detail-timeframe",
                options=[{"label": value, "value": value}
                         for value in ("1m", "5m", "15m", "30m", "1h")],
                value="5m", clearable=False, className="dark-dropdown")),
            _control("Sessions", dcc.Dropdown(
                id="mvp-detail-days",
                options=[{"label": "1 session", "value": 1},
                         {"label": "2 sessions", "value": 2},
                         {"label": "5 sessions", "value": 5}],
                value=2, clearable=False, className="dark-dropdown")),
            html.Button("Load analysis", id="mvp-detail-load", n_clicks=0,
                        className="primary-button"),
        ], className="control-bar"),
        html.Div(id="mvp-detail-status", className="status-line"),
        html.Div(id="mvp-detail-metrics", className="metric-grid"),
        html.Div([
            html.Div(dcc.Loading(dcc.Graph(
                id="mvp-detail-chart", figure=empty_figure("Load a symbol to begin", 590),
                config={"displaylogo": False, "scrollZoom": True})), className="chart-panel detail-main"),
            html.Div(dcc.Loading(dcc.Graph(
                id="mvp-detail-profile", figure=empty_figure("Volume profile", 590),
                config={"displaylogo": False})), className="chart-panel detail-profile"),
        ], className="detail-grid"),
        html.Div([
            html.Div([html.Span("DETECTED EVENTS", className="panel-kicker"),
                      html.H3("Volume spikes")], className="panel-title"),
            dash_table.DataTable(
                id="mvp-spike-table", columns=SPIKE_COLUMNS, data=[], page_size=12,
                sort_action="native",
                style_table={"overflowX": "auto"},
                style_header={"backgroundColor": "#0a0f14", "color": "#72838f",
                              "fontWeight": "700", "border": "none", "fontSize": "11px"},
                style_cell={"backgroundColor": "#0d1218", "color": "#dce7eb",
                            "border": "1px solid #17212a", "padding": "10px",
                            "fontFamily": "Inter, sans-serif", "fontSize": "12px"},
            ),
        ], className="table-panel"),
        html.P("Buying/selling pressure is estimated from minute-bar direction and is not exchange-classified order flow.",
               className="disclaimer"),
    ], id="mvp-page-detail", className="product-page page-hidden")


def build_layout():
    return html.Div([
        dcc.Store(id="mvp-active-page", data="gex", storage_type="session"),
        html.Aside([
            html.Div([
                html.Div("FS", className="brand-mark"),
                html.Div([html.Strong(APP_NAME), html.Span("MARKET INTELLIGENCE")]),
            ], className="brand"),
            html.Nav([
                html.Button([html.Span("γ", className="nav-icon"), html.Span("GEX")],
                            id="mvp-nav-gex", n_clicks=0, className="nav-item active"),
                html.Button([html.Span("⌁", className="nav-icon"), html.Span("Volume Screener")],
                            id="mvp-nav-screener", n_clicks=0, className="nav-item"),
                html.Button([html.Span("▥", className="nav-icon"), html.Span("Volume Detail")],
                            id="mvp-nav-detail", n_clicks=0, className="nav-item"),
            ], className="side-nav"),
            html.Div([
                html.Div([html.Span(className="live-dot"), " MARKET DATA"]),
                html.P("Prototype feed · verify before trading"),
            ], className="feed-status"),
        ], className="sidebar"),
        html.Main([
            html.Header([
                html.Div([html.Span("MVP"), APP_TAGLINE], className="topbar-tagline"),
                html.Div([html.Span("PUBLIC BETA", className="beta-pill")]),
            ], className="topbar"),
            html.Div([_gex_page(), _screener_page(), _detail_page()],
                     className="page-container"),
        ], className="app-main"),
    ], className="mvp-shell")
