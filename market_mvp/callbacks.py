"""Interactive behavior for the standalone market MVP."""

from __future__ import annotations

import re
from datetime import datetime

from dash import Input, Output, State, ctx, html, no_update

from market_mvp.charts import (
    compact_money,
    empty_figure,
    make_gex_heatmap,
    make_gex_market_chart,
    make_gex_profile,
    make_volume_profile,
    make_volume_timeline,
)
from market_mvp.services import (
    get_gex,
    get_price_bars,
    get_volume_detail,
    get_volume_scan,
)


def _metric(label: str, value: str, detail: str = "", tone: str = "neutral"):
    return html.Div([
        html.Span(label),
        html.Strong(value),
        html.Small(detail),
    ], className=f"metric-card tone-{tone}")


def _tone(value: float) -> str:
    return "positive" if value > 0 else "negative" if value < 0 else "neutral"


def _fmt_number(value, suffix: str = "") -> str:
    if value is None:
        return "—"
    value = float(value)
    if abs(value) >= 1e9:
        return f"{value / 1e9:.2f}B{suffix}"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.1f}M{suffix}"
    if abs(value) >= 1e3:
        return f"{value / 1e3:.1f}K{suffix}"
    return f"{value:,.2f}{suffix}"


def register_callbacks(app):
    @app.callback(
        [Output("mvp-active-page", "data"),
         Output("mvp-page-gex", "className"),
         Output("mvp-page-screener", "className"),
         Output("mvp-page-detail", "className"),
         Output("mvp-nav-gex", "className"),
         Output("mvp-nav-screener", "className"),
         Output("mvp-nav-detail", "className"),
         Output("mvp-detail-symbol", "value")],
        [Input("mvp-nav-gex", "n_clicks"),
         Input("mvp-nav-screener", "n_clicks"),
         Input("mvp-nav-detail", "n_clicks"),
         Input("mvp-volume-table", "active_cell")],
        [State("mvp-active-page", "data"),
         State("mvp-volume-table", "derived_virtual_data"),
         State("mvp-volume-table", "data"),
         State("mvp-detail-symbol", "value")],
    )
    def navigate(_gex, _screener, _detail, active_cell, current_page,
                 visible_rows, all_rows, detail_symbol):
        trigger = ctx.triggered_id
        page = current_page or "gex"
        symbol_out = no_update
        if trigger == "mvp-nav-gex":
            page = "gex"
        elif trigger == "mvp-nav-screener":
            page = "screener"
        elif trigger == "mvp-nav-detail":
            page = "detail"
        elif trigger == "mvp-volume-table" and active_cell:
            rows = visible_rows or all_rows or []
            row_index = active_cell.get("row", -1)
            if 0 <= row_index < len(rows) and rows[row_index].get("symbol"):
                page = "detail"
                symbol_out = rows[row_index]["symbol"]

        page_classes = {
            name: "product-page" + ("" if page == name else " page-hidden")
            for name in ("gex", "screener", "detail")
        }
        nav_classes = {
            name: "nav-item" + (" active" if page == name else "")
            for name in ("gex", "screener", "detail")
        }
        return (
            page,
            page_classes["gex"], page_classes["screener"], page_classes["detail"],
            nav_classes["gex"], nav_classes["screener"], nav_classes["detail"],
            symbol_out,
        )

    @app.callback(
        [Output("mvp-gex-timer", "interval"),
         Output("mvp-gex-timer", "disabled")],
        Input("mvp-gex-refresh", "value"),
    )
    def configure_gex_refresh(value):
        intervals = {"30s": 30_000, "1m": 60_000,
                     "2m": 120_000, "5m": 300_000}
        if value not in intervals:
            return 30_000, True
        return intervals[value], False

    @app.callback(
        [Output("mvp-gex-status", "children"),
         Output("mvp-gex-metrics", "children"),
         Output("mvp-gex-market", "figure"),
         Output("mvp-gex-heatmap", "figure"),
         Output("mvp-gex-profile", "figure")],
        [Input("mvp-gex-build", "n_clicks"),
         Input("mvp-gex-timer", "n_intervals")],
        [State("mvp-gex-symbol", "value"),
         State("mvp-gex-dtes", "value"),
         State("mvp-gex-expirations", "value"),
         State("mvp-gex-window", "value")],
        prevent_initial_call=True,
    )
    def build_gex(_clicks, _ticks, symbol, dtes, expirations, window):
        symbol = (symbol or "").strip().upper()
        if not symbol:
            empty = empty_figure("Enter an optionable symbol")
            return "Enter a symbol first.", [], empty, empty, empty
        try:
            expiration_count = max(1, min(20, int(expirations or 12)))
            window_pct = max(.03, min(.50, float(window or 15) / 100))
            selected_dtes = sorted(set(int(d) for d in (dtes or [])))
            result = get_gex(symbol, selected_dtes, expiration_count, window_pct)
            if not result.strikes:
                message = "No usable option contracts returned. " + " · ".join(result.notes[:2])
                empty = empty_figure(message)
                return message, [], empty, empty, empty
            bars = get_price_bars(symbol)
        except Exception as exc:
            message = f"GEX request failed: {exc}"
            empty = empty_figure(message)
            return message, [], empty, empty, empty

        nearest_call = result.call_walls[0]["strike"] if result.call_walls else None
        nearest_put = result.put_walls[0]["strike"] if result.put_walls else None
        metrics = [
            _metric("SPOT", f"${result.spot:,.2f}", result.as_of, "accent"),
            _metric("NET GEX", compact_money(result.total_gex), "$ delta / 1% move",
                    _tone(result.total_gex)),
            _metric("GAMMA FLIP", f"${result.flip_price:,.2f}" if result.flip_price else "—",
                    "estimated zero-gamma level", "warning"),
            _metric("CALL WALL", f"${nearest_call:,.2f}" if nearest_call else "—",
                    "strongest positive strike", "positive"),
            _metric("PUT WALL", f"${nearest_put:,.2f}" if nearest_put else "—",
                    "strongest negative strike", "negative"),
        ]
        dte_label = ", ".join(f"{d}DTE" for d in selected_dtes) if selected_dtes else "all DTEs"
        mode = "Auto-refreshed" if ctx.triggered_id == "mvp-gex-timer" else "Built"
        status = (f"{mode} {symbol} · {len(result.expirations)} expirations · "
                  f"{len(result.strikes)} strikes · {dte_label} · {result.rows:,} contracts")
        return (
            status, metrics, make_gex_market_chart(result, bars),
            make_gex_heatmap(result), make_gex_profile(result),
        )

    @app.callback(
        [Output("mvp-volume-status", "children"),
         Output("mvp-volume-metrics", "children"),
         Output("mvp-volume-table", "data")],
        Input("mvp-volume-scan", "n_clicks"),
        State("mvp-volume-symbols", "value"),
        prevent_initial_call=True,
    )
    def run_volume_scan(_clicks, raw_symbols):
        symbols = [s for s in re.split(r"[\s,;]+", raw_symbols or "") if s]
        symbols = list(dict.fromkeys(s.upper() for s in symbols))[:75]
        if not symbols:
            return "Enter at least one symbol.", [], []
        try:
            rows = get_volume_scan(symbols)
        except Exception as exc:
            return f"Volume scan failed: {exc}", [], []
        valid = [row for row in rows if row.get("rel_vol") is not None]
        abnormal = [row for row in valid if float(row["rel_vol"]) >= 1.5]
        top = max(valid, key=lambda row: float(row["rel_vol"])) if valid else None
        bullish = sum(1 for row in valid if float(row.get("buy_share") or 50) >= 60)
        bearish = sum(1 for row in valid if float(row.get("buy_share") or 50) <= 40)
        bias = "BUYING" if bullish > bearish else "SELLING" if bearish > bullish else "MIXED"
        metrics = [
            _metric("SCANNED", str(len(rows)), f"{len(valid)} with live data", "accent"),
            _metric("ABNORMAL", str(len(abnormal)), "RVOL ≥ 1.5×", "warning"),
            _metric("TOP RVOL", f"{top['rel_vol']:.2f}×" if top else "—",
                    top["symbol"] if top else "no live result", "positive"),
            _metric("MARKET BIAS", bias, f"{bullish} buy · {bearish} sell",
                    "positive" if bias == "BUYING" else "negative" if bias == "SELLING" else "neutral"),
        ]
        timestamp = datetime.now().strftime("%I:%M:%S %p")
        return f"Scan completed at {timestamp} · select a row for Volume Detail", metrics, rows

    @app.callback(
        [Output("mvp-detail-status", "children"),
         Output("mvp-detail-metrics", "children"),
         Output("mvp-detail-chart", "figure"),
         Output("mvp-detail-profile", "figure"),
         Output("mvp-spike-table", "data")],
        Input("mvp-detail-load", "n_clicks"),
        [State("mvp-detail-symbol", "value"),
         State("mvp-detail-timeframe", "value"),
         State("mvp-detail-days", "value")],
        prevent_initial_call=True,
    )
    def load_volume_detail(_clicks, symbol, timeframe, days):
        symbol = (symbol or "").strip().upper()
        if not symbol:
            empty = empty_figure("Enter a symbol")
            return "Enter a symbol first.", [], empty, empty, []
        try:
            payload = get_volume_detail(symbol, timeframe or "5m", int(days or 2))
            history = payload.get("history") or []
            timeline = payload.get("timeline") or {}
        except Exception as exc:
            message = f"Volume analysis failed: {exc}"
            empty = empty_figure(message)
            return message, [], empty, empty, []
        if not history:
            message = f"No intraday volume data returned for {symbol}."
            empty = empty_figure(message)
            return message, [], empty, empty, []

        latest = history[-1]
        buy_share = float(latest.get("buy_share") or 50)
        direction = "BUYING" if buy_share >= 60 else "SELLING" if buy_share <= 40 else "BALANCED"
        spikes = timeline.get("spike_rows") or []
        metrics = [
            _metric("LAST", f"${latest['close']:,.2f}", latest.get("ts", ""), "accent"),
            _metric("BAR RVOL", f"{latest['rel_vol']:.2f}×" if latest.get("rel_vol") is not None else "—",
                    f"{timeframe} participation", "warning"),
            _metric("SESSION VOLUME", _fmt_number(latest.get("cum_vol")), "cumulative", "neutral"),
            _metric("PRESSURE", direction, f"{buy_share:.1f}% estimated buy",
                    "positive" if direction == "BUYING" else "negative" if direction == "SELLING" else "neutral"),
            _metric("VWAP", f"${latest['vwap']:,.2f}" if latest.get("vwap") is not None else "—",
                    f"price {latest.get('vwap_diff', 0):+.2f} vs VWAP", _tone(float(latest.get("vwap_diff") or 0))),
        ]
        status = (f"Loaded {symbol} · {len(history)} {timeframe} bars · "
                  f"{len(spikes)} detected five-minute spikes")
        return (
            status, metrics, make_volume_timeline(history, symbol),
            make_volume_profile(history, symbol), spikes,
        )
