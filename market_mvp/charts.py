"""Plotly chart builders for the three-page MVP."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from market_mvp.config import COLORS


PLOT_LAYOUT = dict(
    paper_bgcolor=COLORS["panel"],
    plot_bgcolor=COLORS["panel"],
    font=dict(family="Inter, Segoe UI, sans-serif", color=COLORS["muted"]),
    margin=dict(l=42, r=30, t=48, b=38),
    hovermode="x unified",
)


def compact_money(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    amount = abs(float(value))
    if amount >= 1e9:
        return f"{sign}${amount / 1e9:.2f}B"
    if amount >= 1e6:
        return f"{sign}${amount / 1e6:.1f}M"
    if amount >= 1e3:
        return f"{sign}${amount / 1e3:.1f}K"
    return f"{sign}${amount:.0f}"


def empty_figure(message: str, height: int = 420) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message, x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, font=dict(color=COLORS["muted"], size=13),
    )
    fig.update_layout(**PLOT_LAYOUT, height=height)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def make_gex_market_chart(result, bars: pd.DataFrame) -> go.Figure:
    if bars is None or bars.empty:
        return make_gex_profile(result)
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(bars.columns)):
        return make_gex_profile(result)

    bars = bars.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    x = np.arange(len(bars), dtype=float)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.025,
        row_heights=[0.78, 0.22],
    )
    fig.add_trace(go.Candlestick(
        x=x, open=bars["Open"], high=bars["High"], low=bars["Low"],
        close=bars["Close"], name=result.symbol,
        increasing_line_color=COLORS["green"],
        decreasing_line_color=COLORS["red"],
        increasing_fillcolor=COLORS["green"],
        decreasing_fillcolor=COLORS["red"],
    ), row=1, col=1)

    volume_colors = np.where(
        bars["Close"].to_numpy() >= bars["Open"].to_numpy(),
        "rgba(49,208,139,.45)", "rgba(255,85,115,.45)",
    )
    fig.add_trace(go.Bar(
        x=x, y=bars["Volume"], marker_color=volume_colors,
        name="Volume", hovertemplate="Volume %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    last = float(bars["Close"].iloc[-1])
    candle_low = float(bars["Low"].min())
    candle_high = float(bars["High"].max())
    padding = max(last * 0.003, (candle_high - candle_low) * 0.35)
    view_low, view_high = candle_low - padding, candle_high + padding
    levels = [
        (float(k), float(v)) for k, v in zip(result.strikes, result.profile)
        if view_low <= float(k) <= view_high and float(v) != 0
    ]
    levels.sort(key=lambda item: abs(item[1]), reverse=True)
    levels = levels[:10]
    max_strength = max((abs(v) for _, v in levels), default=1.0)
    bar_height = max(last * 0.00007, (view_high - view_low) * 0.009)

    for strike, value in levels:
        strength = abs(value) / max_strength
        color = COLORS["green"] if value >= 0 else COLORS["red"]
        fill = "rgba(49,208,139,.76)" if value >= 0 else "rgba(255,85,115,.76)"
        width = 0.035 + 0.31 * strength ** 0.72
        fig.add_shape(
            type="rect", xref="paper", yref="y", x0=0.985-width, x1=0.985,
            y0=strike-bar_height, y1=strike+bar_height,
            line=dict(color=color, width=1), fillcolor=fill,
        )
        fig.add_annotation(
            x=0.981-width, xref="paper", y=strike, yref="y",
            text=compact_money(value).replace("$", ""), showarrow=False,
            xanchor="right", font=dict(color=color, size=10),
        )

    fig.add_hline(
        y=last, line=dict(color=COLORS["cyan"], width=1, dash="dot"),
        annotation_text=f"LAST {last:,.2f}", annotation_position="right",
        row=1, col=1,
    )
    if result.flip_price and view_low <= result.flip_price <= view_high:
        fig.add_hline(
            y=result.flip_price,
            line=dict(color=COLORS["amber"], width=1.4, dash="dash"),
            annotation_text=f"FLIP {result.flip_price:,.2f}",
            annotation_position="left", row=1, col=1,
        )

    tick_step = max(1, len(bars) // 8)
    tick_idx = list(range(0, len(bars), tick_step))
    tick_text = [bars.index[i].strftime("%I:%M %p") for i in tick_idx]
    fig.update_layout(
        **PLOT_LAYOUT, height=610, showlegend=False,
        title=dict(
            text=(f"<b>{result.symbol}</b> · 5m · Estimated net GEX "
                  f"<span style='color:{COLORS['cyan']}'>{compact_money(result.total_gex)}</span>"),
            x=0.015, font=dict(size=13, color=COLORS["text"]),
        ),
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(range=[-1, max(len(bars) * 1.62, len(bars) + 10)])
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_xaxes(tickmode="array", tickvals=tick_idx, ticktext=tick_text,
                     row=2, col=1)
    fig.update_yaxes(range=[view_low, view_high], side="right", tickformat=".2f",
                     gridcolor="rgba(255,255,255,.045)", row=1, col=1)
    fig.update_yaxes(showticklabels=False, gridcolor="rgba(255,255,255,.025)",
                     row=2, col=1)
    return fig


def make_gex_heatmap(result) -> go.Figure:
    if not result.strikes or not result.expirations:
        return empty_figure("No usable GEX contracts returned")
    z = np.asarray(result.heatmap, dtype=float) / 1e6
    limit = float(np.nanpercentile(np.abs(z), 97)) if z.size else 1.0
    limit = max(limit, 0.01)
    labels = [f"{exp}<br>{dte} DTE" for exp, dte in zip(
        result.expirations, result.expiration_dtes)]
    fig = go.Figure(go.Heatmap(
        x=labels, y=result.strikes, z=z, zmid=0, zmin=-limit, zmax=limit,
        colorscale=[[0, "#c72f55"], [.5, "#111820"], [1, "#2acb8a"]],
        colorbar=dict(title="$M/1%", thickness=11),
        hovertemplate="%{x}<br>Strike %{y:.2f}<br>Net GEX %{z:.2f}M<extra></extra>",
    ))
    fig.update_layout(
        **PLOT_LAYOUT, height=440,
        title=dict(text="Strike × expiration", x=.02,
                   font=dict(size=14, color=COLORS["text"])),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,.03)")
    fig.update_yaxes(title="Strike", gridcolor="rgba(255,255,255,.03)")
    return fig


def make_gex_profile(result) -> go.Figure:
    values = np.asarray(result.profile, dtype=float) / 1e6
    colors = np.where(values >= 0, COLORS["green"], COLORS["red"])
    fig = go.Figure(go.Bar(
        x=values, y=result.strikes, orientation="h", marker_color=colors,
        hovertemplate="Strike %{y:.2f}<br>Net GEX %{x:.2f}M<extra></extra>",
    ))
    fig.add_hline(y=result.spot, line_color=COLORS["cyan"], line_dash="dot",
                  annotation_text=f"Spot {result.spot:.2f}")
    if result.flip_price:
        fig.add_hline(y=result.flip_price, line_color=COLORS["amber"],
                      line_dash="dash", annotation_text=f"Flip {result.flip_price:.2f}")
    fig.update_layout(
        **PLOT_LAYOUT, height=440,
        title=dict(text="Net GEX by strike", x=.02,
                   font=dict(size=14, color=COLORS["text"])),
    )
    fig.update_xaxes(title="$M per 1% move", gridcolor="rgba(255,255,255,.04)")
    fig.update_yaxes(title="Strike", gridcolor="rgba(255,255,255,.025)")
    return fig


def make_volume_timeline(history: list[dict], symbol: str) -> go.Figure:
    if not history:
        return empty_figure("No intraday volume history returned", 560)
    df = pd.DataFrame(history)
    x = pd.to_datetime(df["ts_iso"])
    colors = np.where(df["close"] >= df["open"], COLORS["green"], COLORS["red"])
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=.035,
        row_heights=[.60, .20, .20],
    )
    fig.add_trace(go.Candlestick(
        x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color=COLORS["green"], decreasing_line_color=COLORS["red"],
        name=symbol,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=x, y=df["vwap"], line=dict(color=COLORS["amber"], width=1.8),
        name="VWAP",
    ), row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=df["volume"], marker_color=colors,
                         name="Volume"), row=2, col=1)
    delta_colors = np.where(df["cum_delta"] >= 0, COLORS["green"], COLORS["red"])
    fig.add_trace(go.Bar(
        x=x, y=df["cum_delta"], marker_color=delta_colors,
        name="Estimated cumulative directional $ volume",
    ), row=3, col=1)
    fig.update_layout(
        **PLOT_LAYOUT, height=590, xaxis_rangeslider_visible=False,
        showlegend=False,
        title=dict(text=f"<b>{symbol}</b> · price, volume and directional pressure",
                   x=.015, font=dict(size=14, color=COLORS["text"])),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,.035)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,.035)")
    return fig


def make_volume_profile(history: list[dict], symbol: str) -> go.Figure:
    if not history:
        return empty_figure("No volume profile available", 590)
    df = pd.DataFrame(history)
    prices = pd.to_numeric(df["close"], errors="coerce")
    volumes = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    valid = prices.notna()
    prices, volumes = prices[valid], volumes[valid]
    if prices.empty or prices.min() == prices.max():
        return empty_figure("Not enough price variation for profile", 590)
    bins = np.linspace(prices.min(), prices.max(), 31)
    bucket = pd.cut(prices, bins=bins, include_lowest=True)
    profile = volumes.groupby(bucket, observed=False).sum()
    mids = [float(interval.mid) for interval in profile.index]
    poc_index = int(np.argmax(profile.to_numpy()))
    colors = [COLORS["amber"] if i == poc_index else COLORS["cyan"]
              for i in range(len(profile))]
    fig = go.Figure(go.Bar(
        x=profile.values, y=mids, orientation="h", marker_color=colors,
        hovertemplate="Price %{y:.2f}<br>Volume %{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        **PLOT_LAYOUT, height=590,
        title=dict(text=f"{symbol} · volume profile (POC highlighted)", x=.02,
                   font=dict(size=14, color=COLORS["text"])),
    )
    fig.update_xaxes(title="Volume", gridcolor="rgba(255,255,255,.035)")
    fig.update_yaxes(title="Price", gridcolor="rgba(255,255,255,.025)")
    return fig
