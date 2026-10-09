from dash import Input, Output, State, callback_context, no_update, html, dcc, ALL
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import json
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from app.data import (
    fetch_etf_data, get_last_fetch_time,
    load_screened_stocks, fetch_watchlist_stocks,
    save_screened_stocks, remove_all_screened, load_saved_tickers,
    save_indicator_prefs,
)
from engine.volume_scanner import (
    scan_symbols as _scan_volume,
    scan_spikes as _scan_spikes,
    get_intraday_timeline as _get_timeline,
    summarize_window as _summarize_window,
    fetch_news as _fetch_news,
    get_volume_history as _get_history,
)
from engine.gex import (
    compute_gex as _compute_gex,
    compute_intraday_gex as _compute_intraday_gex,
)
from engine.gex_alpaca import (
    compute_gex_alpaca as _compute_gex_alpaca,
    fetch_alpaca_bars as _fetch_alpaca_bars,
)
from engine.iv_walls import compute_iv_walls as _compute_iv_walls
from engine.overnight import (
    scan_overnight as _scan_overnight,
    board_row as _on_board_row,
    flow_rows as _on_flow_rows,
)
from config import SECTOR_ETFS, MAG7_SYMBOLS, MASSIVE_API_KEY
from credential_store import (
    alpaca_credentials_configured,
    validate_and_store_alpaca_credentials,
)

_green = "#00d47e"
_red = "#ff4757"
_cyan = "#4ecdc4"
_orange = "#ffa502"
_card_bg = "#16213e"
_massive_api_key = MASSIVE_API_KEY


def _tv_interval_from_history(tf: str | None) -> str:
    mapping = {
        "1m": "1",
        "5m": "5",
        "10m": "10",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "2h": "120",
        "4h": "240",
        "1d": "D",
    }
    return mapping.get((tf or "1d").strip().lower(), "D")


def _yf_interval_from_history(tf: str | None) -> str:
    mapping = {
        "1m": "1m",
        "5m": "5m",
        "10m": "15m",
        "15m": "15m",
        "30m": "30m",
        "1h": "60m",
        "2h": "60m",
        "4h": "1h",
        "1d": "1d",
    }
    return mapping.get((tf or "5m").strip().lower(), "5m")


# =========================================================================
# TradingView embed builder
# =========================================================================

def _tradingview_url(symbol: str, interval: str = "D") -> str:
    """Build a TradingView Advanced Chart embed URL."""
    from urllib.parse import urlencode
    params = urlencode({
        "frameElementId": "tradingview_embed",
        "symbol": symbol,
        "interval": interval,
        "hidesidetoolbar": "0",
        "symboledit": "1",
        "saveimage": "0",
        "toolbarbg": "1a1a2e",
        "theme": "dark",
        "style": "1",
        "timezone": "America/New_York",
        "withdateranges": "1",
        "showpopupbutton": "1",
        "studies": "[]",
        "locale": "en",
    })
    return f"https://s.tradingview.com/widgetembed/?{params}"


# =========================================================================
# TradingView full-chart widget builder
# =========================================================================

def _indicator_dicts_to_studies(ind_list: list[dict]) -> list:
    """Convert our internal indicator dicts into the TradingView widget
    ``studies`` array (objects with ``id`` and optional ``inputs``)."""
    out = []
    for item in (ind_list or []):
        entry: dict = {"id": item["study_id"]}
        inputs = item.get("inputs")
        if inputs:
            entry["inputs"] = inputs
        out.append(entry)
    return out


def _build_tv_widget_html(ind_list: list[dict] | None = None) -> str:
    """Return an HTML document that embeds the TradingView Advanced Chart
    widget with the given indicator configs pre-loaded."""
    studies = _indicator_dicts_to_studies(ind_list)
    config = json.dumps({
        "autosize": True,
        "symbol": "SPY",
        "interval": "D",
        "timezone": "America/New_York",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "allow_symbol_change": True,
        "withdateranges": True,
        "hide_side_toolbar": False,
        "details": True,
        "hotlist": True,
        "calendar": False,
        "studies": studies,
        "show_popup_button": True,
        "popup_width": "1000",
        "popup_height": "650",
        "support_host": "https://www.tradingview.com",
    }, indent=2)
    return f"""<!DOCTYPE html><html style="height:100%"><head>
<style>html,body{{margin:0;padding:0;height:100%;overflow:hidden;background:#0a0a1a}}
.tradingview-widget-container{{height:100%}}
.tradingview-widget-container__widget{{height:100%}}</style>
</head><body>
<div class="tradingview-widget-container">
  <div class="tradingview-widget-container__widget"></div>
  <script type="text/javascript"
    src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
  {config}
  </script>
</div>
</body></html>"""


def _render_pills(ind_list: list[dict]) -> list:
    """Build removable pill badges from the indicator list."""
    if not ind_list:
        return [html.Span("None — add indicators above",
                          style={"color": "#666", "fontSize": "0.8rem"})]
    pills = []
    for item in ind_list:
        key = item["key"]
        label = item["label"]
        pills.append(
            html.Span([
                html.Span(label, style={"marginRight": "6px"}),
                html.Span("\u00d7", id={"type": "tv-rm-ind", "index": key},
                          n_clicks=0,
                          style={"cursor": "pointer", "fontWeight": "700",
                                 "opacity": "0.7"}),
            ], className="tv-pill")
        )
    return pills


# =========================================================================
# Shared helpers
# =========================================================================

def _card(title, main, sub, sub_color):
    return dbc.Col(dbc.Card([
        dbc.CardBody([
            html.P(title, className="text-muted mb-1",
                   style={"fontSize": "0.75rem", "letterSpacing": "0.5px"}),
            html.H4(main, className="mb-0",
                     style={"fontWeight": "700", "fontFamily": "Consolas, monospace"}),
            html.Span(sub, style={"color": sub_color, "fontSize": "0.85rem",
                                  "fontWeight": "600"}),
        ], style={"padding": "14px 18px"}),
    ], style={"backgroundColor": _card_bg,
              "border": "1px solid rgba(255,255,255,0.06)",
              "borderRadius": "8px"}),
        md=3, sm=6, className="mb-2")


# =========================================================================
# Sector ETF helpers
# =========================================================================

def _make_etf_cards(df):
    if df is None or df.empty:
        return []
    above = (df["trend"] == "\u2713").sum()
    total = len(df)
    best = df.loc[df["perf_1m"].idxmax()]
    worst = df.loc[df["perf_1m"].idxmin()]
    most_vol = df.loc[df["adr"].idxmax()]
    trend_color = _green if above > total / 2 else _red

    best_sign = "+" if best["perf_1m"] >= 0 else ""
    worst_sign = "+" if worst["perf_1m"] >= 0 else ""

    return [
        _card("SECTORS ABOVE 200 SMA", f"{above} / {total}", "", trend_color),
        _card("STRONGEST SECTOR (1M)", best["ticker"],
              f"  {best_sign}{best['perf_1m']:.1f}%", _green),
        _card("WEAKEST SECTOR (1M)", worst["ticker"],
              f"  {worst_sign}{worst['perf_1m']:.1f}%", _red),
        _card("HIGHEST VOLATILITY", most_vol["ticker"],
              f"  ADR {most_vol['adr']:.1f}%", _cyan),
    ]


# =========================================================================
# Screener helpers
# =========================================================================

def _make_screener_cards(df):
    if df is None or df.empty:
        return [dbc.Col(html.P(
            "Enter tickers above and click Screen to analyse stocks.",
            className="text-muted", style={"fontSize": "0.9rem"}
        ), width=12)]

    total = len(df)
    avg_str = df["abs_strength"].mean() if "abs_strength" in df.columns else 0
    sectors = df["sector"].nunique() if "sector" in df.columns else 0
    tight = (df.get("vol_contraction", False) == True).sum()

    return [
        _card("STOCKS SCREENED", str(total), "", _green),
        _card("AVG ABS STRENGTH", f"{avg_str:.0f}", " / 99", _cyan),
        _card("SECTORS REPRESENTED", str(sectors), "", _orange),
        _card("VOL CONTRACTIONS", str(tight), " (RMV < 75)", _cyan),
    ]


# =========================================================================
# Register all callbacks
# =========================================================================

def register_callbacks(app):

    # =====================================================================
    # SIDEBAR NAVIGATION
    # =====================================================================
    _tab_ids = ["tab-sectors", "tab-screener", "tab-volume", "tab-gex", "tab-gex-alpaca", "tab-iv-walls", "tab-volume-ai",
                "tab-overnight", "tab-options-screener", "tab-tradingview",
                "tab-trade", "tab-alerts", "tab-ai"]
    _nav_ids = [f"nav-{t}" for t in _tab_ids]
    _page_ids = [f"page-{t}" for t in _tab_ids]

    @app.callback(
        Output("main-tabs", "data", allow_duplicate=True),
        [Input(nid, "n_clicks") for nid in _nav_ids],
        prevent_initial_call=True,
    )
    def sidebar_click(*n_clicks_list):
        ctx = callback_context
        if not ctx.triggered:
            return no_update
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        tab_id = trigger_id.replace("nav-", "")
        return tab_id

    @app.callback(
        [Output(pid, "style") for pid in _page_ids] +
        [Output(nid, "className") for nid in _nav_ids],
        Input("main-tabs", "data"),
    )
    def switch_page(active_tab):
        active_tab = active_tab or "tab-sectors"
        page_styles = []
        nav_classes = []
        for tid in _tab_ids:
            page_styles.append({"display": "block"} if tid == active_tab else {"display": "none"})
            nav_classes.append("sidebar-link active" if tid == active_tab else "sidebar-link")
        return page_styles + nav_classes

    # ----- Ask for Alpaca keys only when an Alpaca feature is opened -----
    @app.callback(
        [Output("alpaca-key-modal", "is_open"),
         Output("alpaca-key-status", "children"),
         Output("alpaca-credentials-ready", "data"),
         Output("alpaca-key-id", "value"),
         Output("alpaca-secret-key", "value")],
        [Input("main-tabs", "data"),
         Input("ivw-provider", "value"),
         Input("trade-env-toggle", "value"),
         Input("alpaca-key-save", "n_clicks"),
         Input("alpaca-key-cancel", "n_clicks")],
        [State("alpaca-key-environment", "value"),
         State("alpaca-key-id", "value"),
         State("alpaca-secret-key", "value")],
        prevent_initial_call=True,
    )
    def manage_alpaca_credentials(active_tab, ivw_provider, trade_environment,
                                  _save_clicks, _cancel_clicks,
                                  key_environment, api_key, secret_key):
        ctx = callback_context
        trigger_id = (ctx.triggered[0]["prop_id"].split(".")[0]
                      if ctx.triggered else "")

        if trigger_id == "alpaca-key-save":
            ok, message = validate_and_store_alpaca_credentials(
                key_environment, api_key, secret_key)
            if not ok:
                return True, message, no_update, no_update, no_update
            # Existing clients may have been created before the key changed.
            from engine import gex_alpaca as _gex_alpaca_module
            from app import trade as _trade_module
            _gex_alpaca_module.reset_clients()
            _trade_module.reset_clients()
            status = {
                "paper": alpaca_credentials_configured("paper"),
                "live": alpaca_credentials_configured("live"),
            }
            return False, message, status, "", ""

        if trigger_id == "alpaca-key-cancel":
            return False, "Alpaca features remain disabled.", no_update, "", ""

        alpaca_only_tab = active_tab in {"tab-gex-alpaca", "tab-trade"}
        alpaca_iv_selected = (active_tab == "tab-iv-walls"
                              and ivw_provider == "alpaca")
        if not alpaca_only_tab and not alpaca_iv_selected:
            return False, "", no_update, no_update, no_update

        required_environment = (trade_environment
                                if active_tab == "tab-trade" else None)
        configured = alpaca_credentials_configured(required_environment)
        if configured:
            return False, "", {
                "paper": alpaca_credentials_configured("paper"),
                "live": alpaca_credentials_configured("live"),
            }, no_update, no_update

        environment_label = required_environment or "paper or live"
        return (True,
                f"Add {environment_label} Alpaca credentials to use this section.",
                no_update, no_update, no_update)

    # ----- ETF: load data -----
    @app.callback(
        [Output("table-data-store", "data"),
         Output("summary-cards", "children"),
         Output("last-updated-text", "children")],
        [Input("refresh-interval", "n_intervals"),
         Input("refresh-btn", "n_clicks")],
    )
    def refresh_etf_data(_n, _clicks):
        ctx = callback_context
        force = any("refresh-btn" in t["prop_id"] for t in ctx.triggered) if ctx.triggered else False
        summary_df, _ = fetch_etf_data(force=force)
        records = summary_df.to_dict("records") if summary_df is not None else []
        cards = _make_etf_cards(summary_df)
        ts = f"Last updated: {get_last_fetch_time()}"
        return records, cards, ts

    # ----- ETF: filter / sort table -----
    @app.callback(
        Output("etf-table", "data"),
        [Input("table-data-store", "data"),
         Input("sector-filter", "value"),
         Input("sort-by", "value"),
         Input("sort-order", "value")],
    )
    def update_etf_table(records, sector, sort_col, sort_order):
        if not records:
            return []
        import pandas as pd
        df = pd.DataFrame(records)
        if sector and sector != "ALL":
            df = df[df["ticker"] == sector]
        asc = sort_order == "asc"
        if sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=asc, na_position="last")
        return df.to_dict("records")

    # ----- ETF: TradingView chart + holdings dropdown on click -----
    @app.callback(
        [Output("etf-tv-chart", "src"),
         Output("chart-card", "style"),
         Output("chart-title", "children"),
         Output("holdings-card", "style"),
         Output("holdings-title", "children"),
         Output("holdings-table", "data"),
         Output("holdings-symbols-store", "data"),
         Output("holdings-table", "selected_rows")],
        Input("etf-table", "active_cell"),
        State("etf-table", "derived_virtual_data"),
    )
    def show_etf_detail(active_cell, virtual_data):
        hidden = {"display": "none"}
        empty = "", hidden, "", hidden, "Top Holdings", [], [], []
        if not active_cell or not virtual_data:
            return empty
        row = virtual_data[active_cell["row"]]
        ticker = row["ticker"]
        info = SECTOR_ETFS.get(ticker, {})
        label = f"{ticker}  \u2014  {info.get('sector', '')}  |  {info.get('industries', '')}"
        url = _tradingview_url(f"AMEX:{ticker}")
        visible = {"display": "block", "backgroundColor": "#1a1a2e",
                   "border": "1px solid rgba(255,255,255,0.06)", "borderRadius": "8px"}

        from app.data import fetch_etf_holdings_metrics
        holdings = fetch_etf_holdings_metrics(ticker, top_n=10)

        if not holdings:
            return url, visible, label, visible, f"{ticker} Top 10 Holdings", [], [], []

        title = f"{ticker} Top 10 Holdings — Return Metrics"
        symbols = [h["symbol"] for h in holdings if h.get("symbol")]
        return url, visible, label, visible, title, holdings, symbols, []

    # ----- Holdings: screen selected holding -----
    @app.callback(
        [Output("main-tabs", "data", allow_duplicate=True),
         Output("scr-ticker-store", "data", allow_duplicate=True)],
        Input("holdings-screen-one-btn", "n_clicks"),
        [State("holdings-table", "selected_rows"),
         State("holdings-table", "data"),
         State("scr-ticker-store", "data")],
        prevent_initial_call=True,
    )
    def screen_one_holding(n_clicks, selected_rows, table_data, stored):
        if not n_clicks or not selected_rows or not table_data:
            return no_update, no_update
        idx = selected_rows[0]
        if idx >= len(table_data):
            return no_update, no_update
        symbol = (table_data[idx].get("symbol") or "").strip().upper()
        if not symbol:
            return no_update, no_update
        existing = set(stored or [])
        merged = list(existing | {symbol})
        return "tab-screener", merged

    # ----- Holdings: screen all holdings -----
    @app.callback(
        [Output("main-tabs", "data", allow_duplicate=True),
         Output("scr-ticker-store", "data", allow_duplicate=True)],
        Input("holdings-screen-all-btn", "n_clicks"),
        [State("holdings-symbols-store", "data"),
         State("scr-ticker-store", "data")],
        prevent_initial_call=True,
    )
    def screen_all_holdings(n_clicks, symbols, stored):
        if not n_clicks or not symbols:
            return no_update, no_update
        new_syms = {s.strip().upper() for s in symbols if s and s.strip()}
        existing = set(stored or [])
        merged = list(existing | new_syms)
        return "tab-screener", merged

    # ----- Screener: add / clear tickers -----
    @app.callback(
        [Output("scr-ticker-store", "data"),
         Output("scr-ticker-input", "value")],
        [Input("scr-add-btn", "n_clicks"),
         Input("scr-clear-btn", "n_clicks")],
        [State("scr-ticker-input", "value"),
         State("scr-ticker-store", "data")],
        prevent_initial_call=True,
    )
    def manage_tickers(add_clicks, clear_clicks, raw_text, stored):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update
        trigger = ctx.triggered[0]["prop_id"]

        if "scr-clear-btn" in trigger:
            remove_all_screened()
            return [], ""

        if not raw_text:
            return no_update, no_update

        new_syms = [s.strip().upper() for s in raw_text.replace(";", ",").split(",") if s.strip()]
        existing = set(stored or [])
        merged = list(existing | set(new_syms))
        return merged, ""

    # ----- Screener: fetch & screen when ticker store changes -----
    @app.callback(
        [Output("scr-data-store", "data"),
         Output("scr-summary-cards", "children"),
         Output("scr-sector-filter", "options"),
         Output("scr-status-text", "children")],
        Input("scr-ticker-store", "data"),
    )
    def refresh_screener(tickers):
        import pandas as pd

        if not tickers:
            return [], _make_screener_cards(None), [{"label": "All Sectors", "value": "ALL"}], ""

        df = fetch_watchlist_stocks(tickers)

        if not df.empty:
            save_screened_stocks(df)

        records = df.to_dict("records") if not df.empty else []
        cards = _make_screener_cards(df)

        sectors = sorted(df["sector"].dropna().unique().tolist()) if "sector" in df.columns and not df.empty else []
        sector_opts = [{"label": "All Sectors", "value": "ALL"}] + [
            {"label": s, "value": s} for s in sectors
        ]

        n_ok = len(df) if not df.empty else 0
        n_total = len(tickers)
        status = f"{n_ok}/{n_total} tickers loaded"
        return records, cards, sector_opts, status

    # ----- Screener: filter / sort table -----
    @app.callback(
        Output("scr-table", "data"),
        [Input("scr-data-store", "data"),
         Input("scr-sector-filter", "value"),
         Input("scr-sort-by", "value"),
         Input("scr-sort-order", "value"),
         Input("scr-vol-contraction", "value")],
    )
    def update_screener_table(records, sector, sort_col, sort_order, vol_only):
        if not records:
            return []
        import pandas as pd
        df = pd.DataFrame(records)
        if sector and sector != "ALL" and "sector" in df.columns:
            df = df[df["sector"] == sector]
        if vol_only and "vol_contraction" in df.columns:
            df = df[df["vol_contraction"] == True]
        asc = sort_order == "asc"
        if sort_col == "rmv_15":
            asc = not asc
        if sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=asc, na_position="last")
        if "avg_dollar_vol" in df.columns:
            df["avg_dollar_vol"] = (df["avg_dollar_vol"] / 1e6).round(1)
        return df.to_dict("records")

    # ----- Screener: TradingView chart on click -----
    @app.callback(
        [Output("scr-tv-chart", "src"),
         Output("scr-chart-card", "style"),
         Output("scr-chart-title", "children")],
        Input("scr-table", "active_cell"),
        State("scr-table", "derived_virtual_data"),
    )
    def show_screener_chart(active_cell, virtual_data):
        if not active_cell or not virtual_data:
            return "", {"display": "none"}, ""
        row = virtual_data[active_cell["row"]]
        symbol = row.get("symbol", "")
        name = row.get("name", "")
        sector = row.get("sector", "")
        industry = row.get("industry", "")
        label = f"{symbol}  \u2014  {name}  |  {sector} / {industry}"
        url = _tradingview_url(symbol)
        style = {"display": "block", "backgroundColor": "#1a1a2e",
                 "border": "1px solid rgba(255,255,255,0.06)", "borderRadius": "8px"}
        return url, style, label

    # ----- TradingView tab: update default period when indicator type changes -----
    @app.callback(
        Output("tv-ind-period", "value"),
        Input("tv-ind-type", "value"),
    )
    def update_default_period(ind_type):
        from app.layout import INDICATOR_CATALOG
        info = INDICATOR_CATALOG.get(ind_type, {})
        return info.get("default") or ""

    # ----- TradingView tab: add indicator -----
    @app.callback(
        Output("tv-indicators-store", "data", allow_duplicate=True),
        Input("tv-add-ind-btn", "n_clicks"),
        [State("tv-ind-type", "value"),
         State("tv-ind-period", "value"),
         State("tv-indicators-store", "data")],
        prevent_initial_call=True,
    )
    def add_indicator(n_clicks, ind_type, period, stored):
        if not n_clicks or not ind_type:
            return no_update
        from app.layout import INDICATOR_CATALOG
        info = INDICATOR_CATALOG.get(ind_type)
        if not info:
            return no_update

        has_len = info["has_length"]
        period_int = int(period) if period and has_len else None

        if period_int:
            key = f"{ind_type}_{period_int}"
            label = f"{ind_type} {period_int}"
            inputs = {"length": period_int}
        else:
            key = ind_type
            label = ind_type
            inputs = {}

        current = list(stored or [])
        if any(item["key"] == key for item in current):
            return no_update

        current.append({
            "key": key,
            "study_id": info["study_id"],
            "label": label,
            "inputs": inputs,
        })
        return current

    # ----- TradingView tab: remove indicator -----
    @app.callback(
        Output("tv-indicators-store", "data", allow_duplicate=True),
        Input({"type": "tv-rm-ind", "index": ALL}, "n_clicks"),
        State("tv-indicators-store", "data"),
        prevent_initial_call=True,
    )
    def remove_indicator(n_clicks_list, stored):
        if not n_clicks_list or not any(n_clicks_list):
            return no_update
        ctx = callback_context
        if not ctx.triggered_id or not isinstance(ctx.triggered_id, dict):
            return no_update
        key_to_remove = ctx.triggered_id["index"]
        current = [item for item in (stored or []) if item["key"] != key_to_remove]
        return current

    # ----- TradingView tab: render pills when store changes -----
    @app.callback(
        Output("tv-active-pills", "children"),
        Input("tv-indicators-store", "data"),
    )
    def render_pills(stored):
        return _render_pills(stored or [])

    # ----- TradingView tab: apply → save to MongoDB + rebuild chart -----
    @app.callback(
        Output("tv-main-chart", "srcDoc"),
        [Input("tv-apply-btn", "n_clicks"),
         Input("tv-indicators-store", "data")],
    )
    def build_tv_widget(n_clicks, stored_indicators):
        ctx = callback_context
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

        ind_list = stored_indicators or []

        if "tv-apply-btn" in triggered:
            save_indicator_prefs(ind_list)

        return _build_tv_widget_html(ind_list)

    # =====================================================================
    # TRADE TAB CALLBACKS
    # =====================================================================
    from app.trade import (
        fetch_account_summary, fetch_positions,
        fetch_expiration_dates, fetch_options_chain,
        execute_trade as _exec_trade, close_all_positions as _close_all,
        execute_mleg_order as _execute_mleg,
        fetch_filled_mleg_orders as _fetch_filled_mleg_orders,
        build_mleg_close_legs as _build_mleg_close_legs,
    )
    from datetime import datetime as _dt

    def _log_entry(msg: str) -> str:
        return f"[{_dt.now().strftime('%H:%M:%S')}] {msg}"

    # ----- Environment badge -----
    @app.callback(
        [Output("trade-env-badge", "children"),
         Output("trade-env-badge", "style"),
         Output("trade-env-store", "data")],
        Input("trade-env-toggle", "value"),
    )
    def update_env_badge(env):
        paper = env == "paper"
        if paper:
            return ("PAPER TRADING",
                    {"fontWeight": "700", "fontSize": "0.95rem",
                     "padding": "6px 16px", "borderRadius": "6px",
                     "display": "inline-block",
                     "backgroundColor": "rgba(0,212,126,0.15)",
                     "color": _green, "border": f"1px solid {_green}"},
                    "paper")
        return ("LIVE TRADING",
                {"fontWeight": "700", "fontSize": "0.95rem",
                 "padding": "6px 16px", "borderRadius": "6px",
                 "display": "inline-block",
                 "backgroundColor": "rgba(255,71,87,0.15)",
                 "color": _red, "border": f"1px solid {_red}"},
                "live")

    # ----- Auto-refresh interval control -----
    @app.callback(
        [Output("trade-auto-interval", "interval"),
         Output("trade-auto-interval", "disabled")],
        Input("trade-auto-refresh", "value"),
    )
    def set_auto_refresh(val):
        if not val or val == "Off":
            return 1_000_000, True
        secs = int(val.replace("s", ""))
        return secs * 1000, False

    # ----- Refresh account + positions -----
    @app.callback(
        [Output("trade-equity", "children"),
         Output("trade-buying-power", "children"),
         Output("trade-cash", "children"),
         Output("trade-positions-table", "data"),
         Output("trade-log", "children", allow_duplicate=True)],
        [Input("trade-refresh-btn", "n_clicks"),
         Input("trade-env-store", "data"),
         Input("trade-auto-interval", "n_intervals")],
        State("trade-log-store", "data"),
        prevent_initial_call=True,
    )
    def refresh_trade_data(n_clicks, env, n_intervals, log_lines):
        paper = env == "paper"
        acct = fetch_account_summary(paper)
        positions = fetch_positions(paper)
        log_lines = list(log_lines or [])
        ctx = callback_context
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        is_auto = "trade-auto-interval" in triggered
        if not is_auto:
            log_lines.append(_log_entry(f"Refreshed — {'PAPER' if paper else 'LIVE'}"))
        log_text = "\n".join(log_lines[-20:])
        return (
            f"${acct['equity']:,.2f}",
            f"${acct['buying_power']:,.2f}",
            f"${acct['cash']:,.2f}",
            positions,
            log_text,
        )

    # ----- Filled multi-leg orders available for coordinated closing ----
    @app.callback(
        [Output("trade-mleg-order-select", "options"),
         Output("trade-mleg-order-select", "value"),
         Output("trade-mleg-orders-store", "data"),
         Output("trade-log", "children", allow_duplicate=True)],
        [Input("trade-mleg-refresh-btn", "n_clicks"),
         Input("trade-env-store", "data")],
        State("trade-log-store", "data"),
        prevent_initial_call=True,
    )
    def refresh_mleg_orders(_n_clicks, env, log_lines):
        orders = _fetch_filled_mleg_orders(paper=(env == "paper"))
        log_lines = list(log_lines or [])
        if orders and orders[0].get("error"):
            log_lines.append(_log_entry(f"Spread refresh FAILED: {orders[0]['error']}"))
            return [], None, [], "\n".join(log_lines[-20:])
        options = []
        for order in orders:
            legs_text = " / ".join(
                f"{l['side'].upper()} {l['symbol']}" for l in order["legs"]
            )
            when = order.get("submitted_at", "").replace("T", " ")[:16]
            options.append({
                "label": f"{when} • {legs_text} • qty {order['qty']:g}",
                "value": order["id"],
            })
        log_lines.append(_log_entry(
            f"Loaded {len(orders)} filled multi-leg spread(s) — "
            f"{'PAPER' if env == 'paper' else 'LIVE'}"
        ))
        return options, (options[0]["value"] if options else None), orders, "\n".join(log_lines[-20:])

    # ----- Selected filled spread → coordinated close payload modal ------
    @app.callback(
        [Output("risk-execute-modal", "is_open", allow_duplicate=True),
         Output("risk-execute-summary", "children", allow_duplicate=True),
         Output("risk-execute-json", "children", allow_duplicate=True),
         Output("risk-execute-env-banner", "children", allow_duplicate=True),
         Output("risk-execute-env-banner", "style", allow_duplicate=True),
         Output("risk-execute-submit", "children", allow_duplicate=True),
         Output("risk-execute-submit", "color", allow_duplicate=True),
         Output("risk-execute-payload", "data", allow_duplicate=True),
         Output("risk-execute-qty", "value", allow_duplicate=True),
         Output("risk-execute-totals", "children", allow_duplicate=True)],
        Input("trade-mleg-close-btn", "n_clicks"),
        [State("trade-mleg-order-select", "value"),
         State("trade-mleg-orders-store", "data"),
         State("trade-mleg-close-price", "value"),
         State("trade-env-store", "data")],
        prevent_initial_call=True,
    )
    def open_mleg_close(n_clicks, order_id, orders, close_price, env):
        if not n_clicks or not order_id or not orders:
            return (no_update,) * 10
        order = next((o for o in orders if o.get("id") == order_id), None)
        if not order or not close_price or float(close_price) <= 0:
            return (no_update,) * 10
        legs = _build_mleg_close_legs(order)
        payload = {
            "qty": int(order.get("qty") or 1),
            "type": "limit",
            "time_in_force": "day",
            "order_class": "mleg",
            "limit_price": round(float(close_price), 2),
            "legs": legs,
            "_env": env,
            "_kind": "close",
        }
        payload_json = json.dumps({k: v for k, v in payload.items() if not k.startswith("_")}, indent=2)
        env_label = "PAPER" if env == "paper" else "LIVE (REAL MONEY)"
        banner_style = {
            "marginBottom": "10px", "padding": "8px 12px", "borderRadius": "5px",
            "fontSize": "0.82rem", "fontWeight": "700",
            "backgroundColor": "rgba(0,212,126,0.10)" if env == "paper" else "rgba(255,71,87,0.12)",
            "border": f"1px solid {_green if env == 'paper' else _red}",
        }
        summary = html.Div([
            html.Div("CLOSE MULTI-LEG SPREAD", style={"fontWeight": "800", "color": _cyan}),
            html.Div(f"Original order: {order_id}", style={"color": "#aaa", "fontSize": "0.78rem"}),
            html.Div("Legs have been reversed to BUY/SELL_TO_CLOSE or SELL/BUY_TO_CLOSE.",
                     style={"marginTop": "6px", "fontWeight": "700"}),
            html.Div(f"Closing net limit: ${float(close_price):.2f} • Quantity: {payload['qty']}",
                     style={"marginTop": "6px", "fontFamily": "Consolas, monospace"}),
        ])
        banner = html.Span(
            f"{env_label}: this will submit one coordinated closing mleg order.",
            style={"color": _red if env != "paper" else "#d0d0d0"},
        )
        return (True, summary, payload_json, banner, banner_style,
                "SUBMIT CLOSE ORDER", "danger", payload, payload["qty"],
                "Closing order — verify the legs and limit price above.")

    # ----- Position click → fill trade symbol -----
    @app.callback(
        [Output("trade-symbol", "value", allow_duplicate=True),
         Output("trade-qty", "value", allow_duplicate=True)],
        Input("trade-positions-table", "selected_rows"),
        State("trade-positions-table", "data"),
        prevent_initial_call=True,
    )
    def fill_from_position(selected_rows, data):
        if not selected_rows or not data:
            return no_update, no_update
        row = data[selected_rows[0]]
        return row["symbol"], abs(float(row["qty"])) if row["qty"] else 1

    # ----- Limit price toggle -----
    @app.callback(
        Output("trade-limit-price", "disabled"),
        Input("trade-order-type", "value"),
    )
    def toggle_limit(order_type):
        return order_type != "Limit"

    # ----- BUY / SELL → open confirm modal -----
    @app.callback(
        [Output("trade-confirm-modal", "is_open", allow_duplicate=True),
         Output("trade-confirm-body", "children", allow_duplicate=True),
         Output("trade-confirm-action", "data", allow_duplicate=True)],
        [Input("trade-buy-btn", "n_clicks"),
         Input("trade-sell-btn", "n_clicks"),
         Input("trade-close-all-btn", "n_clicks")],
        [State("trade-symbol", "value"),
         State("trade-qty", "value"),
         State("trade-order-type", "value"),
         State("trade-limit-price", "value"),
         State("trade-tif", "value"),
         State("trade-env-store", "data")],
        prevent_initial_call=True,
    )
    def open_confirm_modal(buy_n, sell_n, close_n,
                           symbol, qty, order_type, limit_price, tif, env):
        ctx = callback_context
        if not ctx.triggered:
            return False, "", None
        trigger = ctx.triggered[0]["prop_id"]
        env_label = "PAPER" if env == "paper" else "LIVE (REAL MONEY)"

        if "trade-close-all-btn" in trigger:
            return (
                True,
                html.Div([
                    html.P(f"Environment: {env_label}", style={"fontWeight": "700",
                           "color": _red if env == "live" else _green}),
                    html.P("Are you sure you want to CLOSE ALL open positions?",
                           style={"fontWeight": "700"}),
                ]),
                {"action": "close_all", "env": env},
            )

        side = "BUY" if "trade-buy-btn" in trigger else "SELL"
        if not symbol or not qty:
            return False, "", None
        msg = f"{side} {qty} x {symbol} ({order_type}, {tif})"
        if order_type == "Limit" and limit_price:
            msg += f" @ ${limit_price}"

        return (
            True,
            html.Div([
                html.P(f"Environment: {env_label}",
                       style={"fontWeight": "700",
                              "color": _red if env == "live" else _green}),
                html.P(msg, style={"fontWeight": "700", "fontSize": "1.05rem"}),
                html.P("Confirm this order?"),
            ]),
            {"action": "trade", "side": side, "symbol": symbol.upper(),
             "qty": float(qty), "order_type": order_type,
             "limit_price": float(limit_price) if limit_price else None,
             "tif": tif, "env": env},
        )

    # ----- Confirm cancel -----
    @app.callback(
        Output("trade-confirm-modal", "is_open", allow_duplicate=True),
        Input("trade-confirm-cancel", "n_clicks"),
        prevent_initial_call=True,
    )
    def cancel_confirm(_):
        return False

    # ----- Confirm OK → execute -----
    @app.callback(
        [Output("trade-confirm-modal", "is_open"),
         Output("trade-confirm-body", "children"),
         Output("trade-confirm-action", "data"),
         Output("trade-log", "children")],
        Input("trade-confirm-ok", "n_clicks"),
        [State("trade-confirm-action", "data"),
         State("trade-log-store", "data")],
        prevent_initial_call=True,
    )
    def execute_confirmed(n_clicks, action, log_lines):
        if not n_clicks or not action:
            return no_update, no_update, no_update, no_update
        log_lines = list(log_lines or [])
        paper = action.get("env") == "paper"

        if action.get("action") == "close_all":
            result = _close_all(paper=paper)
            log_lines.append(_log_entry(result))
        elif action.get("action") == "trade":
            result = _exec_trade(
                symbol=action["symbol"],
                qty=action["qty"],
                side=action["side"],
                order_type=action.get("order_type", "Market"),
                limit_price=action.get("limit_price"),
                tif=action.get("tif", "DAY"),
                paper=paper,
            )
            log_lines.append(_log_entry(result))

        return False, "", None, "\n".join(log_lines[-20:])

    # ----- Options: load expiration dates -----
    @app.callback(
        [Output("opt-exp-date", "options"),
         Output("opt-exp-date", "value"),
         Output("opt-current-price", "children"),
         Output("opt-price-store", "data"),
         Output("trade-log", "children", allow_duplicate=True)],
        Input("opt-load-dates-btn", "n_clicks"),
        [State("opt-symbol", "value"),
         State("trade-log-store", "data")],
        prevent_initial_call=True,
    )
    def load_opt_dates(n_clicks, symbol, log_lines):
        if not n_clicks or not symbol:
            return no_update, no_update, no_update, no_update, no_update
        log_lines = list(log_lines or [])
        try:
            dates, price = fetch_expiration_dates(symbol)
            if not dates:
                log_lines.append(_log_entry(f"No options data for {symbol.upper()}"))
                return [], None, "", 0, "\n".join(log_lines[-20:])
            opts = [{"label": d, "value": d} for d in dates]
            log_lines.append(_log_entry(
                f"Loaded {len(dates)} exp dates for {symbol.upper()} @ ${price:.2f}"))
            return opts, dates[0], f"Price: ${price:.2f}", price, "\n".join(log_lines[-20:])
        except Exception as exc:
            log_lines.append(_log_entry(f"Error loading dates: {exc}"))
            return [], None, "", 0, "\n".join(log_lines[-20:])

    # ----- Options: load chain (writes RAW store; filter callback below
    #       classifies + filters into the visible DataTable) -----
    @app.callback(
        [Output("opt-chain-raw-store", "data"),
         Output("trade-log", "children", allow_duplicate=True)],
        Input("opt-load-chain-btn", "n_clicks"),
        [State("opt-symbol", "value"),
         State("opt-exp-date", "value"),
         State("opt-spread", "value"),
         State("opt-price-store", "data"),
         State("trade-env-store", "data"),
         State("trade-log-store", "data")],
        prevent_initial_call=True,
    )
    def load_opt_chain(n_clicks, symbol, exp_date, spread, price, env, log_lines):
        if not n_clicks or not symbol or not exp_date:
            return no_update, no_update
        log_lines = list(log_lines or [])
        paper = env == "paper"
        try:
            chain = fetch_options_chain(
                symbol=symbol, expiration_date=exp_date,
                spread=int(spread or 5), current_price=float(price or 0),
                paper=paper,
            )
            log_lines.append(_log_entry(
                f"Loaded {len(chain)} contracts for {symbol.upper()} exp {exp_date}"))
            return chain, "\n".join(log_lines[-20:])
        except Exception as exc:
            log_lines.append(_log_entry(f"Chain error: {exc}"))
            return [], "\n".join(log_lines[-20:])

    # ----- Options: classify ITM/ATM/OTM and pass through to chain table.
    #
    # Classification (relative to the underlying spot price):
    #   CALL: ITM if strike < spot - tol;  ATM if |strike-spot| <= tol;  OTM if strike > spot + tol
    #   PUT : ITM if strike > spot + tol;  ATM if |strike-spot| <= tol;  OTM if strike < spot - tol
    #
    # The chain table always shows ALL classified rows (so the user can
    # see the full chain with moneyness color-coding).  The actual
    # ITM/ATM/OTM *filter* lives in the Risk Engine (Step 2) and is
    # applied inside filter_spreads when building candidates.
    def _classify_moneyness(opt_type: str, strike: float,
                            spot: float, tol: float) -> str:
        if not spot or spot <= 0:
            return "ATM"  # no spot ⇒ can't classify; treat as neutral
        diff = strike - spot
        if abs(diff) <= tol:
            return "ATM"
        t = (opt_type or "").upper()
        if t == "CALL":
            return "ITM" if diff < 0 else "OTM"
        if t == "PUT":
            return "ITM" if diff > 0 else "OTM"
        return "ATM"

    @app.callback(
        Output("opt-chain-table", "data"),
        [Input("opt-chain-raw-store", "data"),
         Input("risk-atm-tol", "value"),
         Input("opt-price-store", "data")],
    )
    def classify_chain_rows(raw_chain, tol_value, spot):
        raw_chain = raw_chain or []
        try:
            tol = float(tol_value) if tol_value is not None else 1.0
        except (TypeError, ValueError):
            tol = 1.0
        if tol < 0:
            tol = 0.0
        try:
            spot_f = float(spot) if spot else 0.0
        except (TypeError, ValueError):
            spot_f = 0.0

        if not raw_chain:
            return []

        out: list[dict] = []
        for row in raw_chain:
            try:
                strike = float(row.get("strike"))
            except (TypeError, ValueError):
                continue
            m = _classify_moneyness(row.get("type"), strike, spot_f, tol)
            out.append({**row, "moneyness": m})
        return out

    # ----- Options: double-click row → fill trade symbol -----
    @app.callback(
        [Output("trade-symbol", "value"),
         Output("trade-qty", "value")],
        Input("opt-chain-table", "selected_rows"),
        State("opt-chain-table", "data"),
        prevent_initial_call=True,
    )
    def fill_from_option(selected_rows, data):
        if not selected_rows or not data:
            return no_update, no_update
        row = data[selected_rows[0]]
        return row.get("option_symbol", ""), 1

    # =====================================================================
    # RISK ENGINE — Debit/Credit Spread + Iron Condor Builder
    #              (sources from live Options Chain)
    # =====================================================================
    from app.layout import build_candidates as _build_spreads
    from app.layout import STRATEGY_META as _STRAT_META

    _AWAITING_PILL_STYLE = {
        "fontSize": "0.68rem", "letterSpacing": "1.5px",
        "padding": "3px 10px", "borderRadius": "3px",
        "color": "#888", "backgroundColor": "rgba(255,255,255,0.05)",
        "border": "1px solid rgba(255,255,255,0.18)", "fontWeight": "700",
    }
    _LIVE_PILL_STYLE = {
        "fontSize": "0.68rem", "letterSpacing": "1.5px",
        "padding": "3px 10px", "borderRadius": "3px",
        "color": _green, "backgroundColor": "rgba(0,212,126,0.12)",
        "border": f"1px solid {_green}", "fontWeight": "700",
    }

    # Column definitions for the dynamic Risk Engine table header.  Each
    # entry is (col_id, label, width_pct, align, sortable).  The Net /
    # PnL columns vary with strategy + move so we build them at render
    # time.
    def _risk_columns(move_val: float, strategy_key: str):
        meta = _STRAT_META.get(strategy_key) or {}
        kind = meta.get("kind", "debit")

        # PnL header sign reflects the literal sign of the user-typed move.
        # +X.XX  → underlying up,   -X.XX → underlying down,   0 → no move.
        if move_val > 0:
            pnl_label = f"Est. PnL (+${move_val:.2f})"
        elif move_val < 0:
            pnl_label = f"Est. PnL (\u2212${abs(move_val):.2f})"
        else:
            pnl_label = "Est. PnL ($0.00)"

        net_label = "Net Credit" if kind == "credit" else "Net Debit"

        return [
            ("strategy",   "Strategy",    11, "left",  False),
            ("strikes",    "Strikes",     14, "left",  True),
            ("width",      "Width",        6, "right", True),
            ("net",        net_label,     10, "right", True),
            ("max_profit", "Max Profit",   9, "right", True),
            ("max_loss",   "Max Loss",     9, "right", True),
            ("target_rr",  "Target RR",    7, "right", True),
            ("net_delta",  "Net \u0394",   9, "right", True),
            ("est_pnl",    pnl_label,     13, "right", True),
            ("action",     "",            12, "right", False),
        ]

    def _sort_value(c: dict, col: str):
        """Return a numeric sort key for column `col`, or None when missing."""
        if col == "strikes":
            return c.get("lower_strike")
        return c.get(col)

    def _sort_candidates(passing: list[dict], col: str, direction: str) -> list[dict]:
        if not passing or col in ("strategy", "action"):
            return passing
        desc = direction == "desc"
        sentinel = float("-inf") if desc else float("inf")

        def key(c):
            v = _sort_value(c, col)
            return sentinel if v is None else v
        return sorted(passing, key=key, reverse=desc)

    def _render_thead(move_val: float, strategy_key: str, sort_col: str,
                      sort_dir: str):
        ths = []
        for col_id, label, width_pct, align, sortable in _risk_columns(
                move_val, strategy_key):
            cell_style = {"width": f"{width_pct}%", "textAlign": align}
            if sortable:
                indicator = ""
                if col_id == sort_col:
                    indicator = " \u25BC" if sort_dir == "desc" else " \u25B2"
                btn = html.Button(
                    children=[
                        html.Span(label),
                        html.Span(indicator,
                                  style={"color": _cyan,
                                         "fontWeight": "800",
                                         "marginLeft": "4px"}),
                    ],
                    id={"type": "risk-sort-btn", "col": col_id},
                    n_clicks=0,
                    className="risk-sort-header"
                              + (" active" if col_id == sort_col else ""),
                )
                ths.append(html.Th(btn, style=cell_style))
            else:
                ths.append(html.Th(label, style=cell_style))
        return html.Tr(ths, style={"borderBottom": f"2px solid {_cyan}"})

    def _fmt_pnl(v):
        if v is None:
            return "\u2014"
        return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"

    _STRAT_PILL_CLASS = {
        "Bull Call":   "strategy-pill bull-call",
        "Bear Put":    "strategy-pill bear-put",
        "Bull Put":    "strategy-pill bull-put",
        "Bear Call":   "strategy-pill bear-call",
        "Iron Condor": "strategy-pill iron-condor",
    }
    _STRAT_HEADER_COLOR = {
        "Bull Call":   _green,
        "Bear Put":    _red,
        "Bull Put":    "#5fdba0",
        "Bear Call":   "#ff8c5a",
        "Iron Condor": "#b388ff",
    }

    def _render_spread_rows(candidates: list[dict]) -> list:
        """Build html.Tbody children from a list of filtered spreads."""
        rows = []
        for idx, c in enumerate(candidates):
            kind = c.get("kind", "debit")
            n_legs = c.get("n_legs", 2)
            pill_cls = _STRAT_PILL_CLASS.get(c["strategy"], "strategy-pill bull-call")
            width = c["width"]
            width_str = (f"${int(width)}"
                         if abs(width - int(width)) < 1e-6
                         else f"${width:g}")

            # Net cell — orange for debit (you pay), green for credit (you collect)
            if kind == "credit":
                net_text = f"+${c['net']:.2f}"
                net_color = _green
                net_sub = "credit"
            else:
                net_text = f"${c['net']:.2f}"
                net_color = "#ffa502"
                net_sub = "debit"

            net_cell = html.Td([
                html.Div(net_text,
                         style={"color": net_color, "fontWeight": "700",
                                "fontFamily": "'Consolas', monospace",
                                "fontSize": "0.88rem", "lineHeight": "1.05"}),
                html.Div(net_sub,
                         style={"color": "#888", "fontSize": "0.62rem",
                                "letterSpacing": "1px",
                                "textTransform": "uppercase",
                                "marginTop": "1px"}),
            ], className="num-cell", style={"textAlign": "right"})

            est_pnl = c.get("est_pnl")
            roi_pct = c.get("roi_pct")
            net_delta = c.get("net_delta")

            if est_pnl is None:
                pnl_main_color = "#666"
                pnl_main_text = "\u2014"
                pnl_sub_text = "no \u0394 data"
            else:
                pnl_main_color = (_green if est_pnl > 0
                                  else (_red if est_pnl < 0 else "#888"))
                pnl_main_text = _fmt_pnl(est_pnl)
                if roi_pct is None:
                    pnl_sub_text = ""
                else:
                    sign = "+" if roi_pct >= 0 else ""
                    pnl_sub_text = f"{sign}{roi_pct:.2f}% ROI"

            pnl_cell = html.Td([
                html.Div(pnl_main_text,
                         style={"color": pnl_main_color,
                                "fontWeight": "800",
                                "fontFamily": "'Consolas', monospace",
                                "fontSize": "0.92rem",
                                "lineHeight": "1.05"}),
                html.Div(pnl_sub_text,
                         style={"color": "#888",
                                "fontSize": "0.7rem",
                                "fontFamily": "'Consolas', monospace",
                                "marginTop": "2px",
                                "letterSpacing": "0.5px"}),
            ], className="est-pnl-cell",
               style={"textAlign": "right",
                      "padding": "8px 12px",
                      "borderLeft": "1px solid rgba(78,205,196,0.10)"})

            # Net Δ cell — signed, color-coded (green=long Δ, red=short Δ,
            # gray=near-zero, muted dash if no Greek data).
            if net_delta is None:
                nd_main = "\u2014"
                nd_color = "#666"
                nd_sub = "no \u0394 data"
                nd_sub_color = "#555"
            else:
                nd_main = f"{net_delta:+.3f}"
                if abs(net_delta) < 0.05:
                    nd_color = "#888"
                    nd_sub = "neutral"
                elif net_delta > 0:
                    nd_color = _green
                    nd_sub = "long \u0394"
                else:
                    nd_color = _red
                    nd_sub = "short \u0394"
                nd_sub_color = "#888"

            net_delta_cell = html.Td([
                html.Div(nd_main,
                         style={"color": nd_color,
                                "fontWeight": "800",
                                "fontFamily": "'Consolas', monospace",
                                "fontSize": "0.88rem",
                                "lineHeight": "1.05"}),
                html.Div(nd_sub,
                         style={"color": nd_sub_color,
                                "fontSize": "0.62rem",
                                "letterSpacing": "1px",
                                "textTransform": "uppercase",
                                "marginTop": "1px"}),
            ], className="num-cell net-delta-cell",
               style={"textAlign": "right"})

            # Strikes cell — show extra "4 LEGS" tag for Iron Condors
            strikes_children: list = [
                html.Div(c["strikes_label"],
                         style={"fontFamily": "'Consolas', monospace",
                                "fontWeight": "700", "color": "#fff",
                                "fontSize": "0.85rem", "lineHeight": "1.1"}),
            ]
            if n_legs == 4:
                strikes_children.append(
                    html.Div("4 LEGS \u2022 long put / short put \u2502 short call / long call",
                             style={"color": "#888", "fontSize": "0.62rem",
                                    "letterSpacing": "0.5px",
                                    "marginTop": "2px",
                                    "fontFamily": "'Consolas', monospace"}),
                )

            rows.append(html.Tr([
                html.Td(html.Span(c["strategy"], className=pill_cls)),
                html.Td(strikes_children),
                html.Td(width_str, className="num-cell muted-cell"),
                net_cell,
                html.Td(f"+${c['max_profit']:.2f}",
                        className="num-cell profit-cell"),
                html.Td(f"-${c['max_loss']:.2f}",
                        className="num-cell loss-cell"),
                html.Td(f"1 : {c['target_rr']:.2f}",
                        className="num-cell rr-cell"),
                net_delta_cell,
                pnl_cell,
                html.Td(
                    html.Button(
                        "Execute (mleg)",
                        id={"type": "mleg-exec", "index": idx},
                        n_clicks=0,
                        className="mleg-execute-btn",
                    ),
                    style={"textAlign": "right"},
                ),
            ]))
        return rows

    def _make_source_display(loaded: bool, ticker: str = "", expiration: str = "",
                             spot: float = 0.0, n_contracts: int = 0,
                             n_legs_for_strategy: int = 0,
                             strategy_label: str = "") -> list:
        if not loaded:
            return html.Div([
                html.Span("\u26a0 ", style={"color": "#ffa502",
                                              "marginRight": "4px"}),
                html.Span("No options chain loaded.",
                          style={"color": "#d0d0d0", "fontWeight": "600"}),
                html.Span(" Use ", style={"color": "#888"}),
                html.Span("Step 1", style={"color": _cyan, "fontWeight": "700"}),
                html.Span(" above to load an options chain — "
                          "the Risk Engine will populate automatically.",
                          style={"color": "#888"}),
            ])
        spot_str = f"${float(spot):,.2f}" if spot else "—"
        return html.Div([
            html.Span("SOURCE",
                      style={"fontSize": "0.65rem", "letterSpacing": "1.5px",
                             "color": "#888", "fontWeight": "700",
                             "marginRight": "10px"}),
            html.Span(f"{ticker.upper()}",
                      style={"fontWeight": "800", "color": "#fff",
                             "fontFamily": "'Consolas', monospace",
                             "fontSize": "0.95rem", "letterSpacing": "1px"}),
            html.Span(f" @ {spot_str}",
                      style={"color": "#b388ff", "fontWeight": "700",
                             "fontFamily": "'Consolas', monospace",
                             "fontSize": "0.88rem", "marginRight": "14px"}),
            html.Span(f"\u2022 exp {expiration}",
                      style={"color": "#888", "fontSize": "0.82rem",
                             "marginRight": "14px"}),
            html.Span(f"\u2022 {n_contracts} contracts loaded",
                      style={"color": "#888", "fontSize": "0.82rem",
                             "marginRight": "14px"}),
            html.Span(f"\u2022 {n_legs_for_strategy} {strategy_label} legs usable",
                      style={"color": _cyan, "fontSize": "0.82rem",
                             "fontWeight": "600"}),
        ])

    # ----- Filter spreads when slider / strategy / chain / move / sort /
    #       moneyness / atm-tol --
    @app.callback(
        [Output("risk-spreads-thead", "children"),
         Output("risk-spreads-tbody", "children"),
         Output("risk-spreads-empty", "children"),
         Output("risk-rr-display", "children"),
         Output("risk-debit-cap", "children"),
         Output("risk-candidate-count", "children"),
         Output("risk-candidate-count", "style"),
         Output("risk-status-pill", "children"),
         Output("risk-source-display", "children"),
         Output("risk-move-hint", "children"),
         Output("risk-moneyness-count", "children"),
         Output("risk-delta-hint", "children"),
         Output("risk-rr-panel", "className"),
         Output("risk-rr-enable-label", "children"),
         Output("risk-rr-enable-label", "style"),
         Output("risk-candidates-store", "data")],
        [Input("risk-rr-slider", "value"),
         Input("risk-strategy", "value"),
         Input("opt-chain-table", "data"),
         Input("risk-move-input", "value"),
         Input("risk-sort-store", "data"),
         Input("risk-moneyness-filter", "value"),
         Input("risk-atm-tol", "value"),
         Input("risk-delta-min", "value"),
         Input("risk-delta-max", "value"),
         Input("risk-rr-enable", "value")],
        [State("opt-symbol", "value"),
         State("opt-exp-date", "value"),
         State("opt-price-store", "data")],
    )
    def filter_spreads(rr_value, strategy, chain_rows, move_value, sort_data,
                       moneyness_sel, atm_tol, delta_min, delta_max,
                       rr_enabled,
                       ticker, expiration, spot):
        rr = float(rr_value or 1.2)
        strat = strategy or "bull_call"
        meta = _STRAT_META.get(strat) or _STRAT_META["bull_call"]
        kind = meta["kind"]
        move_mult = meta["move_mult"]
        n_legs_strat = meta["n_legs"]
        chain_rows = chain_rows or []
        loaded = bool(chain_rows)
        try:
            spot_f = float(spot) if spot else 0.0
        except (TypeError, ValueError):
            spot_f = 0.0

        try:
            move_val = float(move_value) if move_value is not None else 0.0
        except (TypeError, ValueError):
            move_val = 0.0

        # Moneyness filter — applied to chain_rows BEFORE building spreads.
        # Rows already carry a "moneyness" field (set by classify_chain_rows).
        # If a row is missing the field (e.g. tol changed mid-render), we
        # re-classify on the fly using the same tol the user typed.
        # NOTE: `None` (callback init) ⇒ default all-on; `[]` (user
        # explicitly deselected every bucket) ⇒ legitimately empty set.
        if moneyness_sel is None:
            money_sel = {"ITM", "ATM", "OTM"}
        else:
            money_sel = set(moneyness_sel)
        try:
            atm_tol_f = float(atm_tol) if atm_tol is not None else 1.0
        except (TypeError, ValueError):
            atm_tol_f = 1.0
        if atm_tol_f < 0:
            atm_tol_f = 0.0

        bucket_counts = {"ITM": 0, "ATM": 0, "OTM": 0}
        filtered_rows: list[dict] = []
        for r in chain_rows:
            m = r.get("moneyness")
            if not m:
                try:
                    k = float(r.get("strike"))
                    m = _classify_moneyness(r.get("type"), k,
                                            spot_f, atm_tol_f)
                except (TypeError, ValueError):
                    continue
            bucket_counts[m] = bucket_counts.get(m, 0) + 1
            if m in money_sel:
                filtered_rows.append(r if r.get("moneyness")
                                     else {**r, "moneyness": m})

        money_count_text = (
            f"ITM {bucket_counts['ITM']}  \u2022  "
            f"ATM {bucket_counts['ATM']}  \u2022  "
            f"OTM {bucket_counts['OTM']}    "
            f"({len(filtered_rows)} / {len(chain_rows)} usable)"
        )

        # Net Delta range filter — parse min/max with sane defaults of
        # [-1, +1] (which spans every possible spread Δ → effectively off).
        try:
            d_min = float(delta_min) if delta_min is not None else -1.0
        except (TypeError, ValueError):
            d_min = -1.0
        try:
            d_max = float(delta_max) if delta_max is not None else 1.0
        except (TypeError, ValueError):
            d_max = 1.0
        if d_min > d_max:
            d_min, d_max = d_max, d_min  # auto-correct swapped inputs
        delta_filter_active = (d_min > -1.0 + 1e-9) or (d_max < 1.0 - 1e-9)
        if delta_filter_active:
            sign_min = "+" if d_min >= 0 else "\u2212"
            sign_max = "+" if d_max >= 0 else "\u2212"
            delta_hint = (f"\u0394 \u2208 [{sign_min}{abs(d_min):.2f}, "
                          f"{sign_max}{abs(d_max):.2f}]")
        else:
            delta_hint = "any \u0394 (filter inactive)"

        sort_data = sort_data or {"col": "est_pnl", "dir": "desc"}
        sort_col = sort_data.get("col") or "est_pnl"
        sort_dir = sort_data.get("dir") or "desc"

        # RR filter on/off toggle.  Default to ON (None ⇒ enabled).
        rr_on = True if rr_enabled is None else bool(rr_enabled)

        # Slider readout + per-strategy filter-hint text.
        # Debit spreads filter on:    net_debit  <= width / (1 + RR)
        # Credit / IC spreads on:     max_profit /  max_loss >= RR
        if not rr_on:
            debit_cap_text = ("RR filter is OFF \u2014 every candidate from "
                              "the moneyness + delta filters appears in the "
                              "table regardless of risk:reward.")
        elif kind == "credit":
            # Show what fraction of width must be retained as profit.
            # For width=$10 examples → "min credit $X.XX per $10 wing"
            # using credit_min = width * RR / (1 + RR).
            credit_min_10 = 10 * rr / (1 + rr)
            debit_cap_text = (
                f"Min reward/risk: 1 : {rr:.2f}  "
                f"\u2022  e.g. \u2265 ${credit_min_10:.2f} credit on a $10 wing  "
                f"\u2022  formula: max_profit / max_loss \u2265 RR"
            )
        else:
            cap_10 = 10 / (1 + rr)
            debit_cap_text = (f"Max acceptable debit: ${cap_10:.2f} per $10 width "
                              f"\u2022 ${cap_10*2:.2f} per $20 \u2022 "
                              f"${cap_10*3:.2f} per $30  "
                              f"\u2022 formula: width / (1 + RR)")
        # Show 2 decimals so sub-1.0 values like 0.45 don't get rounded
        # to 0.5 in the readout.  When OFF, the readout dims via CSS.
        rr_text = f"{rr:.2f}"

        # Visual state for the slider panel + toggle label.
        rr_panel_class = "rr-panel" if rr_on else "rr-panel rr-disabled"
        if rr_on:
            rr_toggle_label = "filter ON"
            rr_toggle_style = {"fontSize": "0.7rem",
                               "letterSpacing": "1.5px",
                               "fontWeight": "800",
                               "color": "#5fdba0"}
        else:
            rr_toggle_label = "filter OFF"
            rr_toggle_style = {"fontSize": "0.7rem",
                               "letterSpacing": "1.5px",
                               "fontWeight": "800",
                               "color": "#ff8c5a"}

        # Move-direction hint describes the LITERAL signed move the user
        # typed.  For Iron Condor (delta-neutral) we add a theta callout.
        if strat == "iron_condor":
            if move_val == 0:
                move_hint = ("Static: no projected move "
                             "(delta-neutral; theta drives P/L)")
            else:
                direction = "up" if move_val > 0 else "down"
                move_hint = (
                    f"Projecting {abs(move_val):.2f} {direction} "
                    f"(delta-neutral; theta drives P/L)"
                )
        else:
            if move_val > 0:
                move_hint = (f"Projecting +${move_val:.2f} underlying move "
                             f"(bullish)")
            elif move_val < 0:
                move_hint = (f"Projecting \u2212${abs(move_val):.2f} "
                             f"underlying move (bearish)")
            else:
                move_hint = "Static: no projected move"

        thead = _render_thead(move_val, strat, sort_col, sort_dir)

        if not loaded:
            count_style = {"fontWeight": "800", "fontSize": "1.4rem",
                           "color": "#888", "textAlign": "right",
                           "fontFamily": "'Consolas', monospace",
                           "lineHeight": "1.1"}
            empty_children = [
                html.Div("Load an options chain in Step 1 to begin.",
                         style={"fontSize": "0.95rem", "color": "#888",
                                "fontWeight": "600", "marginBottom": "6px"}),
                html.Div("All spreads will be derived from the strikes and "
                         "live bid/ask quotes returned by Alpaca.",
                         style={"fontSize": "0.78rem", "color": "#666"}),
            ]
            status_pill = html.Span("AWAITING CHAIN", style=_AWAITING_PILL_STYLE)
            source = _make_source_display(False)
            return (thead, [], empty_children, rr_text, debit_cap_text,
                    "0 / 0", count_style, status_pill, source, move_hint,
                    "\u2014", delta_hint,
                    rr_panel_class, rr_toggle_label, rr_toggle_style, [])

        all_candidates = _build_spreads(filtered_rows, strat, spot=spot_f)

        # RR filter applies the same way for debit & credit (RR = max_profit / max_loss),
        # so we compare net (debit) for debit kinds and use the equivalent
        # max_loss-based threshold for credit kinds.  When the toggle is
        # OFF, the filter is bypassed entirely.
        if not rr_on:
            passing: list[dict] = list(all_candidates)
        else:
            passing = []
            for c in all_candidates:
                if c["kind"] == "debit":
                    if c["net"] <= c["width"] / (1 + rr) + 1e-9:
                        passing.append(c)
                else:
                    # Credit: max_profit / max_loss >= rr  ⇒  max_loss <= max_profit / rr
                    if c["max_loss"] > 0 and c["max_profit"] / c["max_loss"] >= rr - 1e-9:
                        passing.append(c)

        # Net Delta range filter — applied AFTER the RR filter so the
        # candidate count reflects the user's full preference set.
        # Candidates without Greek data are dropped only when the filter
        # is active; otherwise we keep them (Est. PnL just shows '—').
        passing_pre_delta = passing
        if delta_filter_active:
            passing = [
                c for c in passing
                if c.get("net_delta") is not None
                and d_min - 1e-9 <= c["net_delta"] <= d_max + 1e-9
            ]

        # Compute Est. PnL + ROI for every passing candidate.
        # Formula:  Expected Profit = net_delta * move * 100
        #   The user-typed Move ($) is the LITERAL signed underlying move
        #   (+ = up, - = down).  The strategy's own net_delta sign carries
        #   the directional P/L correctly (e.g. Bear Put has Δ < 0 so a
        #   negative move yields a positive PnL automatically).
        # ROI %: est_pnl ÷ capital-at-risk-per-contract.  Capital-at-risk is
        # net_debit*100 for debit spreads, max_loss*100 for credit spreads.
        # The two ×100 factors cancel, so we just divide by net (debit) or
        # max_loss (credit) directly.
        for c in passing:
            nd = c.get("net_delta")
            if nd is None:
                c["est_pnl"] = None
                c["roi_pct"] = None
                continue
            est_pnl = float(nd) * (move_val * move_mult) * 100
            cap_at_risk = c["net"] if c["kind"] == "debit" else c["max_loss"]
            roi_pct = (est_pnl / cap_at_risk) if cap_at_risk > 0 else 0.0
            c["est_pnl"] = round(est_pnl, 2)
            c["roi_pct"] = round(roi_pct, 2)

        # Sort according to the user-selected column / direction.
        passing = _sort_candidates(passing, sort_col, sort_dir)

        # Diagnostic: how many usable legs of the right type(s) exist
        # AFTER the moneyness filter (these are the legs the spread
        # builder actually saw).
        n_calls = sum(1 for r in filtered_rows
                      if str(r.get("type") or "").upper() == "CALL")
        n_puts = sum(1 for r in filtered_rows
                     if str(r.get("type") or "").upper() == "PUT")
        if strat == "iron_condor":
            n_legs_chain = n_calls + n_puts
            strat_label = "iron-condor"
        elif strat in ("bull_call", "bear_call"):
            n_legs_chain = n_calls
            strat_label = "call"
        else:
            n_legs_chain = n_puts
            strat_label = "put"

        rows = _render_spread_rows(passing)
        empty_children: list = []
        if not passing:
            if not money_sel or not filtered_rows:
                # Moneyness filter eliminated everything.
                if not money_sel:
                    msg = "No moneyness buckets selected."
                    sub = ("Enable ITM, ATM, or OTM in the Risk Engine "
                           "to allow legs into the spread builder.")
                else:
                    enabled = ", ".join(sorted(money_sel))
                    msg = (f"No legs in the loaded chain match the "
                           f"current moneyness filter ({enabled}).")
                    sub = ("Enable additional buckets above or widen the "
                           "ATM tolerance.")
                empty_children = [
                    html.Div(msg,
                             style={"fontSize": "0.95rem", "color": "#888",
                                    "fontWeight": "600", "marginBottom": "6px"}),
                    html.Div(sub,
                             style={"fontSize": "0.78rem", "color": "#666"}),
                ]
            elif not all_candidates:
                if strat == "iron_condor" and spot_f <= 0:
                    msg = ("Iron Condor needs a spot price — load the chain "
                           "with the underlying symbol so OTM strikes can "
                           "be picked.")
                else:
                    msg = (f"No usable {strat_label} legs in the filtered "
                           f"chain to build a {meta['label']}.")
                empty_children = [
                    html.Div(msg,
                             style={"fontSize": "0.95rem", "color": "#888",
                                    "fontWeight": "600", "marginBottom": "6px"}),
                    html.Div("Try widening the moneyness filter, the strike "
                             "range (Strikes +/-), or switching strategy.",
                             style={"fontSize": "0.78rem", "color": "#666"}),
                ]
            elif delta_filter_active and passing_pre_delta:
                # RR was satisfied but the Net Δ range filter knocked
                # everything out — distinct, more actionable message.
                sign_min = "+" if d_min >= 0 else "\u2212"
                sign_max = "+" if d_max >= 0 else "\u2212"
                empty_children = [
                    html.Div(
                        f"No spreads with Net \u0394 \u2208 "
                        f"[{sign_min}{abs(d_min):.2f}, "
                        f"{sign_max}{abs(d_max):.2f}].",
                        style={"fontSize": "0.95rem", "color": "#888",
                               "fontWeight": "600", "marginBottom": "6px"}),
                    html.Div(f"{len(passing_pre_delta)} spread(s) passed RR "
                             "but failed the Δ range — widen the Min/Max "
                             "above to bring them back.",
                             style={"fontSize": "0.78rem", "color": "#666"}),
                ]
            else:
                empty_children = [
                    html.Div(f"No spreads pass RR \u2265 1:{rr:.1f}.",
                             style={"fontSize": "0.95rem", "color": "#888",
                                    "fontWeight": "600", "marginBottom": "6px"}),
                    html.Div(f"{len(all_candidates)} candidate(s) exist — "
                             "lower the slider to widen the search.",
                             style={"fontSize": "0.78rem", "color": "#666"}),
                ]

        count_text = f"{len(passing)} / {len(all_candidates)}"
        count_color = _green if passing else "#888"
        count_style = {"fontWeight": "800", "fontSize": "1.4rem",
                       "color": count_color, "textAlign": "right",
                       "fontFamily": "'Consolas', monospace",
                       "lineHeight": "1.1"}

        status_pill = html.Span(f"LIVE \u2022 {len(chain_rows)} contracts",
                                style=_LIVE_PILL_STYLE)
        source = _make_source_display(
            True, ticker or "—", expiration or "—",
            spot_f, len(chain_rows), n_legs_chain, strat_label,
        )

        return (thead, rows, empty_children, rr_text, debit_cap_text,
                count_text, count_style, status_pill, source, move_hint,
                money_count_text, delta_hint,
                rr_panel_class, rr_toggle_label, rr_toggle_style, passing)

    # ----- Sortable column headers -------------------------------------
    @app.callback(
        Output("risk-sort-store", "data"),
        Input({"type": "risk-sort-btn", "col": ALL}, "n_clicks"),
        State("risk-sort-store", "data"),
        prevent_initial_call=True,
    )
    def update_risk_sort(n_clicks_list, current):
        if not n_clicks_list or not any(n_clicks_list):
            return no_update
        ctx = callback_context
        if not ctx.triggered_id or not isinstance(ctx.triggered_id, dict):
            return no_update
        col = ctx.triggered_id.get("col")
        current = current or {"col": "est_pnl", "dir": "desc"}
        if current.get("col") == col:
            new_dir = "asc" if current.get("dir") == "desc" else "desc"
        else:
            # Strikes / Width default to ascending; everything else desc.
            new_dir = "asc" if col in ("strikes", "width") else "desc"
        return {"col": col, "dir": new_dir}

    # ----- Helpers shared by execute_mleg + qty live-update -------------
    #
    # `_render_execute_totals` builds the cyan-tinted "scaled totals"
    # readout in the modal — Total Cost / Max Reward / Max Risk all
    # multiplied by the user-selected contract quantity.  Called on
    # modal open (qty=1 default) and on every qty change.
    def _money(v: float) -> str:
        # Compact currency formatter ($1,250 / -$3,750 / +$120)
        sign = "-" if v < 0 else ""
        return f"{sign}${abs(v):,.0f}" if abs(v) >= 100 else f"{sign}${abs(v):,.2f}"

    def _render_execute_totals(spread: dict, qty: int):
        try:
            q = max(1, int(qty))
        except (TypeError, ValueError):
            q = 1
        kind = spread.get("kind", "debit")
        net = float(spread.get("net") or 0)
        max_p = float(spread.get("max_profit") or 0)
        max_l = float(spread.get("max_loss") or 0)
        # × 100 because every option contract = 100 shares
        total_net   = net   * q * 100
        total_prof  = max_p * q * 100
        total_loss  = max_l * q * 100
        if kind == "credit":
            primary_label = "Credit Collected"
            primary_value = f"+{_money(total_net)}"
            primary_color = _green
        else:
            primary_label = "Total Cost"
            primary_value = _money(total_net)
            primary_color = "#ffa502"

        per_contract = (f"({_money(net*100)} \u00d7 {q} "
                        f"{'contract' if q == 1 else 'contracts'})")

        return [
            html.Div([
                html.Span(f"{primary_label}: ",
                          style={"color": "#888", "marginRight": "4px"}),
                html.Span(primary_value,
                          style={"color": primary_color, "fontWeight": "800",
                                 "fontSize": "1.0rem"}),
                html.Span(f"   {per_contract}",
                          style={"color": "#666", "fontSize": "0.72rem",
                                 "fontWeight": "500", "marginLeft": "6px"}),
            ]),
            html.Div([
                html.Span("Max Reward: ", style={"color": "#888"}),
                html.Span(f"+{_money(total_prof)}",
                          style={"color": _green, "fontWeight": "800",
                                 "marginRight": "16px"}),
                html.Span("Max Risk: ", style={"color": "#888"}),
                html.Span(f"-{_money(total_loss)}",
                          style={"color": _red, "fontWeight": "800"}),
            ]),
        ]

    # ----- Execute (mleg) button → build payload & open confirm modal ----
    @app.callback(
        [Output("risk-execute-modal", "is_open", allow_duplicate=True),
         Output("risk-execute-summary", "children"),
         Output("risk-execute-json", "children"),
         Output("risk-execute-env-banner", "children"),
         Output("risk-execute-env-banner", "style"),
         Output("risk-execute-submit", "children"),
         Output("risk-execute-submit", "color"),
         Output("risk-execute-payload", "data"),
         Output("risk-execute-qty", "value"),
         Output("risk-execute-totals", "children")],
        Input({"type": "mleg-exec", "index": ALL}, "n_clicks"),
        [State("risk-candidates-store", "data"),
         State("opt-symbol", "value"),
         State("opt-exp-date", "value"),
         State("trade-env-store", "data")],
        prevent_initial_call=True,
    )
    def execute_mleg(n_clicks_list, candidates, ticker, expiration, env):
        no_outs = (no_update,) * 10
        if not n_clicks_list or not any(n_clicks_list):
            return no_outs

        ctx = callback_context
        if not ctx.triggered_id or not isinstance(ctx.triggered_id, dict):
            return no_outs

        idx = ctx.triggered_id.get("index")
        candidates = candidates or []
        if idx is None or idx >= len(candidates):
            return no_outs

        spread = candidates[idx]
        sym = (ticker or "").strip().upper() or "—"
        exp = expiration or "—"
        kind = spread.get("kind", "debit")
        n_legs = spread.get("n_legs", 2)
        legs_list = spread.get("legs") or []
        strat_color = _STRAT_HEADER_COLOR.get(spread["strategy"], _cyan)
        paper = env == "paper"

        payload = {
            "symbol": sym,
            "qty": 1,
            "type": "limit",
            "time_in_force": "day",
            "order_class": "mleg",
            "limit_price": float(spread["net"]),
            "legs": [
                {"symbol": l["symbol"], "side": l["side"], "ratio_qty": 1,
                 "position_intent": l["position_intent"]}
                for l in legs_list
            ],
            # Internal-only context — the helper strips this before send.
            "_env": "paper" if paper else "live",
            "_kind": kind,
        }
        payload_json = json.dumps(
            {k: v for k, v in payload.items() if not k.startswith("_")},
            indent=2,
        )

        net_label = "Net Credit" if kind == "credit" else "Net Debit"
        net_color = _green if kind == "credit" else "#ffa502"
        net_value = f"+${spread['net']:.2f}" if kind == "credit" else f"${spread['net']:.2f}"

        summary = html.Div([
            html.Div([
                html.Span(spread["strategy"].upper(),
                          style={"fontWeight": "800", "letterSpacing": "1.5px",
                                 "fontSize": "0.85rem",
                                 "color": strat_color, "marginRight": "10px"}),
                html.Span(f"({n_legs} legs \u2022 {kind})",
                          style={"color": "#888", "fontSize": "0.72rem",
                                 "letterSpacing": "1px",
                                 "textTransform": "uppercase",
                                 "marginRight": "12px"}),
                html.Span(f"{sym} {spread['strikes_label']}",
                          style={"fontWeight": "700", "color": "#fff",
                                 "fontFamily": "'Consolas', monospace",
                                 "fontSize": "1.0rem"}),
                html.Span(f" \u2022 exp {exp}",
                          style={"color": "#888", "fontSize": "0.82rem",
                                 "marginLeft": "8px"}),
            ]),
            html.Div([
                html.Span(f"{net_label}: ", style={"color": "#888"}),
                html.Span(net_value,
                          style={"color": net_color, "fontWeight": "700",
                                 "fontFamily": "'Consolas', monospace",
                                 "marginRight": "16px"}),
                html.Span("Max Profit: ", style={"color": "#888"}),
                html.Span(f"+${spread['max_profit']:.2f}",
                          style={"color": _green, "fontWeight": "700",
                                 "fontFamily": "'Consolas', monospace",
                                 "marginRight": "16px"}),
                html.Span("Max Loss: ", style={"color": "#888"}),
                html.Span(f"-${spread['max_loss']:.2f}",
                          style={"color": _red, "fontWeight": "700",
                                 "fontFamily": "'Consolas', monospace",
                                 "marginRight": "16px"}),
                html.Span("RR: ", style={"color": "#888"}),
                html.Span(f"1 : {spread['target_rr']:.2f}",
                          style={"color": _cyan, "fontWeight": "700",
                                 "fontFamily": "'Consolas', monospace"}),
            ], style={"marginTop": "6px", "fontSize": "0.85rem"}),
        ])

        if paper:
            banner_children = [
                html.Span("PAPER ", style={"color": _green, "marginRight": "6px"}),
                html.Span("Submitting will place a real order on your "
                          "Alpaca paper account.",
                          style={"color": "#d0d0d0", "fontWeight": "500"}),
            ]
            banner_style = {"marginBottom": "10px", "padding": "8px 12px",
                            "borderRadius": "5px", "fontSize": "0.82rem",
                            "fontWeight": "700",
                            "backgroundColor": "rgba(0,212,126,0.10)",
                            "border": f"1px solid {_green}"}
            submit_label = "SUBMIT TO PAPER"
            submit_color = "success"
        else:
            banner_children = [
                html.Span("\u26a0 LIVE ", style={"color": _red, "marginRight": "6px"}),
                html.Span("Real money. This will place a binding order on "
                          "your live Alpaca account.",
                          style={"color": "#fff", "fontWeight": "600"}),
            ]
            banner_style = {"marginBottom": "10px", "padding": "8px 12px",
                            "borderRadius": "5px", "fontSize": "0.82rem",
                            "fontWeight": "700",
                            "backgroundColor": "rgba(255,71,87,0.12)",
                            "border": f"1px solid {_red}"}
            submit_label = "SUBMIT \u2014 LIVE MONEY"
            submit_color = "danger"

        totals_children = _render_execute_totals(spread, qty=1)
        return (True, summary, payload_json, banner_children, banner_style,
                submit_label, submit_color, payload, 1, totals_children)

    # ----- Live qty update → re-render JSON preview + scaled totals -----
    #
    # The user can dial the contract qty up or down BEFORE submitting.
    # We update the stored payload (so submit_risk_order picks up the
    # new value), regenerate the JSON preview, and rescale the
    # cost/reward/risk readout — all without re-opening the modal.
    @app.callback(
        [Output("risk-execute-payload", "data", allow_duplicate=True),
         Output("risk-execute-json", "children", allow_duplicate=True),
         Output("risk-execute-totals", "children", allow_duplicate=True)],
        Input("risk-execute-qty", "value"),
        [State("risk-execute-payload", "data"),
         State("risk-candidates-store", "data")],
        prevent_initial_call=True,
    )
    def update_qty_payload(qty_value, payload, candidates):
        if not payload:
            return no_update, no_update, no_update
        try:
            q = max(1, int(qty_value)) if qty_value is not None else 1
        except (TypeError, ValueError):
            q = 1

        new_payload = dict(payload)
        new_payload["qty"] = q

        payload_json = json.dumps(
            {k: v for k, v in new_payload.items() if not k.startswith("_")},
            indent=2,
        )

        # Reconstruct the spread dict needed for _render_execute_totals
        # by matching the stored payload's legs against the candidate
        # currently associated with this submit flow.  The simplest
        # path: derive net/max_profit/max_loss from the payload itself
        # plus the candidates store.  We try to find the matching
        # candidate by leg-symbol set (order-independent).
        cand = None
        try:
            payload_syms = {l["symbol"] for l in (payload.get("legs") or [])}
            for c in (candidates or []):
                cand_syms = {l["symbol"] for l in (c.get("legs") or [])}
                if cand_syms == payload_syms:
                    cand = c
                    break
        except Exception:
            cand = None

        if cand is None:
            # Fallback: synthesize a minimal spread dict from the payload
            # so totals can still be rendered (no max_profit / max_loss).
            cand = {
                "kind": payload.get("_kind", "debit"),
                "net": payload.get("limit_price", 0),
                "max_profit": 0,
                "max_loss": payload.get("limit_price", 0),
            }

        totals_children = _render_execute_totals(cand, qty=q)
        return new_payload, payload_json, totals_children

    # ----- Submit confirmed mleg order to Alpaca ------------------------
    @app.callback(
        [Output("risk-execute-modal", "is_open", allow_duplicate=True),
         Output("risk-execute-toast", "is_open", allow_duplicate=True),
         Output("risk-execute-toast", "header", allow_duplicate=True),
         Output("risk-execute-toast", "icon", allow_duplicate=True),
         Output("risk-execute-toast", "children", allow_duplicate=True),
         Output("risk-execute-toast", "style", allow_duplicate=True),
         Output("trade-log", "children", allow_duplicate=True)],
        Input("risk-execute-submit", "n_clicks"),
        [State("risk-execute-payload", "data"),
         State("trade-env-store", "data"),
         State("trade-log-store", "data")],
        prevent_initial_call=True,
    )
    def submit_risk_order(n_clicks, payload, env, log_lines):
        no_outs = (no_update,) * 7
        if not n_clicks or not payload:
            return no_outs

        paper = env == "paper"
        env_label = "PAPER" if paper else "LIVE"
        log_lines = list(log_lines or [])

        legs = payload.get("legs") or []
        try:
            limit_px = float(payload.get("limit_price") or 0)
            qty = int(payload.get("qty") or 1)
        except (TypeError, ValueError):
            limit_px, qty = 0.0, 1

        result = _execute_mleg(
            legs=legs,
            limit_price=limit_px,
            qty=qty,
            tif="DAY",
            paper=paper,
        )

        log_lines.append(
            _log_entry(f"[mleg/{env_label}] {result.get('message', '?')}")
        )
        log_text = "\n".join(log_lines[-20:])

        legs_summary = "\n".join(
            f"  {l.get('side', '?').upper():<4} {l.get('symbol', '?')}"
            f"  ({l.get('position_intent', '?')})"
            for l in legs
        )

        ok = bool(result.get("ok"))
        if ok:
            toast_header = f"Order Accepted \u2022 {env_label}"
            toast_icon = "success"
            toast_body = (
                f"id: {result.get('order_id') or '?'}\n"
                f"status: {result.get('status') or '?'}\n"
                f"limit_price: ${limit_px:.2f}   qty: {qty}   "
                f"legs: {len(legs)}\n{legs_summary}"
            )
            border = _green
        else:
            toast_header = f"Order FAILED \u2022 {env_label}"
            toast_icon = "danger"
            toast_body = result.get("message") or "Unknown error"
            border = _red

        toast_style = {"position": "fixed", "top": "80px", "right": "24px",
                       "zIndex": 9999, "minWidth": "340px",
                       "backgroundColor": _card_bg,
                       "border": f"1px solid {border}",
                       "color": "#e0e0e0"}

        return (False, True, toast_header, toast_icon, toast_body,
                toast_style, log_text)

    # ----- Close payload modal (Cancel button) --------------------------
    @app.callback(
        Output("risk-execute-modal", "is_open"),
        Input("risk-execute-close", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_risk_modal(_n):
        return False

    # =====================================================================
    # ALERTS TAB CALLBACKS
    # =====================================================================
    from app.alerts import (
        load_alerts, create_alert, delete_alert, check_alerts,
    )

    def _alert_log(msg: str) -> str:
        return f"[{_dt.now().strftime('%H:%M:%S')}] {msg}"

    def _alerts_to_table(alerts: list[dict]) -> list[dict]:
        """Convert MongoDB alert documents to table-friendly dicts."""
        rows = []
        for a in alerts:
            created = a.get("created_at")
            if created and hasattr(created, "strftime"):
                created_str = created.strftime("%Y-%m-%d %H:%M")
            else:
                created_str = str(created or "")
            rows.append({
                "alert_id": a.get("alert_id", ""),
                "symbol": a.get("symbol", ""),
                "direction": a.get("direction", ""),
                "target_price": a.get("target_price"),
                "status": a.get("status", ""),
                "triggered_price": a.get("triggered_price"),
                "note": a.get("note", ""),
                "created_at": created_str,
            })
        return rows

    # ----- Alert check interval control -----
    @app.callback(
        [Output("alert-check-interval-timer", "interval"),
         Output("alert-check-interval-timer", "disabled"),
         Output("alert-monitor-badge", "children"),
         Output("alert-monitor-badge", "style")],
        Input("alert-check-interval", "value"),
    )
    def set_alert_interval(val):
        off_style = {"fontWeight": "700", "fontSize": "0.9rem",
                     "padding": "5px 14px", "borderRadius": "6px",
                     "display": "inline-block",
                     "backgroundColor": "rgba(255,255,255,0.06)",
                     "color": "#888", "border": "1px solid rgba(255,255,255,0.1)"}
        on_style = {"fontWeight": "700", "fontSize": "0.9rem",
                    "padding": "5px 14px", "borderRadius": "6px",
                    "display": "inline-block",
                    "backgroundColor": "rgba(0,212,126,0.12)",
                    "color": _green, "border": f"1px solid {_green}"}

        if not val or val == "Off":
            return 1_000_000, True, "MONITORING OFF", off_style

        mapping = {"30s": 30, "1m": 60, "5m": 300, "15m": 900}
        secs = mapping.get(val, 60)
        return secs * 1000, False, f"MONITORING ({val})", on_style

    # ----- Load alerts on tab open / after changes -----
    @app.callback(
        [Output("alert-table", "data"),
         Output("alert-active-count", "children"),
         Output("alert-triggered-count", "children")],
        Input("alert-store", "data"),
    )
    def refresh_alert_table(store_trigger):
        alerts = load_alerts()
        rows = _alerts_to_table(alerts)
        active = sum(1 for a in alerts if a.get("status") == "active")
        triggered = sum(1 for a in alerts if a.get("status") == "triggered")
        return rows, str(active), str(triggered)

    # ----- Add alert -----
    @app.callback(
        [Output("alert-store", "data", allow_duplicate=True),
         Output("alert-symbol", "value"),
         Output("alert-target-price", "value"),
         Output("alert-note", "value"),
         Output("alert-log", "children", allow_duplicate=True)],
        Input("alert-add-btn", "n_clicks"),
        [State("alert-symbol", "value"),
         State("alert-direction", "value"),
         State("alert-target-price", "value"),
         State("alert-note", "value"),
         State("alert-log-store", "data")],
        prevent_initial_call=True,
    )
    def add_alert(n_clicks, symbol, direction, target_price, note, log_lines):
        if not n_clicks or not symbol or not target_price:
            return no_update, no_update, no_update, no_update, no_update
        log_lines = list(log_lines or [])
        try:
            alert = create_alert(
                symbol=symbol,
                target_price=float(target_price),
                direction=direction,
                note=note or "",
            )
            log_lines.append(_alert_log(
                f"Added: {alert['symbol']} {direction} ${float(target_price):.2f}"))
        except Exception as exc:
            log_lines.append(_alert_log(f"Error adding alert: {exc}"))
            return no_update, no_update, no_update, no_update, "\n".join(log_lines[-30:])

        return (
            log_lines,
            "",
            None,
            "",
            "\n".join(log_lines[-30:]),
        )

    # ----- Delete selected alerts -----
    @app.callback(
        [Output("alert-store", "data", allow_duplicate=True),
         Output("alert-log", "children", allow_duplicate=True)],
        Input("alert-delete-btn", "n_clicks"),
        [State("alert-table", "selected_rows"),
         State("alert-table", "data"),
         State("alert-log-store", "data")],
        prevent_initial_call=True,
    )
    def delete_selected_alerts(n_clicks, selected_rows, data, log_lines):
        if not n_clicks or not selected_rows or not data:
            return no_update, no_update
        log_lines = list(log_lines or [])
        for idx in selected_rows:
            if idx < len(data):
                aid = data[idx].get("alert_id")
                sym = data[idx].get("symbol", "")
                if aid:
                    delete_alert(aid)
                    log_lines.append(_alert_log(f"Deleted: {sym} ({aid})"))
        return log_lines, "\n".join(log_lines[-30:])

    # ----- Check alerts (manual + interval) -----
    @app.callback(
        [Output("alert-store", "data"),
         Output("alert-log", "children"),
         Output("alert-last-check", "children")],
        [Input("alert-check-now-btn", "n_clicks"),
         Input("alert-check-interval-timer", "n_intervals")],
        State("alert-log-store", "data"),
        prevent_initial_call=True,
    )
    def run_alert_check(n_clicks, n_intervals, log_lines):
        log_lines = list(log_lines or [])
        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        is_manual = "alert-check-now-btn" in triggered_id

        try:
            triggered_msgs = check_alerts()
            if triggered_msgs:
                for m in triggered_msgs:
                    log_lines.append(_alert_log(f"TRIGGERED: {m}"))
            elif is_manual:
                log_lines.append(_alert_log("Check complete — no alerts triggered"))
        except Exception as exc:
            log_lines.append(_alert_log(f"Check error: {exc}"))

        last_check = f"Last check: {_dt.now().strftime('%H:%M:%S')}"
        return log_lines, "\n".join(log_lines[-30:]), last_check

    # =====================================================================
    # AI CHAT TAB CALLBACKS
    # =====================================================================
    from app.ai_data import fetch_sp500_movers, fetch_insider_data, ask_gemini

    # ----- Toggle data preview collapse -----
    @app.callback(
        Output("ai-preview-collapse", "is_open"),
        Input("ai-toggle-preview-btn", "n_clicks"),
        State("ai-preview-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_preview(n, is_open):
        return not is_open

    # ----- Load data -----
    @app.callback(
        [Output("ai-context-store", "data"),
         Output("ai-data-loaded", "data"),
         Output("ai-status", "children"),
         Output("ai-data-preview", "children"),
         Output("ai-history-store", "data", allow_duplicate=True),
         Output("ai-chat-messages", "children", allow_duplicate=True),
         Output("ai-loading-target", "children")],
        Input("ai-load-data-btn", "n_clicks"),
        State("ai-data-sources", "value"),
        prevent_initial_call=True,
    )
    def load_ai_data(n_clicks, sources):
        if not n_clicks:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update

        sources = sources or []
        context_parts = []
        preview_parts = []
        counts = []

        context_parts.append(
            "You are an expert quantitative swing trading assistant. "
            "Below is real-time scraped data representing today's market action and recent insider trading.\n"
            "Always cross-reference the data when answering. If a user asks for a recommendation, "
            "look for stocks that have CONVERGENCE (e.g., strong momentum/gaps AND insider buying).\n"
            "Format your answers with clear sections and bullet points. Be concise but thorough.\n"
        )

        if "sp500" in sources:
            try:
                market_csv, n_movers = fetch_sp500_movers()
                context_parts.append(
                    f"=== S&P 500 MOVERS (Gappers, RVOL Spikes, Weekly/Monthly Movers) ===\n{market_csv}"
                )
                preview_parts.append(f"S&P 500 Movers: {n_movers} stocks with notable action")
                counts.append(f"{n_movers} S&P movers")
            except Exception as e:
                preview_parts.append(f"S&P 500: Error — {e}")

        if "insider_buys" in sources:
            try:
                buys_csv, n_buys = fetch_insider_data("cluster_buys")
                context_parts.append(
                    f"=== INSIDER CLUSTER BUYS (> $50k) ===\n{buys_csv if buys_csv else 'No significant buys today.'}"
                )
                preview_parts.append(f"Insider Buys: {n_buys} cluster buy transactions")
                counts.append(f"{n_buys} insider buys")
            except Exception as e:
                preview_parts.append(f"Insider Buys: Error — {e}")

        if "insider_sales" in sources:
            try:
                sales_csv, n_sales = fetch_insider_data("top_sales")
                context_parts.append(
                    f"=== TOP INSIDER SALES (> $500k) ===\n{sales_csv if sales_csv else 'No significant sales today.'}"
                )
                preview_parts.append(f"Insider Sales: {n_sales} large sale transactions")
                counts.append(f"{n_sales} insider sales")
            except Exception as e:
                preview_parts.append(f"Insider Sales: Error — {e}")

        if not sources:
            return (
                "", False,
                "No data sources selected. Check at least one option above.",
                "No data loaded.",
                [], [html.Div("Select data sources and click Load Data.", className="ai-msg ai-msg-system")],
                "",
            )

        context = "\n\n".join(context_parts)
        status = f"Data loaded: {', '.join(counts)}  •  Ready to chat!"
        preview = "\n".join(preview_parts)
        welcome = html.Div([
            html.Div("AI context loaded with live market data.", className="ai-msg ai-msg-system"),
            html.Div(
                f"I've ingested {', '.join(counts)}. Ask me anything about today's market action, "
                "insider trading signals, momentum plays, or convergence setups.",
                className="ai-msg ai-msg-ai",
            ),
        ])

        return context, True, status, preview, [], welcome.children, ""

    # ----- Clear chat -----
    @app.callback(
        [Output("ai-history-store", "data", allow_duplicate=True),
         Output("ai-chat-messages", "children", allow_duplicate=True)],
        Input("ai-clear-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_chat(n):
        if not n:
            return no_update, no_update
        return [], [html.Div("Chat cleared. Send a message to continue.", className="ai-msg ai-msg-system")]

    # ----- Send message (button click OR Enter key) -----
    @app.callback(
        [Output("ai-chat-messages", "children"),
         Output("ai-history-store", "data"),
         Output("ai-user-input", "value")],
        [Input("ai-send-btn", "n_clicks"),
         Input("ai-user-input", "n_submit")],
        [State("ai-user-input", "value"),
         State("ai-context-store", "data"),
         State("ai-history-store", "data"),
         State("ai-chat-messages", "children"),
         State("ai-data-loaded", "data")],
        prevent_initial_call=True,
    )
    def send_message(n_clicks, n_submit, user_text, context, history, messages, data_loaded):
        if not user_text or not user_text.strip():
            return no_update, no_update, no_update

        user_text = user_text.strip()
        messages = list(messages or [])
        history = list(history or [])

        messages.append(html.Div(user_text, className="ai-msg ai-msg-user"))

        if not data_loaded or not context:
            messages.append(
                html.Div("Please load data first by clicking 'Load Data & Start'.",
                         className="ai-msg ai-msg-system")
            )
            return messages, history, ""

        history.append({"role": "user", "parts": [user_text]})

        try:
            reply = ask_gemini(context, history)
            history.append({"role": "model", "parts": [reply]})
            messages.append(html.Div(
                dcc.Markdown(reply, style={"margin": 0, "fontSize": "0.85rem",
                                           "lineHeight": "1.6", "color": "#d0d0d0"}),
                className="ai-msg ai-msg-ai",
            ))
        except Exception as e:
            messages.append(html.Div(f"Error: {e}", className="ai-msg ai-msg-error"))
            if history and history[-1].get("role") == "user":
                history.pop()

        return messages, history, ""

    # =====================================================================
    # VOLUME AI TAB CALLBACKS  (Gemini 2.5 Pro squeeze analyst)
    # =====================================================================
    from app.ai_data import (
        ask_gemini_volume as _ask_vol_ai,
        build_volume_context as _build_vol_ctx,
    )

    # ----- Toggle preview collapse -----
    @app.callback(
        Output("vai-preview-collapse", "is_open"),
        Input("vai-toggle-preview-btn", "n_clicks"),
        State("vai-preview-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def vai_toggle_preview(n, is_open):
        return not is_open

    def _vai_filter_rows(rows, t_from, t_to):
        """Apply optional From/To PT-time filters to a rows list."""
        if not rows:
            return rows
        last_iso = rows[-1].get("ts_iso") or ""
        start_iso = _parse_pt(t_from, last_iso) if t_from else None
        end_iso = _parse_pt(t_to, last_iso) if t_to else None
        if start_iso and end_iso and start_iso > end_iso:
            start_iso, end_iso = end_iso, start_iso
        if not (start_iso or end_iso):
            return rows
        out = []
        for r in rows:
            iso = r.get("ts_iso") or ""
            if start_iso and iso < start_iso:
                continue
            if end_iso and iso > end_iso:
                continue
            out.append(r)
        return out

    def _vai_briefing(symbol, timeframe, lookback, n_rows, sessions):
        return html.Div([
            html.Div(
                f"Tape loaded: {symbol} \u2022 {timeframe} \u2022 "
                f"{n_rows} bars across {len(sessions)} session"
                f"{'s' if len(sessions) != 1 else ''}.",
                className="ai-msg ai-msg-system",
            ),
            html.Div(
                "I have the full bar tape in memory. Ask me to grade the "
                "session, classify the stage at a specific time, walk "
                "through the flush bar, or check the A+ checklist.",
                className="ai-msg ai-msg-ai",
            ),
        ])

    def _vai_table_count_label(symbol, timeframe, n_rows, sessions):
        return (f"{symbol} \u2022 {timeframe} \u2022 {n_rows} bars across "
                f"{len(sessions)} session"
                f"{'s' if len(sessions) != 1 else ''}")

    # ----- Load tape from controls -----
    @app.callback(
        [Output("vai-context-store", "data"),
         Output("vai-data-loaded", "data"),
         Output("vai-status", "children"),
         Output("vai-data-preview", "children"),
         Output("vai-history-store", "data", allow_duplicate=True),
         Output("vai-chat-messages", "children", allow_duplicate=True),
         Output("vai-table", "data"),
         Output("vai-table-count", "children"),
         Output("vai-loading-target", "children")],
        Input("vai-load-btn", "n_clicks"),
        [State("vai-symbol", "value"),
         State("vai-timeframe", "value"),
         State("vai-lookback", "value"),
         State("vai-from", "value"),
         State("vai-to", "value")],
        prevent_initial_call=True,
    )
    def vai_load_tape(n_clicks, symbol, timeframe, lookback, t_from, t_to):
        if not n_clicks:
            return (no_update,) * 9
        if not symbol or not symbol.strip():
            return (no_update, False,
                    "Enter a symbol and click Load Tape.",
                    no_update, no_update, no_update,
                    no_update, no_update, "")
        sym = symbol.strip().upper()
        tf = (timeframe or "5m").strip()
        try:
            days = int(lookback) if lookback else 1
        except (TypeError, ValueError):
            days = 1
        try:
            rows = _get_history(sym, timeframe=tf, lookback_days=days)
        except Exception as e:
            return ("", False,
                    f"Failed to load {sym}: {e}",
                    f"Error: {e}",
                    [], [html.Div(f"Failed to load tape: {e}",
                                   className="ai-msg ai-msg-error")],
                    [], "", "")
        if not rows:
            return ("", False,
                    f"No intraday data available for {sym}.",
                    "No bars returned.",
                    [], [html.Div(f"No bars available for {sym}.",
                                   className="ai-msg ai-msg-system")],
                    [], "", "")
        filtered = _vai_filter_rows(rows, t_from, t_to)
        if not filtered:
            return ("", False,
                    f"No bars in the selected window for {sym}.",
                    "Window filtered all bars out.",
                    [], [html.Div("No bars in the selected window.",
                                   className="ai-msg ai-msg-system")],
                    [], "", "")
        context, summary = _build_vol_ctx(sym, tf, days, filtered,
                                          t_from, t_to)
        sessions = sorted({r.get("session") for r in filtered})
        status = ("Tape ready  \u2022  " + summary +
                  "  \u2022  pick a model and ask a question.")
        count_label = _vai_table_count_label(sym, tf, len(filtered),
                                              sessions)
        return (context, True, status, context,
                [], _vai_briefing(sym, tf, days, len(filtered),
                                   sessions).children,
                filtered, count_label, "")

    # ----- Use tape that's currently loaded in the Volume History tab -----
    @app.callback(
        [Output("vai-context-store", "data", allow_duplicate=True),
         Output("vai-data-loaded", "data", allow_duplicate=True),
         Output("vai-status", "children", allow_duplicate=True),
         Output("vai-data-preview", "children", allow_duplicate=True),
         Output("vai-history-store", "data", allow_duplicate=True),
         Output("vai-chat-messages", "children", allow_duplicate=True),
         Output("vai-table", "data", allow_duplicate=True),
         Output("vai-table-count", "children", allow_duplicate=True),
         Output("vai-symbol", "value"),
         Output("vai-timeframe", "value"),
         Output("vai-lookback", "value"),
         Output("vai-from", "value"),
         Output("vai-to", "value"),
         Output("vai-loading-target", "children", allow_duplicate=True)],
        Input("vai-use-current-btn", "n_clicks"),
        [State("vol-hist-store", "data"),
         State("vol-hist-symbol", "value"),
         State("vol-hist-timeframe", "value"),
         State("vol-hist-lookback", "value"),
         State("vol-hist-from", "value"),
         State("vol-hist-to", "value")],
        prevent_initial_call=True,
    )
    def vai_use_current(n_clicks, rows, symbol, timeframe, lookback,
                          t_from, t_to):
        if not n_clicks:
            return (no_update,) * 14
        if not rows:
            return ("", False,
                    "Volume History tab has no tape loaded \u2014 load it "
                    "there first, or use the controls above.",
                    "No tape available from Volume History.",
                    [], [html.Div("Nothing to import \u2014 load a tape in "
                                   "the Volume History tab first.",
                                   className="ai-msg ai-msg-system")],
                    [], "",
                    no_update, no_update, no_update, no_update, no_update,
                    "")
        sym = (symbol or "").strip().upper() or "SYM"
        tf = (timeframe or "5m").strip()
        try:
            days = int(lookback) if lookback else 1
        except (TypeError, ValueError):
            days = 1
        filtered = _vai_filter_rows(rows, t_from, t_to)
        if not filtered:
            return ("", False,
                    f"No bars in the selected window for {sym}.",
                    "Window filtered all bars out.",
                    [], [html.Div("No bars in the selected window.",
                                   className="ai-msg ai-msg-system")],
                    [], "",
                    sym, tf, str(days), t_from or "", t_to or "", "")
        context, summary = _build_vol_ctx(sym, tf, days, filtered,
                                          t_from, t_to)
        sessions = sorted({r.get("session") for r in filtered})
        status = ("Imported from Volume History  \u2022  " + summary +
                  "  \u2022  pick a model and ask a question.")
        count_label = _vai_table_count_label(sym, tf, len(filtered),
                                              sessions)
        return (context, True, status, context,
                [], _vai_briefing(sym, tf, days, len(filtered),
                                   sessions).children,
                filtered, count_label,
                sym, tf, str(days), t_from or "", t_to or "", "")

    # ----- Clear chat / context -----
    @app.callback(
        [Output("vai-chat-messages", "children", allow_duplicate=True),
         Output("vai-history-store", "data", allow_duplicate=True)],
        Input("vai-clear-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def vai_clear(n):
        if not n:
            return no_update, no_update
        return ([html.Div("Chat cleared. Ask another question \u2014 "
                          "the loaded tape is still in context.",
                          className="ai-msg ai-msg-system")],
                [])

    # ----- Send message (button or Enter) -----
    @app.callback(
        [Output("vai-chat-messages", "children"),
         Output("vai-history-store", "data"),
         Output("vai-user-input", "value"),
         Output("vai-loading-target", "children", allow_duplicate=True)],
        [Input("vai-send-btn", "n_clicks"),
         Input("vai-user-input", "n_submit")],
        [State("vai-user-input", "value"),
         State("vai-context-store", "data"),
         State("vai-history-store", "data"),
         State("vai-chat-messages", "children"),
         State("vai-data-loaded", "data"),
         State("vai-model", "value")],
        prevent_initial_call=True,
    )
    def vai_send(n_clicks, n_submit, user_text, context, history,
                  messages, data_loaded, model_name):
        if not user_text or not user_text.strip():
            return no_update, no_update, no_update, no_update
        user_text = user_text.strip()
        messages = list(messages or [])
        history = list(history or [])
        messages.append(html.Div(user_text, className="ai-msg ai-msg-user"))

        if not data_loaded or not context:
            messages.append(html.Div(
                "Please load a tape first \u2014 use the controls above or "
                "click \u2018Use Current\u2019 to import the tape from the "
                "Volume History tab.",
                className="ai-msg ai-msg-system"))
            return messages, history, "", ""

        history.append({"role": "user", "parts": [user_text]})
        try:
            reply = _ask_vol_ai(context, history, model_name=model_name)
            history.append({"role": "model", "parts": [reply]})
            messages.append(html.Div([
                dcc.Markdown(reply, style={"margin": 0,
                                            "fontSize": "0.85rem",
                                            "lineHeight": "1.6",
                                            "color": "#d0d0d0"}),
                html.Div(f"\u2014 {model_name}",
                         style={"marginTop": "6px",
                                "fontSize": "0.68rem",
                                "color": "#666",
                                "fontStyle": "italic",
                                "textAlign": "right"}),
            ], className="ai-msg ai-msg-ai"))
        except Exception as e:
            messages.append(html.Div(f"Error: {e}",
                                      className="ai-msg ai-msg-error"))
            if history and history[-1].get("role") == "user":
                history.pop()
        return messages, history, "", ""

    # =====================================================================
    # VOLUME SCANNER TAB
    # =====================================================================

    @app.callback(
        Output("vol-symbols-input", "value"),
        Input("vol-preset", "value"),
        State("vol-symbols-input", "value"),
        prevent_initial_call=True,
    )
    def vol_apply_preset(preset, current):
        if preset == "MAG7":
            return ", ".join(MAG7_SYMBOLS)
        return current or ""

    @app.callback(
        [Output("vol-refresh-timer", "interval"),
         Output("vol-refresh-timer", "disabled")],
        Input("vol-refresh-interval", "value"),
    )
    def vol_set_timer(value):
        mapping = {"30s": 30_000, "1m": 60_000, "5m": 300_000}
        if value in mapping:
            return mapping[value], False
        return 1_000_000, True

    @app.callback(
        [Output("vol-spike-refresh-timer", "interval"),
         Output("vol-spike-refresh-timer", "disabled")],
        [Input("vol-spike-refresh-interval", "value"),
         Input("vol-spike-toggle", "value")],
    )
    def vol_set_spike_timer(value, toggle_on):
        mapping = {
            "1m": 60_000, "2m": 120_000, "5m": 300_000,
            "10m": 600_000, "15m": 900_000,
        }
        if not toggle_on or value not in mapping:
            return 1_000_000, True
        return mapping[value], False

    @app.callback(
        [Output("vol-hist-refresh-timer", "interval"),
         Output("vol-hist-refresh-timer", "disabled")],
        Input("vol-hist-refresh-interval", "value"),
    )
    def vol_set_hist_timer(value):
        mapping = {"30s": 30_000, "1m": 60_000, "2m": 120_000, "5m": 300_000}
        if value in mapping:
            return mapping[value], False
        return 1_000_000, True

    @app.callback(
        [Output("vol-data-store", "data"),
         Output("vol-spike-store", "data"),
         Output("vol-status-text", "children"),
         Output("vol-spike-status", "children")],
        [Input("vol-scan-btn", "n_clicks"),
         Input("vol-refresh-timer", "n_intervals"),
         Input("vol-spike-refresh-timer", "n_intervals"),
         Input("page-tab-volume", "style"),
         Input("vol-spike-toggle", "value")],
        [State("vol-symbols-input", "value"),
         State("vol-spike-z", "value"),
         State("vol-spike-lookback", "value"),
         State("vol-data-store", "data"),
         State("vol-spike-store", "data")],
    )
    def vol_run_scan(_clicks, _ticks, _spike_ticks, page_style, spike_on,
                      raw_text, spike_z, spike_lookback,
                      existing_session, existing_spikes):
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        ctx = callback_context
        is_visible = page_style and page_style.get("display") == "block"
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

        if "page-tab-volume" in triggered:
            if not is_visible or (existing_session and len(existing_session) > 0):
                return no_update, no_update, no_update, no_update

        if "vol-refresh-timer" in triggered and not is_visible:
            return no_update, no_update, no_update, no_update

        # Spike-only timer: refresh just the spike feed, don't touch the
        # session table. Skip when the tab is hidden or toggle is off.
        spike_only = "vol-spike-refresh-timer" in triggered
        if spike_only and (not is_visible or not spike_on):
            return no_update, no_update, no_update, no_update

        # Toggle change alone shouldn't force a fresh scan if we already
        # have results — the visibility callback handles showing the panel.
        if "vol-spike-toggle" in triggered and existing_session:
            if spike_on and existing_spikes:
                return no_update, no_update, no_update, no_update
            if not spike_on:
                return no_update, no_update, no_update, no_update

        symbols = [s.strip().upper() for s in (raw_text or "").replace(";", ",").split(",")
                   if s.strip()]
        if not symbols:
            symbols = list(MAG7_SYMBOLS)

        now_pt = _dt.now(ZoneInfo("America/Los_Angeles"))

        # ---- Spike-only refresh path ---------------------------------
        if spike_only:
            try:
                z_val = float(spike_z) if spike_z else 2.0
            except (TypeError, ValueError):
                z_val = 2.0
            today_only = (spike_lookback or "1d") == "1d"
            lookback_days = 1 if today_only else 5
            spikes = _scan_spikes(symbols, lookback_days=lookback_days,
                                   z_threshold=z_val,
                                   today_only=today_only)
            spike_status = (f"{len(spikes)} 5m spike(s) at "
                            f"{now_pt.strftime('%H:%M:%S')} PT "
                            f"\u2022 z \u2265 {z_val:.1f}")
            return no_update, spikes, no_update, spike_status

        # ---- Full scan (button / page-show / session timer / toggle) -
        rows = _scan_volume(symbols)
        n_abnormal = sum(1 for r in rows if r.get("signal") and (
            "ABNORMAL" in r["signal"] or "EXTREME" in r["signal"]))
        session_status = (f"Scanned {len(rows)} symbols at "
                          f"{now_pt.strftime('%H:%M:%S')} PT \u2022 "
                          f"{n_abnormal} abnormal")

        spikes: list = []
        spike_status = ""
        if spike_on:
            try:
                z_val = float(spike_z) if spike_z else 2.0
            except (TypeError, ValueError):
                z_val = 2.0
            today_only = (spike_lookback or "1d") == "1d"
            lookback_days = 1 if today_only else 5
            spikes = _scan_spikes(symbols, lookback_days=lookback_days,
                                   z_threshold=z_val,
                                   today_only=today_only)
            spike_status = (f"{len(spikes)} 5m spike(s) found "
                            f"(z \u2265 {z_val:.1f})")

        return rows, spikes, session_status, spike_status

    @app.callback(
        Output("vol-spike-card-wrapper", "style"),
        Input("vol-spike-toggle", "value"),
    )
    def vol_toggle_spike_panel(on):
        return {"display": "block"} if on else {"display": "none"}

    @app.callback(
        [Output("vol-spike-table", "data"),
         Output("vol-spike-count", "children")],
        Input("vol-spike-store", "data"),
    )
    def vol_render_spikes(rows):
        rows = rows or []
        if not rows:
            return [], ""
        n_buy = sum(1 for r in rows if "BUY" in (r.get("signal") or ""))
        n_sell = sum(1 for r in rows if "SELL" in (r.get("signal") or ""))
        return rows, f"\u2022 {len(rows)} bars  ({n_buy} \u2191 / {n_sell} \u2193)"

    @app.callback(
        Output("vol-table", "data"),
        Input("vol-data-store", "data"),
    )
    def vol_render_table(rows):
        return rows or []

    @app.callback(
        Output("vol-summary-cards", "children"),
        Input("vol-data-store", "data"),
    )
    def vol_render_cards(rows):
        if not rows:
            return [dbc.Col(html.P(
                "Click \u2018Scan Now\u2019 to detect abnormal session volume.",
                className="text-muted",
                style={"fontSize": "0.85rem", "marginBottom": 0}), width=12)]

        valid = [r for r in rows if r.get("rel_vol") is not None]
        if not valid:
            return [dbc.Col(html.P(
                "No intraday volume data available \u2014 markets may be closed.",
                className="text-muted",
                style={"fontSize": "0.85rem", "marginBottom": 0}), width=12)]

        n_abnormal = sum(1 for r in valid if r["rel_vol"] >= 1.5)
        top = max(valid, key=lambda r: r["rel_vol"])
        net = sum((r.get("net_delta") or 0) for r in valid)

        bull = [r for r in valid if (r.get("buy_share") or 50) >= 60]
        bear = [r for r in valid if (r.get("buy_share") or 50) <= 40]

        net_color = _green if net >= 0 else _red
        net_str = f"${net/1e6:+.1f}M"
        skew_main = f"{len(bull)} \u2191 / {len(bear)} \u2193"

        return [
            _card("ABNORMAL SIGNALS", f"{n_abnormal} / {len(valid)}",
                  "  rel-vol \u2265 1.5x", _cyan),
            _card("HIGHEST REL VOL", top["symbol"],
                  f"  {top['rel_vol']:.2f}x", _orange),
            _card("NET DELTA (\u03A3)", net_str,
                  "  buy \u2212 sell", net_color),
            _card("DIRECTIONAL SKEW", skew_main,
                  "  buying / selling", _cyan),
        ]

    # =====================================================================
    # MOVE INVESTIGATOR (Volume tab)
    # =====================================================================

    def _parse_pt(text: str | None, ref_iso: str | None) -> str | None:
        """Accept either a full datetime ('2026-04-30 07:20') or just a
        time-of-day ('07:20'); in the latter case use the date of the
        ref ISO timestamp from the timeline. Return ISO PT string or
        None if the input is empty/unparseable."""
        if not text or not str(text).strip():
            return None
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo
        s = str(text).strip()
        try:
            if " " in s or "T" in s:
                ts = pd.Timestamp(s)
            else:
                ref = pd.Timestamp(ref_iso) if ref_iso else _dt.now(
                    ZoneInfo("America/Los_Angeles"))
                hh, mm = s.split(":")[:2]
                date_part = ref.date()
                ts = pd.Timestamp(f"{date_part} {int(hh):02d}:{int(mm):02d}")
            if ts.tzinfo is None:
                ts = ts.tz_localize("America/Los_Angeles")
            else:
                ts = ts.tz_convert("America/Los_Angeles")
            return ts.isoformat()
        except Exception:
            return None

    def _build_inv_chart(timeline: dict, start_iso: str | None,
                          end_iso: str | None) -> "go.Figure":
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        fig = make_subplots(
            rows=3, cols=1, shared_xaxes=True,
            row_heights=[0.55, 0.20, 0.25],
            vertical_spacing=0.03,
            subplot_titles=(None, None, None),
        )

        ts = timeline["ts_1m"]

        fig.add_trace(go.Candlestick(
            x=ts,
            open=timeline["open"], high=timeline["high"],
            low=timeline["low"],   close=timeline["close"],
            name="Price",
            increasing_line_color="#00d47e",
            decreasing_line_color="#ff4757",
            increasing_fillcolor="#00d47e",
            decreasing_fillcolor="#ff4757",
            showlegend=False,
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=ts, y=timeline["vwap"], mode="lines", name="VWAP",
            line={"color": "#4ecdc4", "width": 1.4, "dash": "dot"},
            hovertemplate="VWAP: %{y:.2f}<extra></extra>",
            showlegend=False,
        ), row=1, col=1)

        opens = timeline["open"]
        closes = timeline["close"]
        bar_colors = []
        for o_, c_ in zip(opens, closes):
            if c_ > o_:
                bar_colors.append("#00d47e")
            elif c_ < o_:
                bar_colors.append("#ff4757")
            else:
                bar_colors.append("#666")
        fig.add_trace(go.Bar(
            x=ts, y=timeline["volume"],
            marker={"color": bar_colors, "line": {"width": 0}},
            name="Volume",
            hovertemplate="Vol: %{y:,.0f}<extra></extra>",
            showlegend=False,
        ), row=2, col=1)

        cd = timeline["cum_delta"]
        cd_color = "#ffa502"
        fig.add_trace(go.Scatter(
            x=ts, y=cd, mode="lines", name="Cum \u0394 $",
            line={"color": cd_color, "width": 1.6},
            fill="tozeroy",
            fillcolor="rgba(255,165,2,0.15)",
            hovertemplate="Cum \u0394: $%{y:,.0f}<extra></extra>",
            showlegend=False,
        ), row=3, col=1)

        if start_iso and end_iso:
            for r in (1, 2, 3):
                fig.add_vrect(
                    x0=start_iso, x1=end_iso,
                    fillcolor="#4ecdc4", opacity=0.10,
                    line_width=0, row=r, col=1,
                )

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e",
            font={"color": "#d0d0d0", "size": 11},
            margin={"t": 20, "b": 30, "l": 50, "r": 20},
            height=560,
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
            bargap=0,
            showlegend=False,
        )
        fig.update_yaxes(title_text="Price",     row=1, col=1,
                         gridcolor="rgba(255,255,255,0.05)")
        fig.update_yaxes(title_text="Volume",    row=2, col=1,
                         gridcolor="rgba(255,255,255,0.05)")
        fig.update_yaxes(title_text="Cum \u0394", row=3, col=1,
                         gridcolor="rgba(255,255,255,0.05)",
                         zerolinecolor="rgba(255,255,255,0.15)")
        fig.update_xaxes(rangebreaks=[
            {"bounds": ["sat", "mon"]},
            {"bounds": [13, 6.5], "pattern": "hour"},
        ], gridcolor="rgba(255,255,255,0.05)")
        return fig

    def _summary_cards(summary: dict) -> list:
        if not summary or summary.get("empty"):
            return [dbc.Col(html.P(
                "No data in the selected window.",
                className="text-muted",
                style={"fontSize": "0.85rem", "marginBottom": 0}), width=12)]

        move_pct = summary.get("move_pct") or 0.0
        move_color = _green if move_pct >= 0 else _red
        move_main = f"${summary['price_start']:.2f} \u2192 ${summary['price_end']:.2f}"
        move_sub = f"  {move_pct:+.2f}%   H {summary['high']:.2f} / L {summary['low']:.2f}"

        vol_main = f"{summary['total_vol']/1e6:.2f}M"
        rel = summary.get("rel_vol")
        vol_sub = (f"  {rel:.2f}x typical" if rel else "  rel-vol N/A")
        vol_color = _orange if (rel and rel >= 1.5) else _cyan

        net = summary.get("net_delta") or 0.0
        net_color = _green if net >= 0 else _red
        net_main = f"${net/1e6:+.1f}M"
        bs = summary.get("buy_share") or 50
        net_sub = f"  buy {bs:.1f}%"

        skew_main = (
            "BUYING" if bs >= 60 else
            ("SELLING" if bs <= 40 else "MIXED")
        )
        skew_color = _green if bs >= 60 else (_red if bs <= 40 else _cyan)
        skew_sub = f"  {summary['bar_count']} bars \u2022 {summary['scope']}"

        return [
            _card("PRICE MOVE", move_main, move_sub, move_color),
            _card("WINDOW VOLUME", vol_main, vol_sub, vol_color),
            _card("NET DELTA", net_main, net_sub, net_color),
            _card("DIRECTIONAL", skew_main, skew_sub, skew_color),
        ]

    def _filter_spikes(spikes: list, start_iso: str | None,
                        end_iso: str | None) -> list:
        if not spikes:
            return []
        if not (start_iso and end_iso):
            return spikes
        return [s for s in spikes
                 if start_iso <= s.get("ts_iso", "") <= end_iso]

    def _render_news(items: list) -> list:
        if not items:
            return [html.P("No recent headlines found.",
                            className="text-muted",
                            style={"fontSize": "0.8rem"})]
        children = []
        for it in items[:20]:
            ts = it.get("ts") or ""
            pub = it.get("publisher") or ""
            title = it.get("title") or ""
            link = it.get("link") or ""
            summary = it.get("summary") or ""
            children.append(html.Div([
                html.Div([
                    html.Span(ts, style={"color": "#777",
                                           "fontSize": "0.7rem",
                                           "fontFamily": "Consolas, monospace"}),
                    html.Span(f"  \u2022  {pub}" if pub else "",
                              style={"color": _cyan,
                                     "fontSize": "0.7rem",
                                     "fontWeight": "600"}),
                ], style={"marginBottom": "2px"}),
                html.A(title, href=link, target="_blank",
                       style={"color": "#e0e0e0",
                              "fontSize": "0.85rem",
                              "fontWeight": "600",
                              "textDecoration": "none",
                              "display": "block",
                              "lineHeight": "1.35"}),
                html.Div(summary, style={"color": "#888",
                                            "fontSize": "0.75rem",
                                            "marginTop": "4px",
                                            "marginBottom": "10px",
                                            "lineHeight": "1.4",
                                            "maxHeight": "44px",
                                            "overflow": "hidden"}),
                html.Hr(style={"borderColor": "rgba(255,255,255,0.05)",
                               "margin": "6px 0"}),
            ]))
        return children

    @app.callback(
        [Output("vol-inv-timeline-store", "data"),
         Output("vol-inv-status", "children")],
        Input("vol-inv-run-btn", "n_clicks"),
        [State("vol-inv-symbol", "value"),
         State("vol-inv-lookback", "value")],
        prevent_initial_call=True,
    )
    def vol_inv_fetch_timeline(n_clicks, symbol, lookback):
        if not n_clicks or not symbol or not symbol.strip():
            return no_update, "Enter a symbol and click Investigate."
        sym = symbol.strip().upper()
        try:
            days = int(lookback) if lookback else 2
        except (TypeError, ValueError):
            days = 2

        timeline = _get_timeline(sym, lookback_days=days)
        if not timeline or not timeline.get("ts_1m"):
            return None, f"No intraday data available for {sym}."

        news = _fetch_news(sym, max_items=20)
        timeline["news"] = news
        n_bars = len(timeline["ts_1m"])
        n_spikes = len(timeline.get("spike_rows") or [])
        status = (f"Loaded {sym} \u2014 {n_bars} 1m bars, "
                  f"{n_spikes} 5m spikes, {len(news)} news items.")
        return timeline, status

    @app.callback(
        [Output("vol-inv-chart", "figure"),
         Output("vol-inv-summary", "children"),
         Output("vol-inv-spike-table", "data"),
         Output("vol-inv-news", "children")],
        [Input("vol-inv-timeline-store", "data"),
         Input("vol-inv-start", "value"),
         Input("vol-inv-end", "value")],
    )
    def vol_inv_render(timeline, start_text, end_text):
        if not timeline:
            return no_update, [], [], _render_news([])

        ref_iso = (timeline["ts_1m"] or [None])[-1]
        start_iso = _parse_pt(start_text, ref_iso)
        end_iso = _parse_pt(end_text, ref_iso)
        if start_iso and end_iso and start_iso > end_iso:
            start_iso, end_iso = end_iso, start_iso

        figure = _build_inv_chart(timeline, start_iso, end_iso)
        summary = _summarize_window(timeline, start_iso, end_iso)
        cards = _summary_cards(summary)
        spike_rows = _filter_spikes(timeline.get("spike_rows") or [],
                                     start_iso, end_iso)
        news_children = _render_news(timeline.get("news") or [])
        return figure, cards, spike_rows, news_children

    # Click a row in either of the volume tables → autofill investigator
    # symbol input. User still hits Investigate so we don't make a heavy
    # request on every click.
    @app.callback(
        Output("vol-inv-symbol", "value"),
        [Input("vol-table", "active_cell"),
         Input("vol-spike-table", "active_cell")],
        [State("vol-table", "derived_virtual_data"),
         State("vol-spike-table", "derived_virtual_data")],
        prevent_initial_call=True,
    )
    def vol_inv_autofill(session_cell, spike_cell, session_rows, spike_rows):
        ctx = callback_context
        if not ctx.triggered:
            return no_update
        trig = ctx.triggered[0]["prop_id"]
        if "vol-table" in trig and session_cell and session_rows:
            row = session_rows[session_cell["row"]] if session_cell["row"] < len(session_rows) else None
            if row and row.get("symbol"):
                return row["symbol"]
        if "vol-spike-table" in trig and spike_cell and spike_rows:
            row = spike_rows[spike_cell["row"]] if spike_cell["row"] < len(spike_rows) else None
            if row and row.get("symbol"):
                return row["symbol"]
        return no_update

    # =====================================================================
    # VOLUME HISTORY (Volume tab)
    # =====================================================================

    @app.callback(
        [Output("vol-hist-store", "data"),
         Output("vol-hist-status", "children")],
        [Input("vol-hist-load-btn", "n_clicks"),
         Input("vol-hist-refresh-timer", "n_intervals")],
        [State("vol-hist-symbol", "value"),
         State("vol-hist-timeframe", "value"),
         State("vol-hist-lookback", "value"),
         State("page-tab-volume", "style")],
        prevent_initial_call=True,
    )
    def vol_hist_fetch(n_clicks, _ticks, symbol, timeframe, lookback, page_style):
        ctx = callback_context
        trig = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        is_visible = page_style and page_style.get("display") == "block"
        if "vol-hist-refresh-timer" in trig and not is_visible:
            return no_update, no_update
        if not symbol or not symbol.strip():
            return no_update, "Enter a symbol and click Load Tape."
        sym = symbol.strip().upper()
        try:
            days = int(lookback) if lookback else 1
        except (TypeError, ValueError):
            days = 1
        rows = _get_history(sym, timeframe=timeframe or "5m", lookback_days=days)
        if not rows:
            return [], f"No intraday data available for {sym}."
        sessions = sorted({r["session"] for r in rows})
        auto_tag = " (auto-refresh)" if "vol-hist-refresh-timer" in trig else ""
        status = (f"Loaded{auto_tag} {len(rows)} \u00d7 {timeframe or '5m'} bars for "
                  f"{sym} across {len(sessions)} session"
                  f"{'s' if len(sessions) != 1 else ''}: "
                  f"{', '.join(sessions)}")
        return rows, status

    @app.callback(
        [Output("vol-hist-table", "data"),
         Output("vol-hist-summary", "children")],
        [Input("vol-hist-store", "data"),
         Input("vol-hist-from", "value"),
         Input("vol-hist-to", "value"),
         Input("vol-hist-order", "value")],
    )
    def vol_hist_render(rows, t_from, t_to, order):
        if not rows:
            return [], [dbc.Col(html.P(
                "Click \u2018Load Tape\u2019 to view the bar-by-bar history.",
                className="text-muted",
                style={"fontSize": "0.85rem", "marginBottom": 0}), width=12)]

        last_iso = rows[-1].get("ts_iso") or ""
        start_iso = _parse_pt(t_from, last_iso) if t_from else None
        end_iso = _parse_pt(t_to, last_iso) if t_to else None
        if start_iso and end_iso and start_iso > end_iso:
            start_iso, end_iso = end_iso, start_iso

        if start_iso or end_iso:
            filtered = []
            for r in rows:
                iso = r.get("ts_iso") or ""
                if start_iso and iso < start_iso:
                    continue
                if end_iso and iso > end_iso:
                    continue
                filtered.append(r)
        else:
            filtered = list(rows)

        if order == "desc":
            display = list(reversed(filtered))
        else:
            display = filtered

        if not filtered:
            cards = [dbc.Col(html.P(
                "No bars in the selected window.",
                className="text-muted",
                style={"fontSize": "0.85rem", "marginBottom": 0}), width=12)]
            return display, cards

        # Aggregate stats over the visible (filtered) range
        n = len(filtered)
        first = filtered[0]
        last = filtered[-1]
        first_open = first.get("open") or last.get("close")
        last_close = last.get("close") or first.get("close")
        chg_pct = ((last_close / first_open - 1) * 100) if first_open else 0

        total_vol = sum((r.get("volume") or 0) for r in filtered)
        net_delta = sum((r.get("delta") or 0) for r in filtered)
        buy_total = sum((r.get("buy_dollar") or 0) for r in filtered)
        sell_total = sum((r.get("sell_dollar") or 0) for r in filtered)
        buy_share = (buy_total / (buy_total + sell_total) * 100
                     if (buy_total + sell_total) > 0 else 50.0)
        n_hot = sum(1 for r in filtered if (r.get("vol_z") or 0) >= 2)
        biggest = max(filtered, key=lambda r: abs(r.get("delta") or 0))

        move_color = _green if chg_pct >= 0 else _red
        net_color = _green if net_delta >= 0 else _red
        skew = "BUYING" if buy_share >= 60 else (
            "SELLING" if buy_share <= 40 else "MIXED")
        skew_color = _green if buy_share >= 60 else (
            _red if buy_share <= 40 else _cyan)

        cards = [
            _card("BARS / RANGE", f"{n}",
                  f"  {first['ts'][6:]} \u2192 {last['ts'][6:]}",
                  _cyan),
            _card("RANGE MOVE",
                  f"${first_open:.2f} \u2192 ${last_close:.2f}",
                  f"  {chg_pct:+.2f}%", move_color),
            _card("TOTAL VOLUME", f"{total_vol/1e6:.2f}M",
                  f"  hot bars: {n_hot}  (z\u22652)", _cyan),
            _card("NET \u0394", f"${net_delta/1e6:+.1f}M",
                  f"  buy {buy_share:.1f}%  \u2022  {skew}",
                  net_color if skew == "MIXED" else skew_color),
        ]

        # Annotate biggest delta bar in the table by adding a marker on the
        # symbol-less view via the "ts" column tooltip — simpler: just
        # surface it in the status via summary (already covered).
        return display, cards

    # ── Download Volume History as CSV ────────────────────────────────────
    @app.callback(
        Output("vol-hist-download", "data"),
        Input("vol-hist-download-btn", "n_clicks"),
        [State("vol-hist-table", "derived_virtual_data"),
         State("vol-hist-table", "data"),
         State("vol-hist-symbol", "value"),
         State("vol-hist-timeframe", "value")],
        prevent_initial_call=True,
    )
    def vol_hist_download(n_clicks, virtual_rows, table_rows,
                           symbol, timeframe):
        if not n_clicks:
            return no_update
        rows = virtual_rows if virtual_rows else table_rows
        if not rows:
            return no_update

        column_order = [
            "ts", "ts_iso", "session", "open", "high", "low", "close",
            "bar_chg", "range", "volume", "pct_sess", "cum_vol",
            "vol_z", "rel_vol", "buy_share", "buy_dollar", "sell_dollar",
            "delta", "cum_delta", "vwap", "vwap_diff",
        ]
        df = pd.DataFrame(rows)
        ordered = [c for c in column_order if c in df.columns]
        extras = [c for c in df.columns if c not in ordered]
        df = df[ordered + extras]

        sym = (symbol or "symbol").strip().upper() or "symbol"
        tf = (timeframe or "5m").strip()
        ts_tag = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        filename = f"volume_history_{sym}_{tf}_{ts_tag}.csv"
        return dcc.send_data_frame(df.to_csv, filename, index=False)

    # Sync history symbol with row clicks too — same source of truth as
    # the Investigator autofill.
    @app.callback(
        Output("vol-hist-symbol", "value"),
        [Input("vol-table", "active_cell"),
         Input("vol-spike-table", "active_cell"),
         Input("vol-inv-symbol", "value")],
        [State("vol-table", "derived_virtual_data"),
         State("vol-spike-table", "derived_virtual_data"),
         State("vol-hist-symbol", "value")],
        prevent_initial_call=True,
    )
    def vol_hist_autofill(session_cell, spike_cell, inv_symbol,
                           session_rows, spike_rows, current):
        ctx = callback_context
        if not ctx.triggered:
            return no_update
        trig = ctx.triggered[0]["prop_id"]

        if "vol-inv-symbol" in trig:
            if inv_symbol and inv_symbol.strip():
                return inv_symbol.strip().upper()
            return no_update

        if "vol-table" in trig and session_cell and session_rows:
            row = session_rows[session_cell["row"]] if session_cell["row"] < len(session_rows) else None
            if row and row.get("symbol"):
                return row["symbol"]
        if "vol-spike-table" in trig and spike_cell and spike_rows:
            row = spike_rows[spike_cell["row"]] if spike_cell["row"] < len(spike_rows) else None
            if row and row.get("symbol"):
                return row["symbol"]
        return no_update

    @app.callback(
        [Output("vol-prof-session", "options"),
         Output("vol-prof-session", "value")],
        Input("vol-hist-store", "data"),
        State("vol-prof-session", "value"),
    )
    def sync_profile_sessions(rows, current_value):
        base = [{"label": "All loaded days", "value": "ALL"}]
        if not rows:
            return base, "ALL"
        sessions = sorted({str(r.get("session")) for r in rows if r.get("session")})
        opts = base + [{"label": s, "value": s} for s in sessions]
        if current_value in {o["value"] for o in opts}:
            return opts, current_value
        # Default to latest session when available.
        return opts, (sessions[-1] if sessions else "ALL")

    @app.callback(
        [Output("vol-prof-status", "children"),
         Output("vol-prof-price-chart", "figure"),
         Output("vol-prof-summary", "children"),
         Output("vol-prof-zones", "children"),
         Output("vol-prof-hist-chart", "figure")],
        [Input("vol-prof-build-btn", "n_clicks"),
         Input("vol-hist-store", "data")],
        [State("vol-hist-symbol", "value"),
         State("vol-hist-timeframe", "value"),
         State("vol-prof-session", "value"),
         State("vol-prof-bins", "value"),
         State("vol-prof-va-pct", "value")],
        prevent_initial_call=True,
    )
    def build_volume_profile(_n, rows, symbol, timeframe, profile_session, bins, va_pct):
        def _empty_fig(msg: str):
            fig = go.Figure()
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#1a1a2e",
                plot_bgcolor="#1a1a2e",
                height=430,
                margin=dict(t=25, b=40, l=35, r=15),
                annotations=[dict(
                    text=msg, x=0.5, y=0.5, showarrow=False,
                    xref="paper", yref="paper", font=dict(color="#666", size=12)
                )],
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
            )
            return fig

        def _price_fig_from_rows(base_df, sym_label, tf_label):
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=base_df["ts_iso"],
                open=base_df["open"],
                high=base_df["high"],
                low=base_df["low"],
                close=base_df["close"],
                increasing_line_color="#00d47e",
                decreasing_line_color="#ff4757",
                name="Price",
            ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#1a1a2e",
                plot_bgcolor="#1a1a2e",
                height=430,
                margin=dict(t=30, b=35, l=45, r=15),
                title=f"{sym_label} ({tf_label})",
                xaxis=dict(rangeslider=dict(visible=False)),
                yaxis=dict(title="Price"),
                showlegend=False,
            )
            return fig

        sym = (symbol or "").strip().upper()
        if not sym:
            return "Enter a symbol in Volume History first.", _empty_fig("Missing symbol"), [], "", _empty_fig("Missing symbol")
        if not rows:
            return "Load Volume History first, then build profile.", _empty_fig("No history loaded"), [], "", _empty_fig("No history loaded")

        df = pd.DataFrame(rows).copy()
        if "session" in df.columns and profile_session and profile_session != "ALL":
            df = df[df["session"].astype(str) == str(profile_session)].copy()
            if df.empty:
                return (f"No bars for session {profile_session}.", _empty_fig(f"No data for {profile_session}"), [], "",
                        _empty_fig(f"No data for {profile_session}"))
        for col in ("low", "high", "volume"):
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        df = df.dropna(subset=["low", "high", "volume"])
        df = df[df["volume"] > 0]
        if df.empty:
            return "No usable bars found for profile.", _empty_fig("No usable bars"), [], "", _empty_fig("No usable bars")

        try:
            n_bins = max(12, min(120, int(bins))) if bins is not None else 36
        except (TypeError, ValueError):
            n_bins = 36
        try:
            va_target = float(va_pct) if va_pct is not None else 70.0
        except (TypeError, ValueError):
            va_target = 70.0
        va_target = min(99.0, max(50.0, va_target))

        low_min = float(df["low"].min())
        high_max = float(df["high"].max())
        if high_max <= low_min:
            return "Flat price range; cannot compute profile.", _empty_fig("Flat range"), [], "", _empty_fig("Flat range")

        step = (high_max - low_min) / n_bins
        profile = [0.0] * n_bins

        for _, r in df.iterrows():
            lo = float(min(r["low"], r["high"]))
            hi = float(max(r["low"], r["high"]))
            vol = float(r["volume"])
            if hi == lo:
                idx = min(n_bins - 1, max(0, int((lo - low_min) / step)))
                profile[idx] += vol
                continue
            start = min(n_bins - 1, max(0, int((lo - low_min) / step)))
            end = min(n_bins - 1, max(0, int((hi - low_min) / step)))
            span = hi - lo
            for idx in range(start, end + 1):
                b_lo = low_min + idx * step
                b_hi = b_lo + step
                overlap = max(0.0, min(hi, b_hi) - max(lo, b_lo))
                if overlap > 0:
                    profile[idx] += vol * (overlap / span)

        total_vol = sum(profile)
        if total_vol <= 0:
            return "Computed profile volume is zero.", _empty_fig("Zero profile volume"), [], "", _empty_fig("Zero profile volume")

        prices = [low_min + (i + 0.5) * step for i in range(n_bins)]
        poc_idx = max(range(n_bins), key=lambda i: profile[i])
        poc_price = prices[poc_idx]

        target_vol = total_vol * (va_target / 100.0)
        selected = {poc_idx}
        cum = profile[poc_idx]
        left = poc_idx - 1
        right = poc_idx + 1
        while cum < target_vol and (left >= 0 or right < n_bins):
            left_vol = profile[left] if left >= 0 else -1
            right_vol = profile[right] if right < n_bins else -1
            if right_vol >= left_vol:
                if right < n_bins:
                    selected.add(right)
                    cum += profile[right]
                    right += 1
                elif left >= 0:
                    selected.add(left)
                    cum += profile[left]
                    left -= 1
            else:
                if left >= 0:
                    selected.add(left)
                    cum += profile[left]
                    left -= 1
                elif right < n_bins:
                    selected.add(right)
                    cum += profile[right]
                    right += 1

        val_price = prices[min(selected)]
        vah_price = prices[max(selected)]

        ranked = sorted(range(n_bins), key=lambda i: profile[i], reverse=True)
        hvn_idxs = [i for i in ranked if i != poc_idx][:3]
        nonzero = [i for i in range(n_bins) if profile[i] > 0]
        lvn_sorted = sorted(nonzero, key=lambda i: profile[i])
        lvn_idxs = [i for i in lvn_sorted[:3] if i != poc_idx]

        # Build price chart from yfinance first; fallback to loaded history rows.
        price_fig = None
        data_note = ""
        try:
            interval = _yf_interval_from_history(timeframe)
            hist_days = 5 if interval in ("1m", "5m", "15m", "30m", "60m", "1h") else 60
            yf_df = yf.Ticker(sym).history(period=f"{hist_days}d", interval=interval)
            if not yf_df.empty:
                yf_df = yf_df.rename(columns={
                    "Open": "open", "High": "high",
                    "Low": "low", "Close": "close",
                }).reset_index()
                ts_col = "Datetime" if "Datetime" in yf_df.columns else "Date"
                yf_df["ts_iso"] = pd.to_datetime(yf_df[ts_col], errors="coerce")
                if profile_session and profile_session != "ALL":
                    target_day = str(profile_session)
                    yf_df = yf_df[yf_df["ts_iso"].dt.strftime("%Y-%m-%d") == target_day]
                yf_df = yf_df.dropna(subset=["ts_iso", "open", "high", "low", "close"])
                if not yf_df.empty:
                    price_fig = _price_fig_from_rows(yf_df, sym, timeframe or "1d")
                    data_note = "Price chart source: yfinance."
        except Exception as exc:
            data_note = f"yfinance chart unavailable ({exc}); using loaded history."

        if price_fig is None:
            local_df = df.copy()
            for col in ("open", "high", "low", "close"):
                local_df[col] = pd.to_numeric(local_df.get(col), errors="coerce")
            local_df = local_df.dropna(subset=["open", "high", "low", "close"])
            if "ts_iso" not in local_df.columns or local_df.empty:
                price_fig = _empty_fig("No price candles available")
            else:
                price_fig = _price_fig_from_rows(local_df, sym, timeframe or "1d")
            if not data_note:
                data_note = "Price chart source: loaded Volume History."

        cards = [
            _card("POC", f"${poc_price:.2f}", f"{profile[poc_idx]:,.0f} vol", _cyan),
            _card("VALUE AREA HIGH", f"${vah_price:.2f}", f"{va_target:.0f}% target", _green),
            _card("VALUE AREA LOW", f"${val_price:.2f}", f"{va_target:.0f}% target", _orange),
            _card("PROFILE RANGE", f"${low_min:.2f} → ${high_max:.2f}", f"{n_bins} bins", _cyan),
        ]

        def _fmt_zone(i):
            return f"${prices[i]:.2f} ({profile[i]:,.0f})"

        zones = html.Div([
            html.Span("High-interest zones (HVN): ", style={"fontWeight": "700", "color": "#ddd"}),
            html.Span(" | ".join(_fmt_zone(i) for i in hvn_idxs) if hvn_idxs else "n/a"),
            html.Br(),
            html.Span("Low-interest zones (LVN): ", style={"fontWeight": "700", "color": "#ddd"}),
            html.Span(" | ".join(_fmt_zone(i) for i in lvn_idxs) if lvn_idxs else "n/a"),
        ])

        bar_colors = ["rgba(78,205,196,0.55)" if i in selected else "rgba(120,120,160,0.42)"
                      for i in range(n_bins)]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=profile,
            y=prices,
            orientation="h",
            marker_color=bar_colors,
            hovertemplate="Price: $%{y:.2f}<br>Volume: %{x:,.0f}<extra></extra>",
            name="Volume",
        ))
        fig.add_hline(y=poc_price, line=dict(color="#4ecdc4", width=2, dash="solid"),
                      annotation_text="POC", annotation_position="top right")
        fig.add_hline(y=vah_price, line=dict(color="#00d47e", width=1, dash="dot"),
                      annotation_text="VAH", annotation_position="top right")
        fig.add_hline(y=val_price, line=dict(color="#ffa502", width=1, dash="dot"),
                      annotation_text="VAL", annotation_position="bottom right")
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e",
            height=430,
            margin=dict(t=25, b=40, l=35, r=15),
            xaxis=dict(title="Allocated Volume"),
            yaxis=dict(title="Price", tickprefix="$"),
            showlegend=False,
        )

        session_label = profile_session if profile_session and profile_session != "ALL" else "all loaded days"
        status = (f"Profile built for {sym} ({timeframe or '1d'}, session: {session_label}) "
                  f"using {len(df):,} bars and {int(total_vol):,} total volume. {data_note}")
        return status, price_fig, cards, zones, fig

    # =====================================================================
    # GEX HEATMAP — Black-Scholes gamma × yfinance OI, no paid APIs
    # =====================================================================

    def _gex_empty_fig(msg: str, h: int = 520):
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e",
            height=h,
            margin=dict(t=30, b=50, l=50, r=15),
            annotations=[dict(
                text=msg, x=0.5, y=0.5, showarrow=False,
                xref="paper", yref="paper",
                font=dict(color="#888", size=13),
            )],
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig

    def _gex_wall_line(label, walls, color, scale_mm=1e6):
        if not walls:
            return html.Span(
                f"{label}: n/a  ", style={"color": "#888"})
        chunks = [f"${w['strike']:,.2f} ({w['gex']/scale_mm:+.1f}M)"
                  for w in walls]
        return html.Div([
            html.Span(label + ": ", style={"fontWeight": "700", "color": "#ddd"}),
            html.Span(" | ".join(chunks),
                      style={"color": color, "fontWeight": "600"}),
        ])

    def _gex_walls_block(spot, flip, call_walls, put_walls):
        return html.Div([
            _gex_wall_line("Top Call Walls (resistance)", call_walls, _green),
            _gex_wall_line("Top Put Walls (support)", put_walls, _red),
            html.Div([
                html.Span("Regime: ", style={"fontWeight": "700",
                                              "color": "#ddd"}),
                html.Span(
                    ("LONG GAMMA — dealers dampen volatility, "
                     "expect mean reversion."
                     if flip is not None and spot >= flip
                     else "SHORT GAMMA — dealers amplify volatility, "
                          "expect trending / momentum.")
                    if flip is not None else
                    "Flip level undefined (chain too thin or all one sign).",
                    style={"color": _cyan, "fontWeight": "600"}),
            ], style={"marginTop": "6px"}),
        ])

    def _gex_empty_response(msg: str):
        return (
            msg, [],
            {"error": msg},
            _gex_empty_fig(msg, 280),
            _gex_empty_fig(msg, 560),
            _gex_empty_fig(msg, 560),
            _gex_empty_fig(msg, 560),
            _gex_empty_fig(msg, 360),
            _gex_empty_fig(msg, 360),
            [], "",
        )

    def _gex_value_label(value: float) -> str:
        sign = "+" if value >= 0 else "-"
        amount = abs(float(value))
        if amount >= 1e9:
            return f"{sign}${amount/1e9:.2f}B"
        return f"{sign}${amount/1e6:.1f}M"

    def _gex_snapshot_visuals(result, symbol: str, dte_label: str,
                              source_label: str):
        """Build the shared snapshot figures used by both GEX providers."""
        scale_mm = 1e6
        spot = result.spot
        strikes = result.strikes
        expirations = result.expirations
        flip = result.flip_price
        z_mm = [[value / scale_mm for value in row]
                for row in result.heatmap]
        profile_mm = [value / scale_mm for value in result.profile]
        total_mm = result.total_gex / scale_mm
        flip_text = f"${flip:,.2f}" if flip is not None else "n/a"

        cards = [
            _card("SPOT", f"${spot:,.2f}",
                  f"{source_label} · {result.as_of}", _cyan),
            _card("NET GEX", f"{total_mm:,.1f}M",
                  (f"Call {result.call_gex/scale_mm:+.1f}M · "
                   f"Put {result.put_gex/scale_mm:+.1f}M / 1%"),
                  _green if total_mm >= 0 else _red),
            _card("ZERO-GAMMA FLIP", flip_text,
                  "above = long γ / below = short γ",
                  _green if (flip is not None and spot >= flip) else _red),
            _card("CHAIN COVERAGE",
                  f"{len(expirations)} exps × {len(strikes)} K",
                  f"{result.rows:,} rows · {dte_label}", _cyan),
        ]
        time_figure = _gex_empty_fig(
            f"{source_label} comparison currently uses live chain snapshots",
            h=260)

        z_array = np.asarray(z_mm, dtype=float)
        z_limit = float(np.nanmax(np.abs(z_array))) if z_array.size else 1.0
        z_limit = max(z_limit, 1e-9)
        expiry_labels = [
            f"{expiry}<br>{dte}DTE"
            for expiry, dte in zip(expirations, result.expiration_dtes)
        ]
        heatmap_figure = go.Figure(go.Heatmap(
            x=expiry_labels, y=strikes, z=z_mm, zmid=0,
            zmin=-z_limit, zmax=z_limit,
            colorscale=[[0, "#ff4757"], [.5, "#1a1a2e"], [1, "#00d47e"]],
            colorbar=dict(title=dict(text="GEX ($M)"), thickness=10),
            hovertemplate=("Expiry: %{x}<br>Strike: $%{y:.2f}"
                           "<br>GEX: %{z:.2f} M<extra></extra>"),
        ))
        heatmap_figure.add_hline(
            y=spot, line=dict(color=_cyan, width=2, dash="dash"),
            annotation_text=f"Spot ${spot:,.2f}")
        if flip is not None and min(strikes) <= flip <= max(strikes):
            heatmap_figure.add_hline(
                y=flip, line=dict(color=_orange, width=2, dash="dot"),
                annotation_text=f"Flip ${flip:,.2f}")
        heatmap_figure.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=520,
            margin=dict(t=30, b=60, l=70, r=15),
            xaxis=dict(title="Expiration", tickangle=-35),
            yaxis=dict(title="Strike", tickprefix="$"),
            title=dict(text=f"{symbol} — {source_label} GEX by Strike × Expiration",
                       font=dict(size=13, color="#ddd")),
        )

        profile_figure = go.Figure()
        profile_figure.add_trace(go.Bar(
            x=[value/scale_mm for value in result.call_profile], y=strikes,
            orientation="h", marker_color=_green, opacity=.72,
            name="Call GEX"))
        profile_figure.add_trace(go.Bar(
            x=[value/scale_mm for value in result.put_profile], y=strikes,
            orientation="h", marker_color=_red, opacity=.72,
            name="Put GEX"))
        profile_figure.add_trace(go.Scatter(
            x=profile_mm, y=strikes, mode="lines",
            line=dict(color="#f1f2f6", width=1.5), name="Net GEX"))
        profile_figure.add_hline(
            y=spot, line=dict(color=_cyan, width=2, dash="dash"),
            annotation_text=f"Spot ${spot:,.2f}")
        if flip is not None and min(strikes) <= flip <= max(strikes):
            profile_figure.add_hline(
                y=flip, line=dict(color=_orange, width=2, dash="dot"),
                annotation_text=f"Flip ${flip:,.2f}")
        profile_figure.add_vline(x=0, line_color="rgba(255,255,255,.25)")
        profile_figure.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=520, barmode="relative",
            margin=dict(t=30, b=50, l=55, r=15),
            xaxis=dict(title="Net GEX ($M)"),
            yaxis=dict(title="Strike", tickprefix="$"),
            legend=dict(orientation="h", y=1.04, x=1, xanchor="right"),
            title=dict(text=f"{source_label} Call / Put / Net GEX by Strike",
                       font=dict(size=13, color="#ddd")),
        )

        scenario_figure = go.Figure(go.Scatter(
            x=result.scenario_spots,
            y=[value/scale_mm for value in result.scenario_gex],
            mode="lines", line=dict(color=_cyan, width=2.5),
            fill="tozeroy", fillcolor="rgba(78,205,196,.08)",
            hovertemplate="Spot $%{x:.2f}<br>Net GEX %{y:.2f}M<extra></extra>",
        ))
        scenario_figure.add_hline(y=0, line_color="rgba(255,255,255,.35)")
        scenario_figure.add_vline(
            x=spot, line=dict(color=_cyan, width=2, dash="dash"),
            annotation_text=f"Spot ${spot:,.2f}")
        if flip is not None:
            scenario_figure.add_vline(
                x=flip, line=dict(color=_orange, width=2, dash="dot"),
                annotation_text=f"Flip ${flip:,.2f}")
        scenario_figure.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=360, showlegend=False,
            margin=dict(t=42, b=48, l=62, r=20),
            title=dict(text=f"{source_label} Whole-Chain Gamma Regime",
                       font=dict(size=13, color="#ddd")),
            xaxis=dict(title="Hypothetical Underlying Price", tickprefix="$"),
            yaxis=dict(title="Net GEX ($M / 1% move)"),
        )

        expiration_figure = go.Figure()
        expiration_x = [f"{row['expiry']}<br>{row.get('dte', '?')}DTE"
                        for row in result.expiration_gex]
        expiration_figure.add_trace(go.Bar(
            x=expiration_x,
            y=[row["call_gex"]/scale_mm for row in result.expiration_gex],
            name="Call GEX", marker_color=_green))
        expiration_figure.add_trace(go.Bar(
            x=expiration_x,
            y=[row["put_gex"]/scale_mm for row in result.expiration_gex],
            name="Put GEX", marker_color=_red))
        expiration_figure.add_trace(go.Scatter(
            x=expiration_x,
            y=[row["net_gex"]/scale_mm for row in result.expiration_gex],
            name="Net GEX", mode="lines+markers",
            line=dict(color="#f1f2f6", width=2)))
        expiration_figure.add_hline(y=0, line_color="rgba(255,255,255,.3)")
        expiration_figure.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=360, barmode="relative",
            margin=dict(t=42, b=65, l=60, r=20),
            title=dict(text=f"{source_label} GEX Contribution by Expiration",
                       font=dict(size=13, color="#ddd")),
            xaxis=dict(title="Expiration", tickangle=-35),
            yaxis=dict(title="GEX ($M / 1% move)"),
            legend=dict(orientation="h", y=1.05, x=1, xanchor="right"),
        )

        level_rows = [{
            "strike": round(float(strike), 2),
            "call_gex": round(float(call_gex)/scale_mm, 4),
            "put_gex": round(float(put_gex)/scale_mm, 4),
            "net_gex": round(float(net_gex)/scale_mm, 4),
            "call_oi": int(round(float(call_oi))),
            "put_oi": int(round(float(put_oi))),
        } for strike, call_gex, put_gex, net_gex, call_oi, put_oi in zip(
            strikes, result.call_profile, result.put_profile, result.profile,
            result.call_oi_profile, result.put_oi_profile)]
        walls = _gex_walls_block(
            spot, flip, result.call_walls, result.put_walls)
        return (cards, time_figure, heatmap_figure, profile_figure,
                scenario_figure, expiration_figure, level_rows, walls)

    def _build_gex_wall_cloud(intraday_result, symbol: str,
                              day: str, interval: str):
        """Render TradingView-style candles with typed GEX wall clouds."""
        timestamps = intraday_result.timestamps
        strikes = np.asarray(intraday_result.strikes, dtype=float)
        values_mm = np.asarray(intraday_result.heatmap, dtype=float) / 1e6
        if values_mm.ndim != 2 or values_mm.size == 0:
            return _gex_empty_fig("No intraday GEX wall history available", 560)

        magnitude = np.abs(values_mm)
        nonzero = magnitude[np.isfinite(magnitude) & (magnitude > 0)]
        scale = float(np.nanpercentile(nonzero, 98)) if nonzero.size else 1.0
        scale = max(scale, 1e-9)
        positive = np.sqrt(np.clip(np.maximum(values_mm, 0)/scale, 0, 1))
        negative = np.sqrt(np.clip(np.maximum(-values_mm, 0)/scale, 0, 1))
        # Only display meaningful concentrations. The gaps turn a dense
        # strike heatmap into the thin wall bands used by GEX charting tools.
        positive[positive < .20] = np.nan
        negative[negative < .20] = np.nan

        figure = go.Figure()

        def _add_wall_segments(intensity, positive_side: bool):
            """Turn significant strike cells into narrow persistent bands."""
            if positive_side:
                levels = [
                    (.20, .45, "rgba(255,214,45,.24)", 2.0),
                    (.45, .72, "rgba(255,214,45,.55)", 3.5),
                    (.72, 1.01, "rgba(255,222,59,.94)", 6.0),
                ]
                legend_name = "Positive GEX wall"
                extra = "Positive wall"
            else:
                levels = [
                    (.20, .45, "rgba(166,82,255,.24)", 2.0),
                    (.45, .72, "rgba(183,75,255,.58)", 3.5),
                    (.72, 1.01, "rgba(203,74,255,.94)", 6.0),
                ]
                legend_name = "Negative GEX wall"
                extra = "Negative wall"

            for band_index, (lower, upper, color, width) in enumerate(levels):
                xs, ys, custom = [], [], []
                for strike_index, strike in enumerate(strikes):
                    active = ((intensity[strike_index] >= lower)
                              & (intensity[strike_index] < upper))
                    in_run = False
                    for time_index, is_active in enumerate(active):
                        if not is_active:
                            if in_run:
                                xs.append(None)
                                ys.append(None)
                                custom.append(None)
                                in_run = False
                            continue
                        xs.append(timestamps[time_index])
                        ys.append(float(strike))
                        custom.append(float(values_mm[strike_index, time_index]))
                        in_run = True
                    if in_run:
                        xs.append(None)
                        ys.append(None)
                        custom.append(None)

                if not xs:
                    continue
                figure.add_trace(go.Scatter(
                    x=xs, y=ys, customdata=custom,
                    mode="lines+markers", connectgaps=False,
                    name=legend_name, legendgroup=legend_name,
                    showlegend=(band_index == 0),
                    line=dict(color=color, width=width),
                    marker=dict(color=color, size=max(2.5, width)),
                    hovertemplate=("%{x}<br>Strike $%{y:.2f}<br>"
                                   "GEX %{customdata:.2f}M"
                                   f"<extra>{extra}</extra>"),
                ))

        _add_wall_segments(positive, True)
        _add_wall_segments(negative, False)

        opens = list(getattr(intraday_result, "open_series", []) or [])
        highs = list(getattr(intraday_result, "high_series", []) or [])
        lows = list(getattr(intraday_result, "low_series", []) or [])
        closes = list(getattr(intraday_result, "close_series", []) or [])
        has_candles = all(len(series) == len(timestamps)
                          for series in (opens, highs, lows, closes))
        if has_candles:
            figure.add_trace(go.Candlestick(
                x=timestamps, open=opens, high=highs, low=lows, close=closes,
                name=symbol, increasing_line_color="#35d6a2",
                increasing_fillcolor="#35d6a2",
                decreasing_line_color="#ff5570",
                decreasing_fillcolor="#ff5570", whiskerwidth=.35,
                hovertext=[
                    (f"{ts}<br>O {o:.2f} · H {h:.2f}<br>"
                     f"L {lo:.2f} · C {c:.2f}")
                    for ts, o, h, lo, c in zip(
                        timestamps, opens, highs, lows, closes)
                ],
                hoverinfo="text",
            ))
        else:
            figure.add_trace(go.Scatter(
                x=timestamps, y=intraday_result.spot_series,
                mode="lines", name="Spot path",
                line=dict(color="#f1f5f7", width=2.2),
                hovertemplate="%{x}<br>Spot $%{y:.2f}<extra></extra>"))

        figure.add_trace(go.Scatter(
            x=timestamps, y=intraday_result.flip_series,
            mode="lines", name="Modeled gamma flip",
            line=dict(color="rgba(255,168,38,.72)", width=1.25, dash="dot"),
            connectgaps=False,
            hovertemplate="%{x}<br>Flip $%{y:.2f}<extra></extra>"))

        strike_steps = np.diff(np.unique(strikes))
        band_half = (float(np.nanmedian(strike_steps))*.10
                     if strike_steps.size else intraday_result.final_spot*.00012)
        current_walls = [
            ("CALL", wall, "#2ee6c5", "dash")
            for wall in (intraday_result.call_walls or [])[:3]
        ] + [
            ("PUT", wall, "#ff5a80", "dash")
            for wall in (intraday_result.put_walls or [])[:3]
        ]
        for wall_type, wall, color, dash in current_walls:
            strike = float(wall["strike"])
            figure.add_hrect(
                y0=strike-band_half, y1=strike+band_half,
                fillcolor=("rgba(46,230,197,.10)" if wall_type == "CALL"
                           else "rgba(255,90,128,.10)"),
                line=dict(color=color, width=.8), layer="above")
            figure.add_trace(go.Scatter(
                x=[timestamps[0], timestamps[-1]], y=[strike, strike],
                mode="lines", name=f"Current {wall_type} wall ${strike:,.2f}",
                line=dict(color=color, width=1.25, dash=dash),
                hovertemplate=(f"Current {wall_type} wall $%{{y:.2f}}<br>"
                               f"{_gex_value_label(float(wall['gex']))}"
                               "<extra></extra>")))
            figure.add_annotation(
                x=timestamps[-1], y=strike, xanchor="right", yanchor="bottom",
                text=(f"{wall_type[0]} ${strike:,.2f} · "
                      f"{_gex_value_label(float(wall['gex']))}"),
                showarrow=False, bgcolor="rgba(7,10,14,.78)",
                bordercolor=color, borderwidth=1, borderpad=3,
                font=dict(color=color, size=9))

        # Focus the initial camera around the session price action and nearby
        # walls. Users can still pan/zoom to inspect levels further away.
        price_lows = np.asarray(lows or intraday_result.spot_series, dtype=float)
        price_highs = np.asarray(highs or intraday_result.spot_series, dtype=float)
        session_low = float(np.nanmin(price_lows))
        session_high = float(np.nanmax(price_highs))
        session_span = max(session_high-session_low,
                           max(intraday_result.final_spot, 1.0)*.0025)
        view_padding = max(session_span*.70,
                           max(intraday_result.final_spot, 1.0)*.004)
        y_range = [session_low-view_padding, session_high+view_padding]

        current_spot = float(intraday_result.final_spot)
        figure.add_hline(
            y=current_spot,
            line=dict(color="rgba(99,230,255,.70)", width=1, dash="dot"),
            annotation_text=f"{current_spot:,.2f}",
            annotation_position="right",
            annotation_font_color="#63e6ff",
            annotation_bgcolor="rgba(12,18,23,.88)",
        )

        figure.update_layout(
            template="plotly_dark", paper_bgcolor="#080d11",
            plot_bgcolor="#080d11", height=560,
            margin=dict(t=58, b=42, l=22, r=72),
            title=dict(
                text=(f"{symbol} — Intraday Candles + Modeled GEX Walls · "
                      f"{day} ({interval})<br>"
                      "<sup>Current OI/IV repriced through historical spot; current walls overlaid</sup>"),
                x=.012, font=dict(size=13, color="#e8edf2")),
            xaxis=dict(title="", tickfont=dict(size=9), rangeslider_visible=False,
                       gridcolor="rgba(120,145,160,.10)", showspikes=True,
                       spikemode="across", spikesnap="cursor"),
            yaxis=dict(title="", side="right", tickprefix="$", tickformat=".2f",
                       range=y_range, fixedrange=False,
                       gridcolor="rgba(120,145,160,.10)", showspikes=True,
                       spikemode="across", spikesnap="cursor"),
            legend=dict(orientation="h", y=1.02, x=.995, xanchor="right",
                        font=dict(size=9)),
            hovermode="x unified", dragmode="pan",
            hoverlabel=dict(bgcolor="#111820", bordercolor="#34414c"),
        )
        return figure

    def _build_gex_price_map(symbol: str, strikes, profile, total_gex,
                             flip, period="1d", interval="5m",
                             day: str | None = None,
                             dte_label: str = "all DTEs",
                             bars_override=None):
        """Bullflow-style candles with GEX zones computed by this app."""
        if bars_override is not None:
            bars = bars_override.copy()
        else:
            try:
                if day:
                    day_ts = pd.Timestamp(day).normalize()
                    start = (day_ts - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                    end = (day_ts + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
                    bars = yf.download(
                        symbol, start=start, end=end, interval=interval,
                        auto_adjust=False, prepost=False, progress=False,
                        threads=False,
                    )
                else:
                    bars = yf.download(
                        symbol, period=period, interval=interval,
                        auto_adjust=False, prepost=False, progress=False,
                        threads=False,
                    )
            except Exception as exc:
                return _gex_empty_fig(f"Price-map candles unavailable: {exc}", 670)

        if bars is None or bars.empty:
            return _gex_empty_fig("No intraday candles available for this selection", 670)
        if isinstance(bars.columns, pd.MultiIndex):
            bars.columns = bars.columns.get_level_values(0)
        required = ["Open", "High", "Low", "Close", "Volume"]
        if any(c not in bars.columns for c in required):
            return _gex_empty_fig("Intraday feed returned incomplete OHLCV data", 670)

        bars = bars.copy().dropna(subset=["Open", "High", "Low", "Close"])
        if bars.empty:
            return _gex_empty_fig("No usable intraday candles returned", 670)
        idx = bars.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        bars.index = idx.tz_convert("America/Los_Angeles")
        if day:
            target = pd.Timestamp(day).date()
            bars = bars[bars.index.date == target]
        if bars.empty:
            return _gex_empty_fig("No regular-session candles for that day", 670)

        for col in required:
            bars[col] = pd.to_numeric(bars[col], errors="coerce")
        bars = bars.dropna(subset=["Open", "High", "Low", "Close"])
        bars["Volume"] = bars["Volume"].fillna(0.0)
        typical = (bars["High"] + bars["Low"] + bars["Close"]) / 3.0
        cumulative_volume = bars["Volume"].cumsum().replace(0, np.nan)
        bars["VWAP"] = (typical * bars["Volume"]).cumsum() / cumulative_volume
        # Ordinal x positions deliberately reserve the right ~43% of the
        # canvas for magnitude-scaled GEX bars, matching a professional
        # gamma chart instead of drawing zones over the candles.
        x_pos = np.arange(len(bars), dtype=float)

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.025,
            row_heights=[0.78, 0.22],
        )
        fig.add_trace(go.Candlestick(
            x=x_pos, open=bars["Open"], high=bars["High"],
            low=bars["Low"], close=bars["Close"], name=symbol,
            increasing_line_color="#2ed8a3", increasing_fillcolor="#2ed8a3",
            decreasing_line_color="#ff5570", decreasing_fillcolor="#ff5570",
            whiskerwidth=0.35,
            hovertext=[
                (f"{ts.strftime('%b %d, %I:%M %p')} PT<br>"
                 f"O {o:.2f} · H {h:.2f} · L {l:.2f} · C {c:.2f}")
                for ts, o, h, l, c in zip(
                    bars.index, bars["Open"], bars["High"],
                    bars["Low"], bars["Close"])
            ],
            hoverinfo="text",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=x_pos, y=bars["VWAP"], mode="lines", name="VWAP",
            line=dict(color="#f5b82e", width=2.2),
            hovertemplate="VWAP $%{y:.2f}<extra></extra>",
        ), row=1, col=1)

        volume_colors = np.where(
            bars["Close"].to_numpy() >= bars["Open"].to_numpy(),
            "rgba(46,216,163,0.52)", "rgba(255,85,112,0.52)")
        fig.add_trace(go.Bar(
            x=x_pos, y=bars["Volume"], name="Volume",
            marker_color=volume_colors,
            hovertemplate="Volume %{y:,.0f}<extra></extra>",
        ), row=2, col=1)

        last_price = float(bars["Close"].iloc[-1])
        raw_low = float(bars["Low"].min())
        raw_high = float(bars["High"].max())
        chart_half_range = max((raw_high - raw_low) * 1.25,
                               last_price * 0.0055)
        view_low = min(raw_low, last_price - chart_half_range)
        view_high = max(raw_high, last_price + chart_half_range)

        candidates = [
            (float(k), float(v)) for k, v in zip(strikes, profile)
            if view_low <= float(k) <= view_high and float(v) != 0
        ]
        candidates.sort(key=lambda item: abs(item[1]), reverse=True)
        levels = candidates[:9]

        if levels:
            strength_max = max(abs(v) for _, v in levels) or 1.0
            bar_half_width = max(last_price * 0.000055,
                                 (view_high - view_low) * 0.008)
            for strike, value in levels:
                strength = abs(value) / strength_max
                positive = value >= 0
                color = "#42c963" if positive else "#c83252"
                fill = ("rgba(66,201,99,0.82)" if positive
                        else "rgba(200,50,82,0.82)")
                bar_length = 0.012 + 0.34 * (strength ** 0.72)
                bar_start = 0.995 - bar_length
                # Paper-referenced x coordinates keep these bars in the
                # reserved right-side exposure area while y follows price.
                fig.add_shape(
                    type="rect", xref="paper", yref="y",
                    x0=bar_start, x1=0.995,
                    y0=strike-bar_half_width, y1=strike+bar_half_width,
                    fillcolor=fill, line=dict(color=color, width=1.3),
                    layer="above",
                )
                fig.add_annotation(
                    x=bar_start-0.004, xref="paper", y=strike, yref="y",
                    text=_gex_value_label(value).replace("$", ""),
                    showarrow=False, xanchor="right", yanchor="middle",
                    font=dict(color=color, size=10, family="Consolas"),
                )

        fig.add_hline(
            y=last_price, line=dict(color="rgba(66,201,99,0.72)",
                                    width=1, dash="dot"),
            annotation_text=f"${last_price:,.2f}",
            annotation_position="right",
            annotation_font_color="#d9ffe3",
            annotation_bgcolor="#2d9d4a", row=1, col=1,
        )

        last = bars.iloc[-1]
        net_color = "#42c963" if total_gex >= 0 else "#c83252"
        title = (
            f"<b>{symbol}</b>  <span style='color:#7f8b99'>│</span>  "
            f"<b>{interval}</b>  <b>{(period or '1d').upper()}</b>  "
            f"<b>{dte_label}</b>  "
            f"<span style='color:#7f8b99'>│ O</span> "
            f"<span style='color:#42c963'>{last['Open']:.2f}</span>  "
            f"<span style='color:#7f8b99'>H</span> "
            f"<span style='color:#42c963'>{last['High']:.2f}</span>  "
            f"<span style='color:#7f8b99'>L</span> "
            f"<span style='color:#42c963'>{last['Low']:.2f}</span>  "
            f"<span style='color:#7f8b99'>C</span> "
            f"<span style='color:#42c963'>{last['Close']:.2f}</span>  "
            f"<span style='color:#7f8b99'>│ Net GEX</span> "
            f"<span style='color:{net_color}'>{_gex_value_label(total_gex)}</span>"
        )
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#111312",
            plot_bgcolor="#151716", height=670,
            margin=dict(t=54, b=34, l=16, r=58),
            title=dict(text=title, x=0.012, xanchor="left", y=0.975,
                       yanchor="top", font=dict(size=11, color="#e8edf2",
                                                family="Inter, Segoe UI")),
            xaxis_rangeslider_visible=False,
            hovermode="x", showlegend=False,
            font=dict(family="Inter, Segoe UI, sans-serif", color="#9ba8b7"),
        )
        # Compact chart-header pill.
        fig.add_shape(
            type="rect", xref="paper", yref="paper",
            x0=0.006, x1=0.39, y0=1.005, y1=1.073,
            fillcolor="rgba(8,10,9,0.92)",
            line=dict(color="rgba(255,255,255,0.10)", width=1),
            layer="below",
        )
        tick_step = max(1, len(bars) // 11)
        tick_idx = list(range(0, len(bars), tick_step))
        if tick_idx[-1] != len(bars) - 1:
            tick_idx.append(len(bars) - 1)
        multi_day = len(set(bars.index.date)) > 1
        tick_text = [
            bars.index[i].strftime("%b %d<br>%I:%M %p" if multi_day
                                   else "%I:%M %p")
            for i in tick_idx
        ]
        x_end = max(float(len(bars) * 1.78), float(len(bars) + 12))
        fig.update_xaxes(
            range=[-1, x_end], showgrid=True,
            gridcolor="rgba(255,255,255,0.035)",
            tickfont=dict(size=9, color="#727a75"),
            showspikes=True, spikecolor="rgba(255,255,255,0.28)",
            spikethickness=1, spikedash="dot",
        )
        fig.update_xaxes(
            tickmode="array", tickvals=tick_idx, ticktext=tick_text,
            showticklabels=True, row=2, col=1)
        fig.update_xaxes(showticklabels=False, row=1, col=1)
        fig.update_yaxes(
            range=[view_low, view_high], side="right",
            tickformat=".2f", showgrid=True,
            gridcolor="rgba(255,255,255,0.035)",
            tickfont=dict(size=9, color="#8b918d"),
            showline=True, linecolor="rgba(255,255,255,0.35)",
            zeroline=False, row=1, col=1,
        )
        fig.update_yaxes(
            side="right", showgrid=True,
            gridcolor="rgba(255,255,255,0.025)",
            tickformat="~s", showticklabels=False, title="", row=2, col=1,
        )
        return fig

    @app.callback(
        [Output("gex-auto-refresh", "interval"),
         Output("gex-auto-refresh", "disabled")],
        Input("gex-refresh-interval", "value"),
    )
    def configure_gex_chart_refresh(refresh_value):
        intervals = {
            "30s": 30_000,
            "1m": 60_000,
            "2m": 120_000,
            "5m": 300_000,
        }
        if refresh_value not in intervals:
            return 30_000, True
        return intervals[refresh_value], False

    @app.callback(
        Output("gex-market-chart", "figure"),
        [Input("gex-market-store", "data"),
         Input("gex-auto-refresh", "n_intervals"),
         Input("gex-refresh-interval", "value")],
        prevent_initial_call=True,
    )
    def refresh_gex_market_chart(market_data, _refresh_tick, _refresh_value):
        data = market_data or {}
        if data.get("error"):
            return _gex_empty_fig(str(data["error"]), 670)
        if not data.get("symbol"):
            return _gex_empty_fig(
                "Build GEX to load candles, volume and gamma levels", 670)
        return _build_gex_price_map(
            data["symbol"], data.get("strikes") or [],
            data.get("profile") or [], float(data.get("total_gex") or 0.0),
            data.get("flip"), period=data.get("period") or "1d",
            interval=data.get("interval") or "5m", day=data.get("day"),
            dte_label=data.get("dte_label") or "all DTEs",
        )

    @app.callback(
        [Output("gex-status", "children"),
         Output("gex-summary", "children"),
         Output("gex-market-store", "data"),
         Output("gex-timeseries", "figure"),
         Output("gex-history-cloud", "figure"),
         Output("gex-heatmap", "figure"),
         Output("gex-profile", "figure"),
         Output("gex-scenario", "figure"),
         Output("gex-expiry-profile", "figure"),
         Output("gex-levels-table", "data"),
         Output("gex-walls", "children")],
        Input("gex-build-btn", "n_clicks"),
        [State("gex-symbol", "value"),
         State("gex-mode", "value"),
         State("gex-day", "date"),
         State("gex-timeframe", "value"),
         State("gex-max-exps", "value"),
         State("gex-dtes", "value"),
         State("gex-window-pct", "value"),
         State("gex-strike-bin", "value"),
         State("gex-risk-free", "value"),
         State("gex-chart-period", "value")],
        prevent_initial_call=True,
    )
    def build_gex_heatmap(_n, symbol, mode, day, timeframe,
                          max_exps, contract_dtes, window_pct, strike_bin,
                          risk_free_pct, chart_period):

        sym = (symbol or "").strip().upper()
        if not sym:
            return _gex_empty_response("Enter an optionable symbol first.")

        try:
            n_exps = int(max_exps) if max_exps else 8
        except (TypeError, ValueError):
            n_exps = 8
        n_exps = max(1, min(30, n_exps))

        selected_dtes: list[int] = []
        for value in contract_dtes or []:
            try:
                dte = int(value)
            except (TypeError, ValueError):
                continue
            if dte >= 0:
                selected_dtes.append(dte)
        selected_dtes = sorted(set(selected_dtes))
        dte_label = (", ".join(f"{d}DTE" for d in selected_dtes)
                     if selected_dtes else "all DTEs")

        try:
            win_pct = float(window_pct) / 100.0 if window_pct else 0.20
        except (TypeError, ValueError):
            win_pct = 0.20
        win_pct = max(0.02, min(0.60, win_pct))

        bin_val: float | None = None
        try:
            if strike_bin is not None and float(strike_bin) > 0:
                bin_val = float(strike_bin)
        except (TypeError, ValueError):
            bin_val = None

        try:
            risk_free = float(risk_free_pct) / 100.0
        except (TypeError, ValueError):
            risk_free = 0.045
        risk_free = max(0.0, min(0.20, risk_free))

        replay_mode = (mode == "replay")

        # ------------------------------------------------------------------
        # INTRADAY REPLAY MODE
        # ------------------------------------------------------------------
        if replay_mode:
            if not day:
                msg = ("Pick a Day to replay (yfinance has 1m for last ~7d, "
                       "5m / 15m / 30m for ~60d).")
                return _gex_empty_response(msg)

            day_str = str(day)[:10]
            tf = (timeframe or "5m").lower()

            try:
                ir = _compute_intraday_gex(
                    symbol=sym, day=day_str, interval=tf,
                    max_expirations=n_exps,
                    strike_window_pct=win_pct,
                    risk_free=risk_free,
                    strike_bin=bin_val,
                    dtes=selected_dtes,
                )
            except Exception as exc:
                msg = f"Intraday GEX failed for {sym} on {day_str}: {exc}"
                return _gex_empty_response(msg)

            if not ir.timestamps or not ir.strikes or not ir.heatmap:
                note = " | ".join(ir.notes) if ir.notes else "no data"
                msg = f"No replay data for {sym} on {day_str}. ({note})"
                return _gex_empty_response(msg)

            scale_mm = 1e6
            spot_final = ir.final_spot
            flip_final = ir.final_flip
            total_mm = ir.final_total_gex / scale_mm

            cards = [
                _card("SPOT @ CLOSE", f"${spot_final:,.2f}",
                      f"{day_str} · {tf}", _cyan),
                _card("NET GEX @ CLOSE", f"{total_mm:,.1f}M",
                      "$ gamma at last bar",
                      _green if total_mm >= 0 else _red),
                _card("FLIP @ CLOSE",
                      f"${flip_final:,.2f}" if flip_final is not None else "n/a",
                      "zero-gamma level at session end",
                      _green if (flip_final is not None and spot_final >= flip_final) else _red),
                _card("REPLAY COVERAGE",
                      f"{len(ir.timestamps)} bars × {len(ir.strikes)} K",
                      f"{len(ir.expirations)} exps · {dte_label}", _cyan),
            ]

            # ---- Time-series chart ---------------------------------------
            net_mm = [v / scale_mm for v in ir.net_gex_series]
            ts_fig = go.Figure()
            ts_fig.add_trace(go.Scatter(
                x=ir.timestamps, y=net_mm,
                mode="lines", name="Net GEX ($M)",
                line=dict(color="#4ecdc4", width=2),
                yaxis="y",
                hovertemplate="%{x}<br>Net GEX: %{y:.1f}M<extra></extra>",
            ))
            ts_fig.add_trace(go.Scatter(
                x=ir.timestamps, y=ir.spot_series,
                mode="lines", name="Spot",
                line=dict(color="#ffa502", width=1.5, dash="dot"),
                yaxis="y2",
                hovertemplate="%{x}<br>Spot: $%{y:.2f}<extra></extra>",
            ))
            ts_fig.add_hline(
                y=0, line=dict(color="rgba(255,255,255,0.25)", width=1),
            )
            ts_fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#1a1a2e",
                plot_bgcolor="#1a1a2e",
                height=260,
                margin=dict(t=28, b=35, l=55, r=55),
                title=dict(
                    text=f"{sym} — Net GEX vs Spot · {day_str} ({tf})",
                    font=dict(size=12, color="#ddd"),
                ),
                xaxis=dict(title="", tickfont=dict(size=9)),
                yaxis=dict(title=dict(text="Net GEX ($M)",
                                       font=dict(color="#4ecdc4")),
                           tickfont=dict(color="#4ecdc4", size=10)),
                yaxis2=dict(title=dict(text="Spot ($)",
                                        font=dict(color="#ffa502")),
                            tickfont=dict(color="#ffa502", size=10),
                            overlaying="y", side="right",
                            tickprefix="$"),
                legend=dict(orientation="h", yanchor="bottom",
                            y=1.02, xanchor="right", x=1,
                            font=dict(size=10)),
            )

            wall_cloud_fig = _build_gex_wall_cloud(
                ir, sym, day_str, tf)

            # ---- Strike × Time heatmap -----------------------------------
            z_mm = [[v / scale_mm for v in row] for row in ir.heatmap]
            z_arr = np.array(z_mm) if z_mm else np.zeros((1, 1))
            z_abs_max = float(np.nanmax(np.abs(z_arr))) if z_arr.size else 1.0
            if z_abs_max <= 0:
                z_abs_max = 1.0

            heatmap_fig = go.Figure()
            heatmap_fig.add_trace(go.Heatmap(
                x=ir.timestamps, y=ir.strikes, z=z_mm,
                zmid=0, zmin=-z_abs_max, zmax=z_abs_max,
                colorscale=[
                    [0.0, "#ff4757"], [0.5, "#1a1a2e"], [1.0, "#00d47e"],
                ],
                colorbar=dict(
                    title=dict(text="GEX ($M)",
                               font=dict(color="#ddd", size=11)),
                    tickfont=dict(color="#bbb", size=10),
                    thickness=10,
                ),
                hovertemplate=("Time: %{x}<br>Strike: $%{y:.2f}"
                               "<br>GEX: %{z:.2f} M<extra></extra>"),
            ))
            heatmap_fig.add_hline(
                y=spot_final, line=dict(color="#4ecdc4", width=2, dash="dash"),
                annotation_text=f"Spot ${spot_final:,.2f}",
                annotation_position="top right",
                annotation_font_color="#4ecdc4",
            )
            if flip_final is not None and min(ir.strikes) <= flip_final <= max(ir.strikes):
                heatmap_fig.add_hline(
                    y=flip_final, line=dict(color="#ffa502", width=2, dash="dot"),
                    annotation_text=f"Flip ${flip_final:,.2f}",
                    annotation_position="bottom right",
                    annotation_font_color="#ffa502",
                )
            heatmap_fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#1a1a2e",
                plot_bgcolor="#1a1a2e",
                height=520,
                margin=dict(t=30, b=60, l=70, r=15),
                xaxis=dict(title="Time of Day (PT)", tickangle=-35,
                           tickfont=dict(size=9)),
                yaxis=dict(title="Strike", tickprefix="$",
                           tickfont=dict(size=10)),
                title=dict(
                    text=f"{sym} — GEX by Strike × Time · {day_str} ({tf})",
                    font=dict(size=13, color="#ddd"),
                ),
            )

            # ---- Per-strike profile at close of session ------------------
            prof_mm = [v / scale_mm for v in ir.final_profile]
            bar_colors = ["#00d47e" if v >= 0 else "#ff4757" for v in prof_mm]
            profile_fig = go.Figure()
            profile_fig.add_trace(go.Bar(
                x=prof_mm, y=ir.strikes, orientation="h",
                marker_color=bar_colors,
                hovertemplate=("Strike: $%{y:.2f}<br>Net GEX: "
                               "%{x:.2f} M<extra></extra>"),
                name="Net GEX",
            ))
            profile_fig.add_hline(
                y=spot_final, line=dict(color="#4ecdc4", width=2, dash="dash"),
                annotation_text=f"Spot ${spot_final:,.2f}",
                annotation_position="top right",
                annotation_font_color="#4ecdc4",
            )
            if flip_final is not None and min(ir.strikes) <= flip_final <= max(ir.strikes):
                profile_fig.add_hline(
                    y=flip_final, line=dict(color="#ffa502", width=2, dash="dot"),
                    annotation_text=f"Flip ${flip_final:,.2f}",
                    annotation_position="bottom right",
                    annotation_font_color="#ffa502",
                )
            profile_fig.add_vline(
                x=0, line=dict(color="rgba(255,255,255,0.25)", width=1),
            )
            profile_fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#1a1a2e",
                plot_bgcolor="#1a1a2e",
                height=520,
                margin=dict(t=30, b=50, l=55, r=15),
                xaxis=dict(title="Net GEX ($M)", zeroline=False),
                yaxis=dict(title="Strike", tickprefix="$"),
                showlegend=False,
                title=dict(text=f"Net GEX by Strike · session close",
                           font=dict(size=13, color="#ddd")),
            )

            scenario_fig = go.Figure()
            scenario_fig.add_trace(go.Scatter(
                x=ir.timestamps, y=ir.spot_series, mode="lines",
                name="Spot", line=dict(color="#4ecdc4", width=2),
                hovertemplate="%{x}<br>Spot: $%{y:.2f}<extra></extra>",
            ))
            scenario_fig.add_trace(go.Scatter(
                x=ir.timestamps, y=ir.flip_series, mode="lines+markers",
                name="Gamma flip", line=dict(color="#ffa502", width=2),
                connectgaps=False,
                hovertemplate="%{x}<br>Flip: $%{y:.2f}<extra></extra>",
            ))
            scenario_fig.update_layout(
                template="plotly_dark", paper_bgcolor="#1a1a2e",
                plot_bgcolor="#1a1a2e", height=360,
                margin=dict(t=38, b=45, l=60, r=20),
                title=dict(text="Intraday Spot vs Repriced Gamma Flip",
                           font=dict(size=13, color="#ddd")),
                xaxis=dict(title="Time (PT)", tickfont=dict(size=9)),
                yaxis=dict(title="Price", tickprefix="$"),
                legend=dict(orientation="h", y=1.05, x=1, xanchor="right"),
            )
            expiry_fig = _gex_empty_fig(
                "Expiration decomposition is available in Snapshot mode", 360)
            level_rows = [
                {"strike": round(float(k), 2), "call_gex": None,
                 "put_gex": None, "net_gex": round(float(v) / scale_mm, 4),
                 "call_oi": None, "put_oi": None}
                for k, v in zip(ir.strikes, ir.final_profile)
            ]

            walls_div = _gex_walls_block(
                spot_final, flip_final, ir.call_walls, ir.put_walls)
            market_data = {
                "symbol": sym,
                "strikes": ir.strikes,
                "profile": ir.final_profile,
                "total_gex": ir.final_total_gex,
                "flip": flip_final,
                "period": "1d",
                "interval": tf,
                "day": day_str,
                "dte_label": dte_label,
            }

            notes_txt = ""
            if ir.notes:
                notes_txt = "  Notes: " + " | ".join(ir.notes[:3])
            status = (f"Replay built for {sym} on {day_str} ({tf}): "
                      f"{len(ir.timestamps)} bars, {len(ir.strikes)} strikes, "
                      f"{ir.rows:,} contract rows, {dte_label}. "
                      f"OI/IV held fixed at current "
                      f"chain snapshot.{notes_txt}")

            return (status, cards, market_data, ts_fig, wall_cloud_fig,
                    heatmap_fig, profile_fig, scenario_fig, expiry_fig,
                    level_rows, walls_div)

        # ------------------------------------------------------------------
        # SNAPSHOT MODE (default)
        # ------------------------------------------------------------------
        try:
            result = _compute_gex(
                symbol=sym,
                max_expirations=n_exps,
                strike_window_pct=win_pct,
                risk_free=risk_free,
                strike_bin=bin_val,
                dtes=selected_dtes,
            )
        except Exception as exc:
            msg = f"GEX computation failed for {sym}: {exc}"
            return _gex_empty_response(msg)

        if not result.strikes or not result.heatmap:
            note = " | ".join(result.notes) if result.notes else "no data"
            msg = f"No usable options data for {sym}. ({note})"
            return _gex_empty_response(msg)

        spot = result.spot
        strikes = result.strikes
        exps = result.expirations
        heat = result.heatmap
        profile = result.profile

        scale_mm = 1e6
        z_mm = [[v / scale_mm for v in row] for row in heat]
        prof_mm = [v / scale_mm for v in profile]
        total_mm = result.total_gex / scale_mm

        flip = result.flip_price
        flip_txt = f"${flip:,.2f}" if flip is not None else "n/a"

        cards = [
            _card("SPOT", f"${spot:,.2f}",
                  f"as of {result.as_of}", _cyan),
            _card("NET GEX", f"{total_mm:,.1f}M",
                  (f"Call {result.call_gex/scale_mm:+.1f}M · "
                   f"Put {result.put_gex/scale_mm:+.1f}M / 1%"),
                  _green if total_mm >= 0 else _red),
            _card("ZERO-GAMMA FLIP", flip_txt,
                  "above = long γ / below = short γ",
                  _green if (flip is not None and spot >= flip) else _red),
            _card("CHAIN COVERAGE",
                  f"{len(exps)} exps × {len(strikes)} K",
                  f"{result.rows:,} rows · {dte_label}", _cyan),
        ]

        # Snapshot mode: time-series chart is just a hint placeholder.
        ts_fig = _gex_empty_fig(
            "Switch to 'Intraday Replay' to see net GEX evolve through the day",
            h=260)
        wall_cloud_fig = _gex_empty_fig(
            "Switch to 'Intraday Replay' to build the modeled GEX wall cloud",
            h=560)

        z_arr = np.array(z_mm) if z_mm else np.zeros((1, 1))
        z_abs_max = float(np.nanmax(np.abs(z_arr))) if z_arr.size else 1.0
        if z_abs_max <= 0:
            z_abs_max = 1.0

        heatmap_fig = go.Figure()
        heatmap_exp_labels = [
            f"{exp}<br>{dte}DTE"
            for exp, dte in zip(exps, result.expiration_dtes)
        ]
        heatmap_fig.add_trace(go.Heatmap(
            x=heatmap_exp_labels, y=strikes, z=z_mm,
            zmid=0, zmin=-z_abs_max, zmax=z_abs_max,
            colorscale=[
                [0.0, "#ff4757"], [0.5, "#1a1a2e"], [1.0, "#00d47e"],
            ],
            colorbar=dict(
                title=dict(text="GEX ($M)",
                           font=dict(color="#ddd", size=11)),
                tickfont=dict(color="#bbb", size=10),
                thickness=10,
            ),
            hovertemplate=("Expiry: %{x}<br>Strike: $%{y:.2f}"
                           "<br>GEX: %{z:.2f} M<extra></extra>"),
        ))
        heatmap_fig.add_hline(
            y=spot, line=dict(color="#4ecdc4", width=2, dash="dash"),
            annotation_text=f"Spot ${spot:,.2f}",
            annotation_position="top right",
            annotation_font_color="#4ecdc4",
        )
        if flip is not None and min(strikes) <= flip <= max(strikes):
            heatmap_fig.add_hline(
                y=flip, line=dict(color="#ffa502", width=2, dash="dot"),
                annotation_text=f"Flip ${flip:,.2f}",
                annotation_position="bottom right",
                annotation_font_color="#ffa502",
            )
        heatmap_fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e",
            height=520,
            margin=dict(t=30, b=60, l=70, r=15),
            xaxis=dict(title="Expiration", tickangle=-35,
                       tickfont=dict(size=10)),
            yaxis=dict(title="Strike", tickprefix="$",
                       tickfont=dict(size=10)),
            title=dict(text=f"{sym} — GEX by Strike × Expiration",
                       font=dict(size=13, color="#ddd")),
        )

        profile_fig = go.Figure()
        profile_fig.add_trace(go.Bar(
            x=[v / scale_mm for v in result.call_profile],
            y=strikes, orientation="h", marker_color="#00d47e",
            opacity=0.72, name="Call GEX",
            hovertemplate="Strike: $%{y:.2f}<br>Call: %{x:.3f}M<extra></extra>",
        ))
        profile_fig.add_trace(go.Bar(
            x=[v / scale_mm for v in result.put_profile],
            y=strikes, orientation="h", marker_color="#ff4757",
            opacity=0.72, name="Put GEX",
            hovertemplate="Strike: $%{y:.2f}<br>Put: %{x:.3f}M<extra></extra>",
        ))
        profile_fig.add_trace(go.Scatter(
            x=prof_mm, y=strikes, mode="lines",
            line=dict(color="#f1f2f6", width=1.5), name="Net GEX",
            hovertemplate=("Strike: $%{y:.2f}<br>Net: "
                           "%{x:.3f}M<extra></extra>"),
        ))
        profile_fig.add_hline(
            y=spot, line=dict(color="#4ecdc4", width=2, dash="dash"),
            annotation_text=f"Spot ${spot:,.2f}",
            annotation_position="top right",
            annotation_font_color="#4ecdc4",
        )
        if flip is not None and min(strikes) <= flip <= max(strikes):
            profile_fig.add_hline(
                y=flip, line=dict(color="#ffa502", width=2, dash="dot"),
                annotation_text=f"Flip ${flip:,.2f}",
                annotation_position="bottom right",
                annotation_font_color="#ffa502",
            )
        profile_fig.add_vline(
            x=0, line=dict(color="rgba(255,255,255,0.25)", width=1),
        )
        profile_fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e",
            height=520,
            margin=dict(t=30, b=50, l=55, r=15),
            xaxis=dict(title="Net GEX ($M)", zeroline=False),
            yaxis=dict(title="Strike", tickprefix="$"),
            barmode="relative",
            legend=dict(orientation="h", y=1.04, x=1, xanchor="right",
                        font=dict(size=9)),
            title=dict(text="Call / Put / Net GEX by Strike",
                       font=dict(size=13, color="#ddd")),
        )

        scenario_mm = [v / scale_mm for v in result.scenario_gex]
        scenario_fig = go.Figure()
        scenario_fig.add_trace(go.Scatter(
            x=result.scenario_spots, y=scenario_mm,
            mode="lines", line=dict(color="#4ecdc4", width=2.5),
            fill="tozeroy", fillcolor="rgba(78,205,196,0.08)",
            name="Total GEX",
            hovertemplate="Spot: $%{x:.2f}<br>Net GEX: %{y:.2f}M<extra></extra>",
        ))
        scenario_fig.add_hline(
            y=0, line=dict(color="rgba(255,255,255,0.35)", width=1))
        scenario_fig.add_vline(
            x=spot, line=dict(color="#4ecdc4", width=2, dash="dash"),
            annotation_text=f"Spot ${spot:,.2f}",
            annotation_font_color="#4ecdc4")
        if flip is not None:
            scenario_fig.add_vline(
                x=flip, line=dict(color="#ffa502", width=2, dash="dot"),
                annotation_text=f"Flip ${flip:,.2f}",
                annotation_font_color="#ffa502")
        scenario_fig.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=360,
            margin=dict(t=42, b=48, l=62, r=20),
            title=dict(text="Whole-Chain Gamma Regime Across Spot",
                       font=dict(size=13, color="#ddd")),
            xaxis=dict(title="Hypothetical Underlying Price", tickprefix="$"),
            yaxis=dict(title="Net GEX ($M / 1% move)"),
            showlegend=False,
        )

        expiry_call = [r["call_gex"] / scale_mm for r in result.expiration_gex]
        expiry_put = [r["put_gex"] / scale_mm for r in result.expiration_gex]
        expiry_net = [r["net_gex"] / scale_mm for r in result.expiration_gex]
        expiry_labels = [
            f"{r['expiry']}<br>{r.get('dte', '?')}DTE"
            for r in result.expiration_gex
        ]
        expiry_fig = go.Figure()
        expiry_fig.add_trace(go.Bar(
            x=expiry_labels, y=expiry_call, name="Call GEX",
            marker_color="#00d47e",
            hovertemplate="%{x}<br>Call: %{y:.2f}M<extra></extra>"))
        expiry_fig.add_trace(go.Bar(
            x=expiry_labels, y=expiry_put, name="Put GEX",
            marker_color="#ff4757",
            hovertemplate="%{x}<br>Put: %{y:.2f}M<extra></extra>"))
        expiry_fig.add_trace(go.Scatter(
            x=expiry_labels, y=expiry_net, name="Net GEX",
            mode="lines+markers", line=dict(color="#f1f2f6", width=2),
            hovertemplate="%{x}<br>Net: %{y:.2f}M<extra></extra>"))
        expiry_fig.add_hline(
            y=0, line=dict(color="rgba(255,255,255,0.3)", width=1))
        expiry_fig.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=360, barmode="relative",
            margin=dict(t=42, b=65, l=60, r=20),
            title=dict(text="GEX Contribution by Expiration",
                       font=dict(size=13, color="#ddd")),
            xaxis=dict(title="Expiration", tickangle=-35, tickfont=dict(size=9)),
            yaxis=dict(title="GEX ($M / 1% move)"),
            legend=dict(orientation="h", y=1.05, x=1, xanchor="right",
                        font=dict(size=9)),
        )

        level_rows = [
            {"strike": round(float(k), 2),
             "call_gex": round(float(cg) / scale_mm, 4),
             "put_gex": round(float(pg) / scale_mm, 4),
             "net_gex": round(float(ng) / scale_mm, 4),
             "call_oi": int(round(float(coi))),
             "put_oi": int(round(float(poi)))}
            for k, cg, pg, ng, coi, poi in zip(
                strikes, result.call_profile, result.put_profile,
                result.profile, result.call_oi_profile, result.put_oi_profile)
        ]

        walls_div = _gex_walls_block(
            spot, flip, result.call_walls, result.put_walls)
        market_data = {
            "symbol": sym,
            "strikes": strikes,
            "profile": profile,
            "total_gex": result.total_gex,
            "flip": flip,
            "period": chart_period or "1d",
            "interval": timeframe or "5m",
            "day": None,
            "dte_label": dte_label,
        }

        notes_txt = ""
        if result.notes:
            notes_txt = "  Notes: " + " | ".join(result.notes[:3])
        status = (f"GEX built for {sym}: {len(exps)} expirations, "
                  f"{len(strikes)} strikes, {result.rows:,} contract rows. "
                  f"Spot ${spot:,.2f}; risk-free {risk_free*100:.2f}%. "
                  f"Filter: {dte_label}. All GEX values are $ per 1% move."
                  f"{notes_txt}")

        return (status, cards, market_data, ts_fig, wall_cloud_fig,
                heatmap_fig, profile_fig, scenario_fig, expiry_fig,
                level_rows, walls_div)

    # =====================================================================
    # GEX ALPACA — isolated comparison workspace using Alpaca-only inputs
    # =====================================================================

    @app.callback(
        [Output("gex-alpaca-auto-refresh", "interval"),
         Output("gex-alpaca-auto-refresh", "disabled")],
        Input("gex-alpaca-refresh-interval", "value"),
    )
    def configure_gex_alpaca_refresh(refresh_value):
        intervals = {
            "30s": 30_000, "1m": 60_000, "2m": 120_000,
            "5m": 300_000,
        }
        if refresh_value not in intervals:
            return 30_000, True
        return intervals[refresh_value], False

    @app.callback(
        Output("gex-alpaca-market-chart", "figure"),
        [Input("gex-alpaca-market-store", "data"),
         Input("gex-alpaca-auto-refresh", "n_intervals"),
         Input("gex-alpaca-refresh-interval", "value")],
        prevent_initial_call=True,
    )
    def refresh_gex_alpaca_market_chart(market_data, _tick, _refresh_value):
        data = market_data or {}
        if data.get("error"):
            return _gex_empty_fig(str(data["error"]), 670)
        if not data.get("symbol"):
            return _gex_empty_fig(
                "Build Alpaca GEX to load Alpaca candles and gamma levels", 670)
        try:
            bars = _fetch_alpaca_bars(
                data["symbol"], period=data.get("period") or "1d",
                interval=data.get("interval") or "5m")
        except Exception as exc:
            return _gex_empty_fig(f"Alpaca price candles failed: {exc}", 670)
        return _build_gex_price_map(
            data["symbol"], data.get("strikes") or [],
            data.get("profile") or [], float(data.get("total_gex") or 0),
            data.get("flip"), period=data.get("period") or "1d",
            interval=data.get("interval") or "5m",
            dte_label=data.get("dte_label") or "all DTEs",
            bars_override=bars,
        )

    @app.callback(
        [Output("gex-alpaca-status", "children"),
         Output("gex-alpaca-summary", "children"),
         Output("gex-alpaca-market-store", "data"),
         Output("gex-alpaca-timeseries", "figure"),
         Output("gex-alpaca-history-cloud", "figure"),
         Output("gex-alpaca-heatmap", "figure"),
         Output("gex-alpaca-profile", "figure"),
         Output("gex-alpaca-scenario", "figure"),
         Output("gex-alpaca-expiry-profile", "figure"),
         Output("gex-alpaca-levels-table", "data"),
         Output("gex-alpaca-walls", "children")],
        Input("gex-alpaca-build-btn", "n_clicks"),
        [State("gex-alpaca-symbol", "value"),
         State("gex-alpaca-mode", "value"),
         State("gex-alpaca-day", "date"),
         State("gex-alpaca-timeframe", "value"),
         State("gex-alpaca-max-exps", "value"),
         State("gex-alpaca-dtes", "value"),
         State("gex-alpaca-window-pct", "value"),
         State("gex-alpaca-strike-bin", "value"),
         State("gex-alpaca-risk-free", "value"),
         State("gex-alpaca-chart-period", "value")],
        prevent_initial_call=True,
    )
    def build_gex_alpaca(_clicks, symbol, mode, _day, timeframe,
                         max_exps, contract_dtes, window_pct, strike_bin,
                         risk_free_pct, chart_period):
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return _gex_empty_response("Enter an optionable symbol first.")
        try:
            expiration_count = max(1, min(30, int(max_exps or 8)))
        except (TypeError, ValueError):
            expiration_count = 8
        try:
            window = max(.02, min(.60, float(window_pct or 20)/100))
        except (TypeError, ValueError):
            window = .20
        try:
            rate = max(0, min(.20, float(risk_free_pct or 4.5)/100))
        except (TypeError, ValueError):
            rate = .045
        try:
            bin_value = float(strike_bin) if strike_bin not in (None, "") else None
            if bin_value is not None and bin_value <= 0:
                bin_value = None
        except (TypeError, ValueError):
            bin_value = None
        selected_dtes = []
        for value in contract_dtes or []:
            try:
                parsed = int(value)
                if parsed >= 0:
                    selected_dtes.append(parsed)
            except (TypeError, ValueError):
                continue
        selected_dtes = sorted(set(selected_dtes))
        dte_label = (", ".join(f"{value}DTE" for value in selected_dtes)
                     if selected_dtes else "all DTEs")

        try:
            result = _compute_gex_alpaca(
                symbol=symbol, max_expirations=expiration_count,
                strike_window_pct=window, risk_free=rate,
                strike_bin=bin_value, dtes=selected_dtes,
            )
        except Exception as exc:
            return _gex_empty_response(
                f"Alpaca GEX computation failed for {symbol}: {exc}")
        if not result.strikes or not result.heatmap:
            note = " | ".join(result.notes) if result.notes else "no data"
            return _gex_empty_response(
                f"No usable Alpaca options data for {symbol}. ({note})")

        (cards, time_figure, heatmap_figure, profile_figure,
         scenario_figure, expiration_figure, level_rows,
         walls) = _gex_snapshot_visuals(
             result, symbol, dte_label, "Alpaca")
        wall_cloud_figure = _gex_empty_fig(
            "Intraday wall cloud is available in the yfinance GEX Replay mode",
            560)
        market_data = {
            "symbol": symbol,
            "strikes": result.strikes,
            "profile": result.profile,
            "total_gex": result.total_gex,
            "flip": result.flip_price,
            "period": chart_period or "1d",
            "interval": timeframe or "5m",
            "day": None,
            "dte_label": dte_label,
            "provider": "alpaca",
        }
        notes = " | ".join(result.notes[:4])
        replay_note = (" Replay is intentionally disabled for this source "
                       "comparison; showing the current Alpaca snapshot."
                       if mode == "replay" else "")
        status = (
            f"Alpaca GEX built for {symbol}: {len(result.expirations)} "
            f"expirations, {len(result.strikes)} strikes, "
            f"{result.rows:,} contract rows. Spot ${result.spot:,.2f}; "
            f"filter: {dte_label}. {notes}{replay_note}"
        )
        return (
            status, cards, market_data, time_figure, wall_cloud_figure,
            heatmap_figure, profile_figure, scenario_figure,
            expiration_figure, level_rows, walls,
        )

    # =====================================================================
    # IV WALLS — open-interest-weighted vega concentration by strike
    # =====================================================================

    @app.callback(
        [Output("ivw-status", "children"),
         Output("ivw-summary", "children"),
         Output("ivw-market-chart", "figure"),
         Output("ivw-profile", "figure"),
         Output("ivw-skew", "figure"),
         Output("ivw-heatmap", "figure"),
         Output("ivw-term", "figure"),
         Output("ivw-table", "data")],
        Input("ivw-build-btn", "n_clicks"),
        [State("ivw-symbol", "value"),
         State("ivw-provider", "value"),
         State("ivw-max-exps", "value"),
         State("ivw-dtes", "value"),
         State("ivw-window-pct", "value"),
         State("ivw-risk-free", "value")],
        prevent_initial_call=True,
    )
    def build_iv_walls(_clicks, symbol, provider, max_exps, contract_dtes,
                       window_pct, risk_free_pct):
        def empty(message: str, height: int = 430):
            return _gex_empty_fig(message, height)

        symbol = (symbol or "").strip().upper()
        if not symbol:
            message = "Enter an optionable symbol first."
            return (message, [], empty(message, 650), empty(message, 520),
                    empty(message, 520), empty(message), empty(message), [])
        try:
            expiration_count = max(1, min(20, int(max_exps or 8)))
        except (TypeError, ValueError):
            expiration_count = 8
        try:
            window = max(.02, min(.60, float(window_pct or 15)/100))
        except (TypeError, ValueError):
            window = .15
        try:
            rate = max(0, min(.20, float(risk_free_pct or 4.5)/100))
        except (TypeError, ValueError):
            rate = .045
        selected_dtes = []
        for value in contract_dtes or []:
            try:
                parsed = int(value)
                if parsed >= 0:
                    selected_dtes.append(parsed)
            except (TypeError, ValueError):
                continue
        selected_dtes = sorted(set(selected_dtes))
        dte_label = (", ".join(f"{value}DTE" for value in selected_dtes)
                     if selected_dtes else "all DTEs")
        try:
            result = _compute_iv_walls(
                symbol=symbol, provider=provider,
                max_expirations=expiration_count,
                strike_window_pct=window, risk_free=rate,
                dtes=selected_dtes,
            )
        except Exception as exc:
            message = f"IV Walls failed for {symbol}: {exc}"
            return (message, [], empty(message, 650), empty(message, 520),
                    empty(message, 520), empty(message), empty(message), [])
        if not result.strikes:
            notes = " | ".join(result.notes) if result.notes else "no data"
            message = f"No usable IV/OI data for {symbol}. {notes}"
            return (message, [], empty(message, 650), empty(message, 520),
                    empty(message, 520), empty(message), empty(message), [])

        provider_label = "Alpaca" if result.provider == "alpaca" else "yfinance"
        call_wall = result.call_walls[0] if result.call_walls else None
        put_wall = result.put_walls[0] if result.put_walls else None
        total_vex = result.total_call_vex + result.total_put_vex
        nearest_index = min(
            range(len(result.strikes)),
            key=lambda index: abs(result.strikes[index]-result.spot))
        near_call_iv = result.call_iv[nearest_index]
        near_put_iv = result.put_iv[nearest_index]
        skew_points = ((near_put_iv-near_call_iv)*100
                       if near_call_iv is not None and near_put_iv is not None
                       else None)
        cards = [
            _card("SPOT", f"${result.spot:,.2f}",
                  f"{provider_label} · {result.as_of}", _cyan),
            _card("CALL IV WALL",
                  f"${call_wall['strike']:,.2f}" if call_wall else "n/a",
                  (_gex_value_label(call_wall["vex"]) + " / 1 IV pt")
                  if call_wall else "no wall", _green),
            _card("PUT IV WALL",
                  f"${put_wall['strike']:,.2f}" if put_wall else "n/a",
                  (_gex_value_label(put_wall["vex"]) + " / 1 IV pt")
                  if put_wall else "no wall", _red),
            _card("TOTAL VEGA CONCENTRATION", _gex_value_label(total_vex),
                  "$ value change / 1 IV point", _orange),
            _card("NEAR-ATM PUT–CALL IV",
                  f"{skew_points:+.2f} pts" if skew_points is not None else "n/a",
                  "positive = put IV premium",
                  _red if skew_points is not None and skew_points > 0 else _green),
        ]

        # Current-snapshot wall overlay on intraday candles. These ribbons
        # intentionally span the visible session and do not imply that the
        # wall had the same value earlier in the day.
        try:
            if result.provider == "alpaca":
                wall_bars = _fetch_alpaca_bars(symbol, period="1d", interval="5m")
            else:
                wall_bars = yf.download(
                    symbol, period="1d", interval="5m", auto_adjust=False,
                    prepost=False, progress=False, threads=False)
                if isinstance(wall_bars.columns, pd.MultiIndex):
                    wall_bars.columns = wall_bars.columns.get_level_values(0)
            wall_bars = wall_bars.copy().dropna(
                subset=["Open", "High", "Low", "Close"])
        except Exception:
            wall_bars = pd.DataFrame()

        if wall_bars.empty:
            market_figure = empty(
                f"{provider_label} candles unavailable; wall analytics are still shown below",
                650)
        else:
            for column in ("Open", "High", "Low", "Close", "Volume"):
                wall_bars[column] = pd.to_numeric(
                    wall_bars[column], errors="coerce")
            wall_bars = wall_bars.dropna(
                subset=["Open", "High", "Low", "Close"])
            wall_bars["Volume"] = wall_bars["Volume"].fillna(0)
            wall_x = np.arange(len(wall_bars), dtype=float)
            market_figure = make_subplots(
                rows=2, cols=1, shared_xaxes=True, vertical_spacing=.025,
                row_heights=[.78, .22])
            market_figure.add_trace(go.Candlestick(
                x=wall_x, open=wall_bars["Open"], high=wall_bars["High"],
                low=wall_bars["Low"], close=wall_bars["Close"],
                increasing_line_color=_green, increasing_fillcolor=_green,
                decreasing_line_color=_red, decreasing_fillcolor=_red,
                name=symbol), row=1, col=1)
            volume_colors = np.where(
                wall_bars["Close"].to_numpy() >= wall_bars["Open"].to_numpy(),
                "rgba(0,212,126,.48)", "rgba(255,71,87,.48)")
            market_figure.add_trace(go.Bar(
                x=wall_x, y=wall_bars["Volume"], marker_color=volume_colors,
                name="Volume", hovertemplate="Volume %{y:,.0f}<extra></extra>"),
                row=2, col=1)

            shown_calls = result.call_walls[:4]
            shown_puts = result.put_walls[:4]
            shown_walls = shown_calls + shown_puts
            raw_low = float(wall_bars["Low"].min())
            raw_high = float(wall_bars["High"].max())
            visible_walls = [wall for wall in shown_walls
                             if result.spot*.96 <= wall["strike"] <= result.spot*1.04]
            if not visible_walls:
                visible_walls = shown_walls[:4]
            wall_prices = [wall["strike"] for wall in visible_walls]
            view_low = min([raw_low] + wall_prices)
            view_high = max([raw_high] + wall_prices)
            padding = max(result.spot*.0015, (view_high-view_low)*.10)
            view_low -= padding
            view_high += padding
            band_half = max(result.spot*.00006, (view_high-view_low)*.0045)
            max_vex = max((wall["vex"] for wall in visible_walls), default=1.0)
            for wall in visible_walls:
                is_call = wall["side"] == "CALL"
                color = _green if is_call else _red
                opacity = .055 + .12*(wall["vex"]/max_vex)
                fill = (f"rgba(0,212,126,{opacity:.3f})" if is_call
                        else f"rgba(255,71,87,{opacity:.3f})")
                market_figure.add_shape(
                    type="rect", xref="paper", yref="y", x0=0, x1=1,
                    y0=wall["strike"]-band_half,
                    y1=wall["strike"]+band_half,
                    fillcolor=fill, line=dict(color=color, width=1.2),
                    layer="below")
                market_figure.add_annotation(
                    x=.995, xref="paper", y=wall["strike"], yref="y",
                    xanchor="right", showarrow=False,
                    text=(f"{wall['side']} IV WALL  ${wall['strike']:,.2f}  ·  "
                          f"${wall['vex']/1000:,.1f}K/pt"),
                    font=dict(color=color, size=10),
                    bgcolor="rgba(7,10,14,.78)", bordercolor=color,
                    borderwidth=1, borderpad=3)
            last_price = float(wall_bars["Close"].iloc[-1])
            market_figure.add_hline(
                y=last_price, line=dict(color=_cyan, width=1.3, dash="dot"),
                annotation_text=f"LAST ${last_price:,.2f}",
                annotation_position="left", row=1, col=1)
            tick_step = max(1, len(wall_bars)//9)
            tick_positions = list(range(0, len(wall_bars), tick_step))
            tick_labels = [
                wall_bars.index[index].strftime("%b %d<br>%I:%M %p")
                if hasattr(wall_bars.index[index], "strftime") else str(index)
                for index in tick_positions]
            market_figure.update_layout(
                template="plotly_dark", paper_bgcolor="#111312",
                plot_bgcolor="#151716", height=650, showlegend=False,
                margin=dict(t=55, b=35, l=18, r=60),
                title=dict(
                    text=(f"<b>{symbol}</b> · {provider_label} · CURRENT IV WALL "
                          "SNAPSHOT ON 5m PRICE"),
                    x=.012, font=dict(size=13, color="#e8edf2")),
                xaxis_rangeslider_visible=False, hovermode="x unified")
            market_figure.update_xaxes(
                showgrid=True, gridcolor="rgba(255,255,255,.035)")
            market_figure.update_xaxes(showticklabels=False, row=1, col=1)
            market_figure.update_xaxes(
                tickmode="array", tickvals=tick_positions,
                ticktext=tick_labels, row=2, col=1)
            market_figure.update_yaxes(
                range=[view_low, view_high], side="right", tickformat=".2f",
                gridcolor="rgba(255,255,255,.035)", row=1, col=1)
            market_figure.update_yaxes(
                showticklabels=False, gridcolor="rgba(255,255,255,.025)",
                row=2, col=1)

        call_k = [value/1000 for value in result.call_vex]
        put_k = [-value/1000 for value in result.put_vex]
        profile_figure = go.Figure()
        profile_figure.add_trace(go.Bar(
            x=call_k, y=result.strikes, orientation="h", name="Call VEX",
            marker_color=_green,
            hovertemplate="Strike $%{y:.2f}<br>Call $Vega %{x:.1f}K<extra></extra>"))
        profile_figure.add_trace(go.Bar(
            x=put_k, y=result.strikes, orientation="h", name="Put VEX",
            marker_color=_red,
            customdata=[[value/1000] for value in result.put_vex],
            hovertemplate="Strike $%{y:.2f}<br>Put $Vega %{customdata[0]:.1f}K<extra></extra>"))
        profile_figure.add_hline(
            y=result.spot, line=dict(color=_cyan, width=2, dash="dash"),
            annotation_text=f"Spot ${result.spot:,.2f}")
        profile_figure.add_vline(x=0, line_color="rgba(255,255,255,.25)")
        profile_figure.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=520, barmode="relative",
            margin=dict(t=48, b=48, l=60, r=20),
            title=dict(text=f"{symbol} — IV Walls by Strike · {provider_label}",
                       font=dict(size=13, color="#ddd")),
            xaxis=dict(title="$ Vega per 1 IV point ($K)", zeroline=False),
            yaxis=dict(title="Strike", tickprefix="$"),
            legend=dict(orientation="h", y=1.05, x=1, xanchor="right"),
        )

        call_iv_pct = [value*100 if value is not None else None
                       for value in result.call_iv]
        put_iv_pct = [value*100 if value is not None else None
                      for value in result.put_iv]
        skew_figure = go.Figure()
        skew_figure.add_trace(go.Scatter(
            x=call_iv_pct, y=result.strikes, mode="lines+markers",
            name="Call IV", line=dict(color=_green, width=2),
            marker=dict(size=4)))
        skew_figure.add_trace(go.Scatter(
            x=put_iv_pct, y=result.strikes, mode="lines+markers",
            name="Put IV", line=dict(color=_red, width=2),
            marker=dict(size=4)))
        skew_figure.add_hline(
            y=result.spot, line=dict(color=_cyan, width=1.5, dash="dash"),
            annotation_text=f"Spot ${result.spot:,.2f}")
        skew_figure.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=520,
            margin=dict(t=48, b=48, l=55, r=15),
            title=dict(text="Vega-Weighted IV by Strike",
                       font=dict(size=13, color="#ddd")),
            xaxis=dict(title="Implied Volatility %"),
            yaxis=dict(title="Strike", tickprefix="$"),
            legend=dict(orientation="h", y=1.05, x=1, xanchor="right"),
        )

        signed_k = [[value/1000 for value in row] for row in result.heatmap]
        heat_array = np.asarray(signed_k, dtype=float)
        heat_limit = max(float(np.nanpercentile(np.abs(heat_array), 98)), .001)
        expiration_labels = [
            f"{expiry}<br>{dte}DTE"
            for expiry, dte in zip(result.expirations, result.expiration_dtes)
        ]
        heatmap_figure = go.Figure(go.Heatmap(
            x=expiration_labels, y=result.strikes, z=signed_k,
            zmid=0, zmin=-heat_limit, zmax=heat_limit,
            colorscale=[[0, _red], [.5, "#1a1a2e"], [1, _green]],
            colorbar=dict(title="$K/1pt", thickness=10),
            hovertemplate=("%{x}<br>Strike $%{y:.2f}"
                           "<br>Signed wall %{z:.2f}K<extra></extra>"),
        ))
        heatmap_figure.add_hline(
            y=result.spot, line=dict(color=_cyan, width=2, dash="dash"),
            annotation_text=f"Spot ${result.spot:,.2f}")
        heatmap_figure.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=420,
            margin=dict(t=45, b=65, l=65, r=15),
            title=dict(text="Signed IV-Wall Concentration · Call + / Put −",
                       font=dict(size=13, color="#ddd")),
            xaxis=dict(title="Expiration", tickangle=-35),
            yaxis=dict(title="Strike", tickprefix="$"),
        )

        term_rows = result.expiration_summary
        term_x = [f"{row['expiry']}<br>{row['dte']}DTE" for row in term_rows]
        term_figure = go.Figure()
        term_figure.add_trace(go.Scatter(
            x=term_x,
            y=[row["call_iv"]*100 if row["call_iv"] is not None else None
               for row in term_rows],
            mode="lines+markers", name="Call IV", line=dict(color=_green, width=2)))
        term_figure.add_trace(go.Scatter(
            x=term_x,
            y=[row["put_iv"]*100 if row["put_iv"] is not None else None
               for row in term_rows],
            mode="lines+markers", name="Put IV", line=dict(color=_red, width=2)))
        term_figure.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e", height=420,
            margin=dict(t=45, b=65, l=60, r=20),
            title=dict(text="Vega-Weighted IV Term Structure",
                       font=dict(size=13, color="#ddd")),
            xaxis=dict(title="Expiration", tickangle=-35),
            yaxis=dict(title="Implied Volatility %"),
            legend=dict(orientation="h", y=1.05, x=1, xanchor="right"),
        )

        table_rows = []
        for walls in (result.call_walls, result.put_walls):
            for rank, wall in enumerate(walls, 1):
                table_rows.append({
                    "rank": rank, "side": wall["side"],
                    "strike": round(wall["strike"], 2),
                    "distance_pct": round(wall["distance_pct"], 2),
                    "vex": round(wall["vex"], 0),
                    "iv_pct": round(wall["iv"]*100, 2),
                    "oi": wall["oi"], "expirations": wall["expirations"],
                })
        notes_text = " | ".join(result.notes[:4])
        status = (
            f"IV Walls built for {symbol} with {provider_label}: "
            f"{len(result.expirations)} expirations, {len(result.strikes)} strikes, "
            f"{result.rows:,} contracts, {dte_label}. {notes_text}"
        )
        return (status, cards, market_figure, profile_figure, skew_figure,
                heatmap_figure, term_figure, table_rows)

    # =====================================================================
    # OVERNIGHT — late-day positioning scanner for gap setups
    # =====================================================================

    @app.callback(
        [Output("on-status", "children"),
         Output("on-board-table", "data"),
         Output("on-detail-store", "data"),
         Output("on-board-table", "selected_rows")],
        Input("on-scan-btn", "n_clicks"),
        [State("on-symbols", "value"),
         State("on-dte-max", "value"),
         State("on-vol-oi-min", "value"),
         State("on-agg-min", "value"),
         State("on-min-notional-k", "value"),
         State("on-include-itm", "value")],
        prevent_initial_call=True,
    )
    def run_overnight_scan(_n, symbols_text, dte_max, vol_oi_min,
                            agg_min, min_notional_k, include_itm_val):
        if not symbols_text:
            return ("Enter at least one symbol (e.g. SPY, QQQ, NVDA).",
                    [], {}, [])

        syms = [s.strip().upper() for s in symbols_text.split(",")
                if s and s.strip()]
        syms = list(dict.fromkeys(syms))
        if not syms:
            return ("No valid symbols parsed.", [], {}, [])

        try:
            dte_n = int(dte_max) if dte_max is not None else 5
        except (TypeError, ValueError):
            dte_n = 5
        dte_n = max(0, min(30, dte_n))

        try:
            voi = float(vol_oi_min) if vol_oi_min is not None else 0.30
        except (TypeError, ValueError):
            voi = 0.30
        voi = max(0.0, min(10.0, voi))

        try:
            agg = float(agg_min) / 100.0 if agg_min is not None else 0.60
        except (TypeError, ValueError):
            agg = 0.60
        agg = max(0.0, min(1.0, agg))

        try:
            minn = float(min_notional_k) * 1000.0 if min_notional_k is not None else 50_000
        except (TypeError, ValueError):
            minn = 50_000

        include_itm = bool(include_itm_val) and "y" in include_itm_val

        try:
            results = _scan_overnight(
                syms, dte_max=dte_n,
                vol_oi_min=voi, aggression_min=agg,
                min_notional=minn,
                include_itm=include_itm,
            )
        except Exception as exc:
            return (f"Scan failed: {exc}", [], {}, [])

        if not results:
            return ("No results.", [], {}, [])

        rows = [_on_board_row(r) for r in results]

        # Stash per-symbol detail in the store so drill-down doesn't need
        # to re-hit yfinance.
        detail = {}
        for r in results:
            detail[r.symbol] = {
                "spot": r.spot,
                "chg_pct": r.day_chg_pct,
                "range_pos": r.day_range_pos,
                "bias_score": r.bias_score,
                "bias_label": r.bias_label,
                "as_of": r.as_of,
                "calls": _on_flow_rows(r.calls),
                "puts": _on_flow_rows(r.puts),
                "notes": r.notes,
            }

        scanned = len(results)
        with_data = sum(1 for r in results if r.spot > 0)
        avg_bias = round(sum(r.bias_score for r in results) / scanned, 1)
        bull = sum(1 for r in results if r.bias_score >= 15)
        bear = sum(1 for r in results if r.bias_score <= -15)
        status = (f"Scanned {scanned} symbols ({with_data} with data). "
                  f"Avg bias {avg_bias:+}. {bull} bullish · {bear} bearish "
                  f"· DTE ≤ {dte_n}, Vol/OI ≥ {voi:.2f}, "
                  f"Agg ≥ {agg*100:.0f}%.")

        # Auto-select the first row so the detail panel populates.
        return status, rows, detail, [0] if rows else []

    @app.callback(
        [Output("on-detail-title", "children"),
         Output("on-detail-sub", "children"),
         Output("on-detail-calls-table", "data"),
         Output("on-detail-puts-table", "data"),
         Output("on-detail-notes", "children")],
        [Input("on-board-table", "selected_rows"),
         Input("on-board-table", "data"),
         Input("on-detail-store", "data")],
    )
    def show_overnight_detail(selected_rows, board_data, store):
        title = "Per-Strike Flow Detail"
        sub = "select a symbol in the board to populate"
        empty_notes = ""
        if not selected_rows or not board_data or not store:
            return title, sub, [], [], empty_notes

        idx = selected_rows[0]
        if idx >= len(board_data):
            return title, sub, [], [], empty_notes

        sym = board_data[idx].get("symbol")
        if not sym or sym not in store:
            return title, sub, [], [], empty_notes

        det = store[sym]
        calls = det.get("calls", [])
        puts = det.get("puts", [])

        # Sub-header tells the user what this detail panel reflects.
        spot = det.get("spot")
        chg = det.get("chg_pct")
        rp = det.get("range_pos")
        bs = det.get("bias_score", 0)
        lbl = det.get("bias_label", "")
        as_of = det.get("as_of", "")

        title = f"{sym} — Per-Strike Flow Detail"
        sub_parts = []
        if spot:
            sub_parts.append(f"spot ${spot:,.2f}")
        if chg is not None:
            sub_parts.append(f"day {chg:+.2f}%")
        if rp is not None:
            sub_parts.append(f"close @ {rp*100:.0f}% of range")
        sub_parts.append(f"bias {bs:+} {lbl}")
        if as_of:
            sub_parts.append(f"as of {as_of}")
        sub = "  ·  ".join(sub_parts)

        notes_div = ""
        notes = det.get("notes", [])
        if notes:
            notes_div = html.Div([
                html.Span("Notes: ", style={"fontWeight": "700",
                                              "color": "#ddd"}),
                html.Span(" | ".join(notes[:5]),
                          style={"color": "#bbb"}),
            ])

        return title, sub, calls, puts, notes_div

    # =====================================================================
    # OPTIONS SCREENER
    # =====================================================================

    @app.callback(
        [Output("opt-scr-status", "children"),
         Output("opt-scr-summary-table", "data"),
         Output("opt-scr-top-table", "data"),
         Output("opt-scr-itm-otm", "children")],
        Input("opt-scr-run-btn", "n_clicks"),
        [State("opt-scr-ticker", "value"),
         State("opt-scr-expirations", "value"),
         State("opt-scr-top-n", "value")],
        prevent_initial_call=True,
    )
    def run_options_volume(_n, ticker, expiration_text, top_n):
        sym = (ticker or "").strip().upper()
        if not sym:
            return "Enter a ticker first.", [], [], ""

        try:
            stock = yf.Ticker(sym)
            available = list(stock.options or [])
        except Exception as exc:
            return f"Failed to fetch options for {sym}: {exc}", [], [], ""

        if not available:
            return f"No options data found for {sym}.", [], [], ""

        parsed = [x.strip() for x in (expiration_text or "").split(",") if x.strip()]
        dates = parsed if parsed else [available[0]]

        summary_rows = []
        first_valid_calls = None
        skipped = []
        for exp in dates:
            if exp not in available:
                skipped.append(exp)
                continue
            try:
                chain = stock.option_chain(exp)
                calls = chain.calls.copy()
                puts = chain.puts.copy()
                summary_rows.append({
                    "expiration": exp,
                    "call_volume": int(calls["volume"].fillna(0).sum()),
                    "put_volume": int(puts["volume"].fillna(0).sum()),
                    "call_oi": int(calls["openInterest"].fillna(0).sum()),
                    "put_oi": int(puts["openInterest"].fillna(0).sum()),
                })
                if first_valid_calls is None:
                    first_valid_calls = calls
            except Exception:
                skipped.append(exp)

        if not summary_rows:
            return (f"No valid expirations resolved for {sym}. "
                    f"Try one of: {', '.join(available[:5])}"), [], [], ""

        n_top = 10
        try:
            if top_n is not None:
                n_top = max(1, min(100, int(top_n)))
        except (TypeError, ValueError):
            n_top = 10

        top_rows = []
        itm_otm = ""
        if first_valid_calls is not None and not first_valid_calls.empty:
            calls = first_valid_calls.copy()
            calls["volume"] = calls["volume"].fillna(0)
            calls["openInterest"] = calls["openInterest"].fillna(0)
            calls["impliedVolatility"] = calls["impliedVolatility"].fillna(0.0)
            top_df = calls.nlargest(n_top, "volume")[[
                "strike", "volume", "openInterest", "impliedVolatility", "inTheMoney"
            ]]
            top_rows = top_df.to_dict("records")
            itm_vol = int(calls[calls["inTheMoney"] == True]["volume"].sum())
            otm_vol = int(calls[calls["inTheMoney"] == False]["volume"].sum())
            itm_otm = f"ITM call volume: {itm_vol:,} | OTM call volume: {otm_vol:,}"

        status = f"Loaded {len(summary_rows)} expiration(s) for {sym}."
        if skipped:
            status += f" Skipped: {', '.join(skipped[:8])}"
        return status, summary_rows, top_rows, itm_otm

    @app.callback(
        [Output("opt-bm-status", "children"),
         Output("opt-bm-table", "data")],
        Input("opt-bm-run-btn", "n_clicks"),
        [State("opt-bm-ticker", "value"),
         State("opt-bm-min-premium", "value"),
         State("opt-bm-limit", "value")],
        prevent_initial_call=True,
    )
    def run_big_money_moves(_n, ticker, min_premium, limit):
        sym = (ticker or "").strip().upper()
        if not sym:
            return "Enter an underlying ticker first.", []

        try:
            max_rows = max(5, min(100, int(limit or 30)))
        except (TypeError, ValueError):
            max_rows = 30
        try:
            min_notional = float(min_premium or 100000)
        except (TypeError, ValueError):
            min_notional = 100000.0

        rows = []
        source_note = ""

        # Try Massive snapshot first (paid tiers). If access is denied on
        # free plan, fallback to yfinance so the tool remains usable.
        url = f"https://api.polygon.io/v3/snapshot/options/{sym}"
        params = {
            "apiKey": _massive_api_key,
            "limit": 250,
            "sort": "day.volume",
            "order": "desc",
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            payload = resp.json() if resp.content else {}
            if resp.status_code == 200:
                contracts = payload.get("results") or []
                for item in contracts:
                    details = item.get("details") or {}
                    day = item.get("day") or {}
                    quote = item.get("last_quote") or {}
                    trade = item.get("last_trade") or {}

                    vol = int(day.get("volume") or 0)
                    oi = int(item.get("open_interest") or 0)
                    bid = float(quote.get("bid") or 0.0)
                    ask = float(quote.get("ask") or 0.0)
                    last = float(trade.get("price") or day.get("close") or 0.0)
                    mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else (last or 0.0)
                    premium_notional = vol * max(mid, last) * 100
                    if premium_notional < min_notional:
                        continue

                    bias = "NEUTRAL"
                    if bid > 0 and ask > 0 and last > 0:
                        spread = max(ask - bid, 0.01)
                        if last >= ask - 0.25 * spread:
                            bias = "BUYER AGGR"
                        elif last <= bid + 0.25 * spread:
                            bias = "SELLER AGGR"

                    rows.append({
                        "expiration": details.get("expiration_date") or "",
                        "option_type": str(details.get("contract_type") or "").upper(),
                        "strike": float(details.get("strike_price") or 0.0),
                        "volume": vol,
                        "open_interest": oi,
                        "last_price": round(last, 4),
                        "bid": round(bid, 4),
                        "ask": round(ask, 4),
                        "premium_notional": round(premium_notional, 2),
                        "vol_oi": round((vol / oi), 2) if oi > 0 else None,
                        "side_bias": bias,
                    })
                source_note = "Source: Massive Snapshot."
        except Exception:
            pass

        if not rows:
            # Fallback path for free plan users: yfinance option chains.
            try:
                stock = yf.Ticker(sym)
                expirations = list(stock.options or [])[:5]
                for exp in expirations:
                    chain = stock.option_chain(exp)
                    for opt_type, frame in (("CALL", chain.calls), ("PUT", chain.puts)):
                        if frame is None or frame.empty:
                            continue
                        df = frame.copy()
                        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
                        df["openInterest"] = pd.to_numeric(df["openInterest"], errors="coerce").fillna(0)
                        df["lastPrice"] = pd.to_numeric(df["lastPrice"], errors="coerce").fillna(0.0)
                        df["bid"] = pd.to_numeric(df["bid"], errors="coerce").fillna(0.0)
                        df["ask"] = pd.to_numeric(df["ask"], errors="coerce").fillna(0.0)
                        df["premium_notional"] = df["volume"] * df["lastPrice"] * 100
                        df = df[df["premium_notional"] >= min_notional]

                        for _, r in df.iterrows():
                            bid = float(r.get("bid") or 0.0)
                            ask = float(r.get("ask") or 0.0)
                            last = float(r.get("lastPrice") or 0.0)
                            bias = "NEUTRAL"
                            if bid > 0 and ask > 0 and last > 0:
                                spread = max(ask - bid, 0.01)
                                if last >= ask - 0.25 * spread:
                                    bias = "BUYER AGGR"
                                elif last <= bid + 0.25 * spread:
                                    bias = "SELLER AGGR"
                            vol = int(r.get("volume") or 0)
                            oi = int(r.get("openInterest") or 0)
                            rows.append({
                                "expiration": exp,
                                "option_type": opt_type,
                                "strike": float(r.get("strike") or 0.0),
                                "volume": vol,
                                "open_interest": oi,
                                "last_price": round(last, 4),
                                "bid": round(bid, 4),
                                "ask": round(ask, 4),
                                "premium_notional": round(float(r.get("premium_notional") or 0.0), 2),
                                "vol_oi": round((vol / oi), 2) if oi > 0 else None,
                                "side_bias": bias,
                            })
                source_note = "Source: yfinance fallback (Massive Snapshot unavailable on current plan)."
            except Exception as exc:
                return f"Big Money Moves fetch failed for {sym}: {exc}", []

        if not rows:
            return (f"No contracts passed min premium ${min_notional:,.0f} for {sym}.", [])

        df = pd.DataFrame(rows).sort_values(
            ["premium_notional", "volume"], ascending=False
        ).head(max_rows)
        out = df.to_dict("records")
        status = (f"Loaded {len(out)} big-money contracts for {sym} "
                  f"(min premium ${min_notional:,.0f}). {source_note}")
        return status, out
