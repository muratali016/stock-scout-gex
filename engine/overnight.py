"""Overnight positioning scanner.

Goal
----
Quantify late-day options + price action signals that historically lead
to overnight gaps, using only free yfinance data:

* **Vol / OI ratio** per strike per side. Today's volume vs yesterday's
  settlement OI tells us how much of the flow is **fresh** vs churning
  existing positions.
* **Bid-ask aggression** per row, ``(last - bid) / (ask - bid)``. Closer
  to 1 = bought at the offer (bullish aggressor); closer to 0 = sold to
  the bid (bearish aggressor). Same idea as the equity tick-rule but
  applied per-option-row.
* **$ Notional** per row, ``volume * last * 100``. Filters out tiny
  retail lotto tickets and surfaces real institutional sizing.
* **Day's range location** of spot at session close — a "close-on-highs"
  finish combined with bullish options flow is a high-conviction
  overnight setup.

Bias score
----------
Per symbol, we combine the call-side and put-side notional × aggression
into a single ``[-100, +100]`` score:

    raw = (call_score - put_score) / (call_score + put_score)
    bias_score = clamp(raw * 100 + eod_modifier, -100, +100)

where ``call_score`` and ``put_score`` only sum rows that look like
*new* positioning (vol/oi above a threshold) and have credible
aggression (between 0 and 1).

The honest caveats
------------------
* OI is yesterday's settlement (OCC publishes once/day). On expiry days
  and after big-flow days the vol/oi ratio can be very large simply
  because OI is stale.
* The bid-ask aggression is a snapshot from the *last* print, not a
  trade-tape distribution. It's a directional hint, not a certainty.
* Indexes (SPX/NDX) are not on yfinance — use the ETF (SPY/QQQ/IWM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf


CONTRACT_MULT = 100

# Thresholds used by the default screen. Tunable from the UI.
DEFAULT_VOL_OI = 0.30
DEFAULT_AGGRESSION = 0.60
DEFAULT_MIN_NOTIONAL = 50_000        # $ — filter retail dust
DEFAULT_DTE_MAX = 5                  # near-dated only


# ---------------------------------------------------------------------------
# Per-symbol containers
# ---------------------------------------------------------------------------

@dataclass
class FlowRow:
    expiry: str
    dte: int
    side: str                 # "C" or "P"
    strike: float
    volume: int
    open_interest: int
    vol_oi: float | None
    last: float
    bid: float
    ask: float
    aggression: float | None  # 0..1; None if spread invalid
    notional: float           # $
    moneyness_pct: float | None  # (K - S) / S * 100  (calls: + = OTM)
    iv: float | None


@dataclass
class SymbolOvernight:
    symbol: str
    spot: float
    day_chg_pct: float | None
    day_range_pos: float | None    # 0..1 — close vs day's low-high
    day_high: float | None
    day_low: float | None
    bias_score: int                # -100..+100
    bias_label: str                # "BULLISH" / "NEUTRAL" / "BEARISH" etc.
    call_notional: float
    put_notional: float
    call_put_ratio: float | None
    call_aggression: float | None  # vol-weighted, 0..1
    put_aggression: float | None
    top_call_strike: float | None
    top_call_vol_oi: float | None
    top_put_strike: float | None
    top_put_vol_oi: float | None
    last_hour_delta_dollar: float | None
    last_hour_rel_vol: float | None
    news_count: int
    calls: list[FlowRow] = field(default_factory=list)
    puts: list[FlowRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    as_of: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aggression(last: float, bid: float, ask: float) -> float | None:
    """Tick-rule-ish buy/sell aggression score in [0,1]."""
    try:
        last = float(last); bid = float(bid); ask = float(ask)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(last) and np.isfinite(bid) and np.isfinite(ask)):
        return None
    if ask <= 0 or bid < 0 or ask <= bid:
        return None
    a = (last - bid) / (ask - bid)
    return float(max(0.0, min(1.0, a)))


def _safe_int(v) -> int:
    try:
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return 0
        return int(v)
    except (TypeError, ValueError):
        return 0


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _dte(expiry: str, today: date) -> int:
    try:
        ed = datetime.fromisoformat(expiry).date()
    except ValueError:
        return -1
    return (ed - today).days


def _last_hour_window(intraday: pd.DataFrame) -> pd.DataFrame:
    """Slice the trailing 60-minute window of the last session in the frame."""
    if intraday is None or intraday.empty:
        return pd.DataFrame()
    df = intraday.copy()
    df = df.dropna(subset=["Close"])
    if df.empty:
        return df
    last_ts = df.index[-1]
    return df[df.index >= (last_ts - pd.Timedelta(minutes=60))]


def _classify_buy_sell(bars: pd.DataFrame) -> tuple[float, float]:
    if bars is None or bars.empty:
        return 0.0, 0.0
    o = bars["Open"].astype(float)
    c = bars["Close"].astype(float)
    v = bars["Volume"].astype(float)
    dollar = c * v
    up = c > o; down = c < o; flat = ~(up | down)
    buy = float(dollar[up].sum() + 0.5 * dollar[flat].sum())
    sell = float(dollar[down].sum() + 0.5 * dollar[flat].sum())
    return buy, sell


# ---------------------------------------------------------------------------
# Core per-symbol analysis
# ---------------------------------------------------------------------------

def analyze_symbol(symbol: str,
                   dte_max: int = DEFAULT_DTE_MAX,
                   vol_oi_min: float = DEFAULT_VOL_OI,
                   aggression_min: float = DEFAULT_AGGRESSION,
                   min_notional: float = DEFAULT_MIN_NOTIONAL,
                   strike_window_pct: float = 0.10,
                   include_itm: bool = False) -> SymbolOvernight | None:
    """Run the full overnight analysis on one ticker."""

    sym = (symbol or "").strip().upper()
    if not sym:
        return None

    tk = yf.Ticker(sym)

    # ---- Spot + day range -----------------------------------------------
    try:
        hist = tk.history(period="3d", interval="1d", auto_adjust=False)
    except Exception:
        hist = None

    spot = None; day_high = day_low = None; chg_pct = None; range_pos = None
    if hist is not None and not hist.empty:
        last = hist.iloc[-1]
        spot = _safe_float(last.get("Close"))
        day_high = _safe_float(last.get("High"))
        day_low = _safe_float(last.get("Low"))
        if len(hist) >= 2:
            prev_close = _safe_float(hist.iloc[-2].get("Close"))
            if spot and prev_close:
                chg_pct = (spot / prev_close - 1) * 100
        if spot is not None and day_high and day_low and day_high > day_low:
            range_pos = (spot - day_low) / (day_high - day_low)

    if not spot or spot <= 0:
        return SymbolOvernight(
            symbol=sym, spot=0.0, day_chg_pct=None, day_range_pos=None,
            day_high=None, day_low=None,
            bias_score=0, bias_label="NO DATA",
            call_notional=0.0, put_notional=0.0, call_put_ratio=None,
            call_aggression=None, put_aggression=None,
            top_call_strike=None, top_call_vol_oi=None,
            top_put_strike=None, top_put_vol_oi=None,
            last_hour_delta_dollar=None, last_hour_rel_vol=None,
            news_count=0,
            notes=[f"No spot price available for {sym}."],
            as_of=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        )

    # ---- Options expirations within DTE window --------------------------
    try:
        all_exps = list(tk.options or [])
    except Exception:
        all_exps = []

    today = datetime.utcnow().date()
    target_exps = [e for e in all_exps if 0 <= _dte(e, today) <= dte_max]

    lo_strike = spot * (1.0 - strike_window_pct)
    hi_strike = spot * (1.0 + strike_window_pct)

    calls: list[FlowRow] = []
    puts: list[FlowRow] = []
    notes: list[str] = []

    for exp in target_exps:
        dte = _dte(exp, today)
        try:
            chain = tk.option_chain(exp)
        except Exception as exc:
            notes.append(f"{exp}: chain fetch failed")
            continue
        for side, df in (("C", chain.calls), ("P", chain.puts)):
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                K = _safe_float(r.get("strike"))
                if K is None or K < lo_strike or K > hi_strike:
                    continue
                vol = _safe_int(r.get("volume"))
                oi = _safe_int(r.get("openInterest"))
                if vol <= 0:
                    continue
                last = _safe_float(r.get("lastPrice")) or 0.0
                bid = _safe_float(r.get("bid")) or 0.0
                ask = _safe_float(r.get("ask")) or 0.0
                iv = _safe_float(r.get("impliedVolatility"))
                in_the_money = bool(r.get("inTheMoney"))
                if not include_itm and in_the_money:
                    continue
                vol_oi = (vol / oi) if oi > 0 else None
                notional = vol * last * CONTRACT_MULT
                if notional < min_notional:
                    continue
                agg = _aggression(last, bid, ask)
                moneyness = ((K - spot) / spot * 100) if spot else None
                row = FlowRow(
                    expiry=exp, dte=dte, side=side, strike=float(K),
                    volume=vol, open_interest=oi,
                    vol_oi=vol_oi, last=last, bid=bid, ask=ask,
                    aggression=agg, notional=notional,
                    moneyness_pct=moneyness, iv=iv,
                )
                if side == "C":
                    calls.append(row)
                else:
                    puts.append(row)

    # ---- Compute side aggregates ----------------------------------------
    def _side_metrics(rows: list[FlowRow]) -> tuple[float, float | None,
                                                     float | None,
                                                     FlowRow | None]:
        if not rows:
            return 0.0, None, None, None
        # qualifying rows for "real new positioning"
        qual = [r for r in rows
                if r.vol_oi is not None and r.vol_oi >= vol_oi_min
                and r.aggression is not None
                and r.aggression >= aggression_min]
        # if nothing qualifies, fall back to all rows for the score (with
        # zero qualifying weight)
        all_rows = rows if rows else []
        total_notional = float(sum(r.notional for r in all_rows))
        # vol-weighted aggression (uses all rows, requires aggression!=None)
        agg_pool = [r for r in all_rows if r.aggression is not None]
        if agg_pool:
            w = np.array([r.notional for r in agg_pool])
            a = np.array([r.aggression for r in agg_pool])
            vw_agg = float((a * w).sum() / w.sum()) if w.sum() > 0 else None
        else:
            vw_agg = None
        # qualifying-notional × aggression — used for the bias score
        if qual:
            q_score = float(sum(r.notional * r.aggression for r in qual))
        else:
            q_score = 0.0
        # top strike: highest vol/oi among qualifying rows (fallback: notional)
        if qual:
            top = max(qual, key=lambda r: r.vol_oi if r.vol_oi else 0.0)
        else:
            top = max(rows, key=lambda r: r.notional) if rows else None
        return total_notional, vw_agg, q_score, top

    call_notional, call_agg, call_q, call_top = _side_metrics(calls)
    put_notional, put_agg, put_q, put_top = _side_metrics(puts)

    # ---- Bias score ------------------------------------------------------
    denom = call_q + put_q
    if denom > 0:
        bias_raw = (call_q - put_q) / denom   # -1..+1
    else:
        # Fall back to raw notional skew when nothing meets the quality
        # filter — still informative directionally.
        d2 = call_notional + put_notional
        bias_raw = ((call_notional - put_notional) / d2) if d2 > 0 else 0.0
        if d2 > 0:
            notes.append("no rows met the vol/oi+aggression filter; "
                          "bias falls back to raw notional skew")

    eod_modifier = 0.0
    if range_pos is not None:
        eod_modifier = (range_pos - 0.5) * 20.0   # -10..+10
    bias_score = int(round(max(-100.0, min(100.0,
                                            bias_raw * 100.0 + eod_modifier))))

    if bias_score >= 40:
        bias_label = "STRONG BULLISH"
    elif bias_score >= 15:
        bias_label = "BULLISH"
    elif bias_score <= -40:
        bias_label = "STRONG BEARISH"
    elif bias_score <= -15:
        bias_label = "BEARISH"
    else:
        bias_label = "NEUTRAL"

    cp_ratio = (call_notional / put_notional) if put_notional > 0 else None

    # ---- Last-hour tape & news ------------------------------------------
    last_hour_delta = None
    last_hour_rel = None
    try:
        intra = yf.download(sym, period="3d", interval="1m",
                             progress=False, auto_adjust=False,
                             prepost=False, threads=False)
        if isinstance(intra.columns, pd.MultiIndex):
            intra.columns = intra.columns.get_level_values(0)
        if intra is not None and not intra.empty:
            idx = intra.index
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            intra.index = idx.tz_convert("America/Los_Angeles")
            last_session = intra.index.normalize().max()
            today_bars = intra[intra.index.normalize() == last_session]
            lh = _last_hour_window(today_bars)
            if not lh.empty:
                buy, sell = _classify_buy_sell(lh)
                last_hour_delta = buy - sell
                # Compare last-hour volume to prior days' last-hour avg
                prior = intra[intra.index.normalize() < last_session]
                if not prior.empty and not lh.empty:
                    start_t = lh.index[0].time()
                    end_t = lh.index[-1].time()
                    pm = prior[(prior.index.time >= start_t)
                                 & (prior.index.time <= end_t)]
                    if not pm.empty:
                        sessions = pm.index.normalize().nunique()
                        if sessions:
                            base = pm["Volume"].sum() / sessions
                            cur = lh["Volume"].sum()
                            last_hour_rel = float(cur / base) if base > 0 else None
    except Exception as exc:
        notes.append(f"intraday tape unavailable: {exc}")

    news_count = 0
    try:
        raw = tk.news or []
        cutoff = datetime.utcnow().timestamp() - 6 * 3600  # last 6h
        for entry in raw:
            content = entry.get("content") or entry
            ts_u = entry.get("providerPublishTime")
            pub = content.get("pubDate") or content.get("displayTime")
            if ts_u and ts_u >= cutoff:
                news_count += 1
            elif pub:
                try:
                    ts = pd.Timestamp(pub).timestamp()
                    if ts >= cutoff:
                        news_count += 1
                except Exception:
                    pass
    except Exception:
        pass

    return SymbolOvernight(
        symbol=sym,
        spot=float(spot),
        day_chg_pct=chg_pct,
        day_range_pos=range_pos,
        day_high=day_high,
        day_low=day_low,
        bias_score=bias_score,
        bias_label=bias_label,
        call_notional=call_notional,
        put_notional=put_notional,
        call_put_ratio=cp_ratio,
        call_aggression=call_agg,
        put_aggression=put_agg,
        top_call_strike=call_top.strike if call_top else None,
        top_call_vol_oi=call_top.vol_oi if call_top else None,
        top_put_strike=put_top.strike if put_top else None,
        top_put_vol_oi=put_top.vol_oi if put_top else None,
        last_hour_delta_dollar=last_hour_delta,
        last_hour_rel_vol=last_hour_rel,
        news_count=news_count,
        calls=sorted(calls, key=lambda r: r.notional, reverse=True),
        puts=sorted(puts, key=lambda r: r.notional, reverse=True),
        notes=notes,
        as_of=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )


# ---------------------------------------------------------------------------
# Multi-symbol scanner
# ---------------------------------------------------------------------------

def scan_overnight(symbols,
                   dte_max: int = DEFAULT_DTE_MAX,
                   vol_oi_min: float = DEFAULT_VOL_OI,
                   aggression_min: float = DEFAULT_AGGRESSION,
                   min_notional: float = DEFAULT_MIN_NOTIONAL,
                   include_itm: bool = False) -> list[SymbolOvernight]:
    syms = []
    for s in symbols or []:
        if isinstance(s, str):
            s = s.strip().upper()
            if s and s not in syms:
                syms.append(s)

    out: list[SymbolOvernight] = []
    for s in syms:
        try:
            res = analyze_symbol(
                s, dte_max=dte_max, vol_oi_min=vol_oi_min,
                aggression_min=aggression_min,
                min_notional=min_notional,
                include_itm=include_itm,
            )
        except Exception as exc:
            res = SymbolOvernight(
                symbol=s, spot=0.0, day_chg_pct=None, day_range_pos=None,
                day_high=None, day_low=None,
                bias_score=0, bias_label="ERROR",
                call_notional=0.0, put_notional=0.0, call_put_ratio=None,
                call_aggression=None, put_aggression=None,
                top_call_strike=None, top_call_vol_oi=None,
                top_put_strike=None, top_put_vol_oi=None,
                last_hour_delta_dollar=None, last_hour_rel_vol=None,
                news_count=0,
                notes=[f"analyze_symbol failed: {exc}"],
                as_of=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            )
        if res is not None:
            out.append(res)
    return out


# ---------------------------------------------------------------------------
# Serialization helpers for the Dash layer
# ---------------------------------------------------------------------------

def board_row(r: SymbolOvernight) -> dict:
    """Flatten a SymbolOvernight into a DataTable row."""
    return {
        "symbol": r.symbol,
        "spot": round(r.spot, 2) if r.spot else None,
        "chg_pct": round(r.day_chg_pct, 2) if r.day_chg_pct is not None else None,
        "range_pos": round(r.day_range_pos * 100, 1)
                      if r.day_range_pos is not None else None,
        "bias_score": r.bias_score,
        "bias_label": r.bias_label,
        "call_notional_m": round(r.call_notional / 1e6, 2),
        "put_notional_m": round(r.put_notional / 1e6, 2),
        "cp_ratio": round(r.call_put_ratio, 2)
                     if r.call_put_ratio is not None else None,
        "call_agg": round(r.call_aggression * 100, 1)
                     if r.call_aggression is not None else None,
        "put_agg": round(r.put_aggression * 100, 1)
                    if r.put_aggression is not None else None,
        "top_call_strike": r.top_call_strike,
        "top_call_vol_oi": round(r.top_call_vol_oi, 2)
                            if r.top_call_vol_oi is not None else None,
        "top_put_strike": r.top_put_strike,
        "top_put_vol_oi": round(r.top_put_vol_oi, 2)
                           if r.top_put_vol_oi is not None else None,
        "last_hour_delta": int(round(r.last_hour_delta_dollar))
                            if r.last_hour_delta_dollar is not None else None,
        "last_hour_rel": round(r.last_hour_rel_vol, 2)
                          if r.last_hour_rel_vol is not None else None,
        "news_count": r.news_count,
        "as_of": r.as_of,
    }


def flow_rows(rows: list[FlowRow]) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "expiry": r.expiry,
            "dte": r.dte,
            "strike": r.strike,
            "volume": r.volume,
            "oi": r.open_interest,
            "vol_oi": round(r.vol_oi, 2) if r.vol_oi is not None else None,
            "last": round(r.last, 2),
            "bid": round(r.bid, 2),
            "ask": round(r.ask, 2),
            "agg": round(r.aggression * 100, 1)
                    if r.aggression is not None else None,
            "notional_k": round(r.notional / 1000, 1),
            "moneyness": round(r.moneyness_pct, 2)
                         if r.moneyness_pct is not None else None,
            "iv": round(r.iv * 100, 1) if r.iv is not None else None,
        })
    return out
