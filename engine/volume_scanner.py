"""Abnormal-volume scanner.

For each symbol we pull recent intraday 1-minute bars and compute:

* **Today's cumulative volume** (so far in this session).
* **Typical cumulative volume by the same minute** averaged across the last
  ``VOL_INTRADAY_LOOKBACK_DAYS`` regular sessions.
* **Relative volume** = today / typical-by-this-time. Anything >= 1.5x is
  flagged as abnormal, >= 2.5x as extreme.
* **Buy / Sell pressure approximation** using the *tick rule* on each
  minute bar: a bar that closes above its open is treated as "buy"
  volume, a bar that closes below its open is "sell" volume, and an
  unchanged bar is split 50/50.
* **Net delta** ($) = buy $ volume − sell $ volume. Positive = net
  buying, negative = net selling.

yfinance does not expose the exchange order book / level-2 data, so the
buy-vs-sell split is an approximation derived from minute-bar tick
direction. This is the same heuristic used by most retail "tape /
volume-pressure" tools and is good enough to flag accumulation vs
distribution days at a glance.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from config import (
    VOL_REL_ABNORMAL,
    VOL_REL_EXTREME,
    VOL_BUY_PRESSURE,
    VOL_SELL_PRESSURE,
    VOL_INTRADAY_LOOKBACK_DAYS,
    VOL_DAILY_LOOKBACK_DAYS,
    VOL_SPIKE_LOOKBACK_BARS,
    VOL_SPIKE_Z_THRESHOLD,
    VOL_SPIKE_REL_THRESHOLD,
    VOL_SPIKE_MAX_RESULTS,
    VOL_SPIKE_DELTA_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Display all timestamps in US/Pacific time. yfinance returns tz-aware
# UTC indices for intraday bars; for tz-naive series we assume UTC.
PT_TZ = "America/Los_Angeles"


def _to_pt(ts) -> pd.Timestamp:
    """Convert any pandas Timestamp / DatetimeIndex element to Pacific Time."""
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(PT_TZ)


def _format_pt(ts, with_date: bool = True) -> str:
    pt = _to_pt(ts)
    return pt.strftime("%Y-%m-%d %H:%M PT" if with_date else "%H:%M PT")


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def _to_pt_index(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with its DatetimeIndex converted to Pacific Time so
    session boundaries / time-of-day lookups all work in PT."""
    if df is None or df.empty:
        return df
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(PT_TZ)
    return df


def _classify_minute_bars(bars: pd.DataFrame) -> tuple[float, float]:
    """Return (buy_dollar_vol, sell_dollar_vol) using tick-rule classification.

    Each minute bar contributes its ``Close * Volume`` dollar value:
      - to ``buy``  if Close > Open
      - to ``sell`` if Close < Open
      - split 50/50 otherwise (doji)
    """
    if bars is None or bars.empty:
        return 0.0, 0.0
    bars = _flatten(bars).dropna(subset=["Open", "Close", "Volume"])
    if bars.empty:
        return 0.0, 0.0

    close = bars["Close"].astype(float)
    open_ = bars["Open"].astype(float)
    vol = bars["Volume"].astype(float)
    dollar = close * vol

    up = close > open_
    down = close < open_
    flat = ~(up | down)

    buy = float(dollar[up].sum() + 0.5 * dollar[flat].sum())
    sell = float(dollar[down].sum() + 0.5 * dollar[flat].sum())
    return buy, sell


def _typical_volume_by_minute(intraday: pd.DataFrame, today: pd.Timestamp,
                                up_to: pd.Timestamp) -> float | None:
    """Average cumulative volume across prior sessions up to ``up_to``'s
    time-of-day. Returns ``None`` if we can't compute a baseline."""
    if intraday is None or intraday.empty:
        return None
    df = _flatten(intraday).dropna(subset=["Volume"])
    if df.empty:
        return None

    df = df.copy()
    df["session"] = df.index.date
    df["tod"] = df.index.time

    cutoff_time = up_to.time()
    sessions = sorted(df["session"].unique())
    today_date = today.date()
    prior_sessions = [s for s in sessions if s != today_date]
    if not prior_sessions:
        return None

    cum_totals: list[float] = []
    for s in prior_sessions[-VOL_INTRADAY_LOOKBACK_DAYS:]:
        chunk = df[(df["session"] == s) & (df["tod"] <= cutoff_time)]
        if chunk.empty:
            continue
        cum_totals.append(float(chunk["Volume"].sum()))

    if not cum_totals:
        return None
    return float(np.mean(cum_totals))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_symbols(symbols: Iterable[str]) -> list[dict]:
    """Run the abnormal-volume scan over ``symbols`` and return one dict
    per symbol describing today's session pressure."""

    syms = [s.strip().upper() for s in symbols if s and s.strip()]
    syms = list(dict.fromkeys(syms))  # de-dupe, preserve order
    if not syms:
        return []

    out: list[dict] = []

    for sym in syms:
        try:
            intraday = yf.download(
                sym,
                period=f"{VOL_INTRADAY_LOOKBACK_DAYS + 2}d",
                interval="1m",
                progress=False,
                auto_adjust=False,
                prepost=False,
                threads=False,
            )
            intraday = _flatten(intraday)
            if intraday is None or intraday.empty:
                out.append(_empty_row(sym, reason="no intraday data"))
                continue

            intraday = _to_pt_index(intraday)
            intraday = intraday.dropna(subset=["Close"])
            if intraday.empty:
                out.append(_empty_row(sym, reason="no intraday data"))
                continue

            last_ts = intraday.index[-1]
            today = pd.Timestamp(last_ts).normalize()
            today_bars = intraday[intraday.index.normalize() == today]

            if today_bars.empty:
                # Market may not be open yet today — fall back to
                # most recent session in the data.
                last_session = intraday.index.normalize().unique().max()
                today = last_session
                today_bars = intraday[intraday.index.normalize() == today]

            if today_bars.empty:
                out.append(_empty_row(sym, reason="no session bars"))
                continue

            close_today = float(today_bars["Close"].iloc[-1])
            open_today = float(today_bars["Open"].iloc[0])
            vwap_num = (today_bars["Close"] * today_bars["Volume"]).sum()
            vwap_den = today_bars["Volume"].sum()
            vwap = float(vwap_num / vwap_den) if vwap_den else None

            today_vol = float(today_bars["Volume"].sum())
            buy_d, sell_d = _classify_minute_bars(today_bars)
            total_d = buy_d + sell_d
            buy_share = (buy_d / total_d) if total_d > 0 else 0.5
            net_delta = buy_d - sell_d

            typical_vol = _typical_volume_by_minute(
                intraday, today=today, up_to=last_ts,
            )
            rel_vol = (today_vol / typical_vol) if typical_vol else None

            # Daily baseline (for context — full-session avg)
            try:
                daily = yf.download(
                    sym,
                    period=f"{VOL_DAILY_LOOKBACK_DAYS + 5}d",
                    interval="1d",
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
                daily = _flatten(daily)
                avg_daily_vol = (
                    float(daily["Volume"].tail(VOL_DAILY_LOOKBACK_DAYS).mean())
                    if daily is not None and not daily.empty else None
                )
                prev_close = (
                    float(daily["Close"].iloc[-2])
                    if daily is not None and len(daily) >= 2 else None
                )
            except Exception:
                avg_daily_vol = None
                prev_close = None

            chg_pct = (
                (close_today / prev_close - 1) * 100
                if prev_close else (close_today / open_today - 1) * 100
            )

            signal = _signal_from(rel_vol, buy_share)

            out.append({
                "symbol": sym,
                "price": round(close_today, 2),
                "chg": round(chg_pct, 2),
                "vwap": round(vwap, 2) if vwap is not None else None,
                "today_vol": int(today_vol),
                "typical_vol": int(typical_vol) if typical_vol else None,
                "rel_vol": round(rel_vol, 2) if rel_vol is not None else None,
                "avg_daily_vol": int(avg_daily_vol) if avg_daily_vol else None,
                "buy_dollar_vol": round(buy_d, 0),
                "sell_dollar_vol": round(sell_d, 0),
                "buy_share": round(buy_share * 100, 1),
                "net_delta": round(net_delta, 0),
                "signal": signal,
                "as_of": _format_pt(last_ts),
            })
        except Exception as e:
            out.append(_empty_row(sym, reason=f"error: {e}"))

    return out


def _signal_from(rel_vol: float | None, buy_share: float) -> str:
    """Combine relative-volume magnitude with directional skew into a
    single human-readable label used by the table styling."""
    if rel_vol is None:
        return "—"

    magnitude = ""
    if rel_vol >= VOL_REL_EXTREME:
        magnitude = "EXTREME"
    elif rel_vol >= VOL_REL_ABNORMAL:
        magnitude = "ABNORMAL"
    else:
        magnitude = "Normal"

    if magnitude == "Normal":
        return magnitude

    if buy_share >= VOL_BUY_PRESSURE:
        return f"{magnitude} ↑ BUY"
    if buy_share <= VOL_SELL_PRESSURE:
        return f"{magnitude} ↓ SELL"
    return f"{magnitude} • mixed"


# ---------------------------------------------------------------------------
# 5-minute spike detector
# ---------------------------------------------------------------------------

def _resample_5m(intraday_1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-minute OHLCV into non-overlapping 5-minute bars.

    Resampling is left-labeled and right-closed so a 14:35 bar covers
    14:35:00–14:39:59, matching how most charting platforms label
    intraday bars."""
    df = _flatten(intraday_1m).dropna(subset=["Close"])
    if df.empty:
        return df
    agg = df.resample("5min", label="left", closed="left").agg({
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    })
    return agg.dropna(subset=["Open", "Close"])


def _spike_signal(z: float, rel: float, buy: float, sell: float) -> str:
    if z >= 3.0 or rel >= 3.0:
        magnitude = "EXTREME"
    elif z >= 2.5 or rel >= 2.4:
        magnitude = "STRONG"
    else:
        magnitude = "SPIKE"

    total = buy + sell
    if total <= 0:
        return magnitude
    share = buy / total
    if share >= VOL_SPIKE_DELTA_THRESHOLD:
        return f"{magnitude} \u2191 BUY"
    if share <= (1 - VOL_SPIKE_DELTA_THRESHOLD):
        return f"{magnitude} \u2193 SELL"
    return f"{magnitude} \u2022 mixed"


def scan_spikes(symbols: Iterable[str],
                lookback_days: int = 5,
                z_threshold: float | None = None,
                rel_threshold: float | None = None,
                max_results: int | None = None,
                today_only: bool = True) -> list[dict]:
    """Detect 5-minute volume + delta spikes across ``symbols``.

    A 5-minute bar is reported when its volume z-score exceeds
    ``z_threshold`` *or* its relative volume (vs the trailing
    ``VOL_SPIKE_LOOKBACK_BARS``-bar mean) exceeds ``rel_threshold``.
    Buy / sell pressure for each spike is computed from the 1-minute
    sub-bars inside that 5-minute window using the same tick-rule
    classifier as the session scanner.
    """

    z_threshold = z_threshold if z_threshold is not None else VOL_SPIKE_Z_THRESHOLD
    rel_threshold = rel_threshold if rel_threshold is not None else VOL_SPIKE_REL_THRESHOLD
    max_results = max_results if max_results is not None else VOL_SPIKE_MAX_RESULTS

    syms = [s.strip().upper() for s in symbols if s and s.strip()]
    syms = list(dict.fromkeys(syms))
    if not syms:
        return []

    events: list[dict] = []

    for sym in syms:
        try:
            intraday_1m = yf.download(
                sym,
                period=f"{lookback_days + 2}d",
                interval="1m",
                progress=False,
                auto_adjust=False,
                prepost=False,
                threads=False,
            )
            intraday_1m = _flatten(intraday_1m)
            if intraday_1m is None or intraday_1m.empty:
                continue

            intraday_1m = _to_pt_index(intraday_1m)
            bars_5m = _resample_5m(intraday_1m)
            if bars_5m.empty or len(bars_5m) <= VOL_SPIKE_LOOKBACK_BARS:
                continue

            vol = bars_5m["Volume"].astype(float)
            # Use only bars strictly *before* the current bar to avoid
            # leaking the spike itself into its own baseline.
            mean = vol.shift(1).rolling(VOL_SPIKE_LOOKBACK_BARS,
                                          min_periods=10).mean()
            std = vol.shift(1).rolling(VOL_SPIKE_LOOKBACK_BARS,
                                         min_periods=10).std()
            z_series = (vol - mean) / std
            rel_series = vol / mean

            if today_only:
                last_session = bars_5m.index.normalize().max()
                target_idx = bars_5m.index[bars_5m.index.normalize() == last_session]
            else:
                target_idx = bars_5m.index

            for ts in target_idx:
                z = float(z_series.loc[ts]) if ts in z_series.index else np.nan
                rel = float(rel_series.loc[ts]) if ts in rel_series.index else np.nan
                if pd.isna(z) and pd.isna(rel):
                    continue
                if (pd.isna(z) or z < z_threshold) and (
                    pd.isna(rel) or rel < rel_threshold):
                    continue

                row = bars_5m.loc[ts]
                bucket_end = ts + pd.Timedelta(minutes=5)
                sub = intraday_1m[(intraday_1m.index >= ts)
                                  & (intraday_1m.index < bucket_end)]
                buy_d, sell_d = _classify_minute_bars(sub)
                total_d = buy_d + sell_d
                buy_share = (buy_d / total_d * 100) if total_d > 0 else None

                open_ = float(row["Open"])
                close = float(row["Close"])
                chg_bar = (close / open_ - 1) * 100 if open_ else 0.0

                events.append({
                    "symbol": sym,
                    "ts": _format_pt(ts),
                    "ts_sort": _to_pt(ts).isoformat(),
                    "price": round(close, 2),
                    "chg_bar": round(chg_bar, 2),
                    "volume": int(row["Volume"]),
                    "vol_z": round(z, 2) if not pd.isna(z) else None,
                    "rel_vol": round(rel, 2) if not pd.isna(rel) else None,
                    "buy_dollar": round(buy_d, 0),
                    "sell_dollar": round(sell_d, 0),
                    "delta": round(buy_d - sell_d, 0),
                    "buy_share": round(buy_share, 1) if buy_share is not None else None,
                    "signal": _spike_signal(
                        z if not pd.isna(z) else 0.0,
                        rel if not pd.isna(rel) else 0.0,
                        buy_d, sell_d,
                    ),
                })
        except Exception as e:
            # Skip the symbol on any data hiccup; do not abort the whole scan.
            print(f"[VolumeScanner] {sym}: {e}")
            continue

    events.sort(key=lambda e: e["ts_sort"], reverse=True)
    return events[:max_results]


# ---------------------------------------------------------------------------
# Intraday timeline + news (Move Investigator)
# ---------------------------------------------------------------------------

def _classify_per_minute(bars: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Vectorised tick-rule classification on each minute bar.

    Returns ``(buy_dollar_per_min, sell_dollar_per_min)`` Series aligned
    to the input index. Doji bars are split 50/50.
    """
    o = bars["Open"].astype(float)
    c = bars["Close"].astype(float)
    v = bars["Volume"].astype(float)
    dollar = c * v
    up = c > o
    down = c < o
    flat = ~(up | down)
    buy = dollar.where(up, 0.0).fillna(0.0) + 0.5 * dollar.where(flat, 0.0).fillna(0.0)
    sell = dollar.where(down, 0.0).fillna(0.0) + 0.5 * dollar.where(flat, 0.0).fillna(0.0)
    return buy, sell


def get_intraday_timeline(symbol: str, lookback_days: int = 2) -> dict | None:
    """Return a Plotly-ready intraday payload for ``symbol`` covering the
    last ``lookback_days`` regular sessions in Pacific Time.

    Includes 1-minute OHLCV + per-bar buy/sell dollar volume, session
    VWAP, session-aware cumulative delta, plus 5-minute spike metrics
    (vol z-score, rel vol, buy share, delta, signal) for the same window.
    """

    sym = (symbol or "").strip().upper()
    if not sym:
        return None

    try:
        intraday = yf.download(
            sym,
            period=f"{lookback_days + 2}d",
            interval="1m",
            progress=False,
            auto_adjust=False,
            prepost=False,
            threads=False,
        )
    except Exception as e:
        print(f"[Investigator] {sym}: {e}")
        return None

    intraday = _flatten(intraday)
    if intraday is None or intraday.empty:
        return None
    intraday = _to_pt_index(intraday).dropna(subset=["Close"])
    if intraday.empty:
        return None

    o = intraday["Open"].astype(float)
    h = intraday["High"].astype(float)
    lo = intraday["Low"].astype(float)
    c = intraday["Close"].astype(float)
    v = intraday["Volume"].astype(float)

    buy_1m, sell_1m = _classify_per_minute(intraday)
    delta_1m = buy_1m - sell_1m

    # Session-aware running totals (VWAP and cumulative delta both reset
    # at the start of each session).
    sessions = pd.Series(intraday.index.normalize(), index=intraday.index)
    cum_pv = (c * v).groupby(sessions).cumsum()
    cum_v = v.groupby(sessions).cumsum()
    vwap = cum_pv / cum_v.replace(0, np.nan)
    cum_delta = delta_1m.groupby(sessions).cumsum()

    # 5-minute aggregation
    bars_5m = _resample_5m(intraday)
    buy_5m = buy_1m.resample("5min", label="left", closed="left").sum().reindex(bars_5m.index).fillna(0.0)
    sell_5m = sell_1m.resample("5min", label="left", closed="left").sum().reindex(bars_5m.index).fillna(0.0)
    delta_5m = buy_5m - sell_5m
    total_5m = (buy_5m + sell_5m).replace(0, np.nan)
    buy_share_5m = (buy_5m / total_5m * 100)

    vol_5m = bars_5m["Volume"].astype(float)
    mean = vol_5m.shift(1).rolling(VOL_SPIKE_LOOKBACK_BARS, min_periods=10).mean()
    std = vol_5m.shift(1).rolling(VOL_SPIKE_LOOKBACK_BARS, min_periods=10).std()
    z5 = (vol_5m - mean) / std
    rel5 = vol_5m / mean

    spike_rows: list[dict] = []
    for ts in bars_5m.index:
        z = float(z5.loc[ts]) if ts in z5.index and not pd.isna(z5.loc[ts]) else None
        rel = float(rel5.loc[ts]) if ts in rel5.index and not pd.isna(rel5.loc[ts]) else None
        if z is None and rel is None:
            continue
        if (z is None or z < VOL_SPIKE_Z_THRESHOLD) and (
            rel is None or rel < VOL_SPIKE_REL_THRESHOLD):
            continue
        b = float(buy_5m.loc[ts])
        s = float(sell_5m.loc[ts])
        spike_rows.append({
            "ts": _format_pt(ts),
            "ts_iso": _to_pt(ts).isoformat(),
            "price": round(float(bars_5m.loc[ts, "Close"]), 2),
            "vol_z": round(z, 2) if z is not None else None,
            "rel_vol": round(rel, 2) if rel is not None else None,
            "buy_dollar": round(b, 0),
            "sell_dollar": round(s, 0),
            "buy_share": round(b / (b + s) * 100, 1) if (b + s) > 0 else None,
            "delta": round(b - s, 0),
            "signal": _spike_signal(
                z if z is not None else 0.0,
                rel if rel is not None else 0.0,
                b, s),
        })
    spike_rows.sort(key=lambda r: r["ts_iso"], reverse=True)

    return {
        "symbol": sym,
        "ts_1m": [t.isoformat() for t in intraday.index],
        "open": o.tolist(),
        "high": h.tolist(),
        "low": lo.tolist(),
        "close": c.tolist(),
        "volume": v.tolist(),
        "buy_1m": buy_1m.tolist(),
        "sell_1m": sell_1m.tolist(),
        "delta_1m": delta_1m.tolist(),
        "cum_delta": cum_delta.tolist(),
        "vwap": vwap.tolist(),
        "spike_rows": spike_rows,
    }


def summarize_window(timeline: dict,
                     start_iso: str | None = None,
                     end_iso: str | None = None) -> dict:
    """Compute price / volume / order-flow stats for the [start, end]
    sub-window of a timeline payload (timestamps in PT ISO format).

    If both ``start_iso`` and ``end_iso`` are ``None``, the full last
    available session is summarized.
    """
    if not timeline:
        return {}

    ts = pd.to_datetime(timeline["ts_1m"], utc=False)
    ts = pd.DatetimeIndex(ts)
    if ts.tz is None:
        ts = ts.tz_localize(PT_TZ)
    else:
        ts = ts.tz_convert(PT_TZ)
    df = pd.DataFrame({
        "open": timeline["open"], "high": timeline["high"],
        "low":  timeline["low"],  "close": timeline["close"],
        "volume": timeline["volume"],
        "buy": timeline["buy_1m"], "sell": timeline["sell_1m"],
    }, index=ts)

    if start_iso and end_iso:
        start = pd.Timestamp(start_iso)
        end = pd.Timestamp(end_iso)
        if start.tzinfo is None:
            start = start.tz_localize(PT_TZ)
        else:
            start = start.tz_convert(PT_TZ)
        if end.tzinfo is None:
            end = end.tz_localize(PT_TZ)
        else:
            end = end.tz_convert(PT_TZ)
        window = df.loc[(df.index >= start) & (df.index <= end)]
        scope_label = f"{_format_pt(start, with_date=False)} \u2192 {_format_pt(end, with_date=False)}"
    else:
        last_session = df.index.normalize().max()
        window = df[df.index.normalize() == last_session]
        scope_label = f"Session {last_session.strftime('%Y-%m-%d')}"

    if window.empty:
        return {"scope": scope_label, "empty": True}

    p_start = float(window["open"].iloc[0])
    p_end = float(window["close"].iloc[-1])
    move_pct = (p_end / p_start - 1) * 100 if p_start else 0.0
    p_high = float(window["high"].max())
    p_low = float(window["low"].min())

    total_vol = int(window["volume"].sum())
    buy = float(window["buy"].sum())
    sell = float(window["sell"].sum())
    net_delta = buy - sell
    buy_share = (buy / (buy + sell) * 100) if (buy + sell) > 0 else 50.0

    # Compare window volume to same-time-of-day baseline from prior days
    prior = df[df.index.normalize() < window.index.normalize().max()]
    typical_vol = None
    if not prior.empty:
        cutoff_start = window.index[0].time()
        cutoff_end = window.index[-1].time()
        prior_match = prior[(prior.index.time >= cutoff_start)
                              & (prior.index.time <= cutoff_end)]
        if not prior_match.empty:
            sessions_count = prior_match.index.normalize().nunique()
            if sessions_count:
                typical_vol = float(prior_match["volume"].sum() / sessions_count)
    rel_vol = (total_vol / typical_vol) if typical_vol else None

    return {
        "scope": scope_label,
        "price_start": round(p_start, 2),
        "price_end": round(p_end, 2),
        "move_pct": round(move_pct, 2),
        "high": round(p_high, 2),
        "low": round(p_low, 2),
        "total_vol": total_vol,
        "typical_vol": int(typical_vol) if typical_vol else None,
        "rel_vol": round(rel_vol, 2) if rel_vol else None,
        "buy_dollar": round(buy, 0),
        "sell_dollar": round(sell, 0),
        "net_delta": round(net_delta, 0),
        "buy_share": round(buy_share, 1),
        "bar_count": len(window),
        "empty": False,
    }


def fetch_news(symbol: str, max_items: int = 20) -> list[dict]:
    """Pull recent news headlines for ``symbol`` via yfinance and return
    a list normalized for display (timestamps in PT)."""

    sym = (symbol or "").strip().upper()
    if not sym:
        return []

    try:
        raw = yf.Ticker(sym).news or []
    except Exception as e:
        print(f"[Investigator news] {sym}: {e}")
        return []

    items: list[dict] = []
    for entry in raw[:max_items]:
        # yfinance now wraps fields in a "content" sub-dict; older
        # versions return them at the top level — handle both.
        content = entry.get("content") or entry
        title = content.get("title") or entry.get("title") or ""
        if not title:
            continue

        publisher = ""
        prov = content.get("provider")
        if isinstance(prov, dict):
            publisher = prov.get("displayName") or ""
        publisher = publisher or content.get("publisher") or entry.get("publisher") or ""

        link = ""
        ct = content.get("clickThroughUrl") or content.get("canonicalUrl")
        if isinstance(ct, dict):
            link = ct.get("url") or ""
        link = link or entry.get("link") or ""

        ts_str = ""
        ts_iso = ""
        unix = entry.get("providerPublishTime")
        pub_date = content.get("pubDate") or content.get("displayTime")
        try:
            if unix:
                pt = _to_pt(pd.Timestamp(int(unix), unit="s", tz="UTC"))
            elif pub_date:
                pt = _to_pt(pd.Timestamp(pub_date))
            else:
                pt = None
            if pt is not None:
                ts_str = pt.strftime("%Y-%m-%d %H:%M PT")
                ts_iso = pt.isoformat()
        except Exception:
            ts_str = str(pub_date or "")

        summary = content.get("summary") or content.get("description") or ""
        items.append({
            "ts": ts_str,
            "ts_iso": ts_iso,
            "title": title,
            "publisher": publisher,
            "link": link,
            "summary": summary,
        })

    items.sort(key=lambda x: x.get("ts_iso") or "", reverse=True)
    return items


# ---------------------------------------------------------------------------
# Volume History — chronological per-bar tape with selectable timeframe
# ---------------------------------------------------------------------------

# Map UI timeframe values to (pandas_offset, rolling_window_bars).
# Rolling window is sized so the baseline covers ~100 minutes of trading
# regardless of bar size (e.g. 5m → 20 bars, 15m → 7 bars).
TIMEFRAME_OPTIONS: dict[str, tuple[str, int]] = {
    "1m":  ("1min",  60),
    "5m":  ("5min",  20),
    "10m": ("10min", 12),
    "15m": ("15min", 8),
    "30m": ("30min", 6),
    "1h":  ("60min", 5),
    "2h":  ("120min", 4),
    "4h":  ("240min", 3),
    "1d":  ("1D",     5),
}


def get_volume_history(symbol: str,
                       timeframe: str = "5m",
                       lookback_days: int = 1) -> list[dict]:
    """Return a chronological tape of volume / order-flow metrics for
    ``symbol`` resampled to ``timeframe``.

    Each row is a single bar (ascending time order — oldest first) with
    every metric a discretionary trader cares about: bar OHLC + range,
    raw volume + cumulative session volume, relative-volume vs a rolling
    baseline, buy/sell dollar volume, buy share, per-bar delta, running
    cumulative delta, session VWAP, and price-vs-VWAP.
    """

    sym = (symbol or "").strip().upper()
    if not sym:
        return []

    tf_key = (timeframe or "5m").lower()
    offset, window = TIMEFRAME_OPTIONS.get(
        tf_key, TIMEFRAME_OPTIONS["5m"])

    try:
        intraday = yf.download(
            sym,
            period=f"{lookback_days + 2}d",
            interval="1m",
            progress=False,
            auto_adjust=False,
            prepost=False,
            threads=False,
        )
    except Exception as e:
        print(f"[VolumeHistory] {sym}: {e}")
        return []

    intraday = _flatten(intraday)
    if intraday is None or intraday.empty:
        return []
    intraday = _to_pt_index(intraday).dropna(subset=["Close"])
    if intraday.empty:
        return []

    buy_1m, sell_1m = _classify_per_minute(intraday)

    bars = intraday.resample(offset, label="left", closed="left").agg({
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }).dropna(subset=["Open", "Close"])
    if bars.empty:
        return []

    buy = (buy_1m.resample(offset, label="left", closed="left").sum()
                  .reindex(bars.index).fillna(0.0))
    sell = (sell_1m.resample(offset, label="left", closed="left").sum()
                   .reindex(bars.index).fillna(0.0))
    delta = buy - sell

    vol = bars["Volume"].astype(float)
    mean = vol.shift(1).rolling(window, min_periods=max(3, window // 3)).mean()
    std = vol.shift(1).rolling(window, min_periods=max(3, window // 3)).std()
    vol_z = (vol - mean) / std
    rel_vol = vol / mean

    sessions = pd.Series(bars.index.normalize(), index=bars.index)
    cum_delta = delta.groupby(sessions).cumsum()
    cum_vol = vol.groupby(sessions).cumsum()
    cum_pv = (bars["Close"] * vol).groupby(sessions).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    session_total_vol = vol.groupby(sessions).transform("sum")
    pct_session = (vol / session_total_vol.replace(0, np.nan)) * 100

    rows: list[dict] = []
    for ts in bars.index:
        o = float(bars.loc[ts, "Open"])
        h = float(bars.loc[ts, "High"])
        lo = float(bars.loc[ts, "Low"])
        c = float(bars.loc[ts, "Close"])
        v_ = float(vol.loc[ts])
        b = float(buy.loc[ts])
        s = float(sell.loc[ts])
        bs = (b / (b + s) * 100) if (b + s) > 0 else None

        z_ = vol_z.loc[ts]
        r_ = rel_vol.loc[ts]
        vw = vwap.loc[ts]

        rows.append({
            "ts":        _to_pt(ts).strftime("%m-%d %H:%M PT"),
            "ts_iso":    _to_pt(ts).isoformat(),
            "session":   _to_pt(ts).strftime("%Y-%m-%d"),
            "open":      round(o, 2),
            "high":      round(h, 2),
            "low":       round(lo, 2),
            "close":     round(c, 2),
            "bar_chg":   round((c / o - 1) * 100, 2) if o else 0.0,
            "range":     round(h - lo, 2),
            "volume":    int(v_),
            "cum_vol":   int(cum_vol.loc[ts]),
            "pct_sess":  round(float(pct_session.loc[ts]), 2)
                          if not pd.isna(pct_session.loc[ts]) else None,
            "vol_z":     round(float(z_), 2) if not pd.isna(z_) else None,
            "rel_vol":   round(float(r_), 2) if not pd.isna(r_) else None,
            "buy_dollar":  round(b, 0),
            "sell_dollar": round(s, 0),
            "buy_share":   round(bs, 1) if bs is not None else None,
            "delta":     round(b - s, 0),
            "cum_delta": round(float(cum_delta.loc[ts]), 0),
            "vwap":      round(float(vw), 2) if not pd.isna(vw) else None,
            "vwap_diff": round(c - float(vw), 2) if not pd.isna(vw) else None,
        })

    return rows


# ---------------------------------------------------------------------------

def _empty_row(sym: str, reason: str) -> dict:
    return {
        "symbol": sym,
        "price": None,
        "chg": None,
        "vwap": None,
        "today_vol": None,
        "typical_vol": None,
        "rel_vol": None,
        "avg_daily_vol": None,
        "buy_dollar_vol": None,
        "sell_dollar_vol": None,
        "buy_share": None,
        "net_delta": None,
        "signal": reason,
        "as_of": "",
    }
