"""Gamma Exposure (GEX) computation from free yfinance options data.

Pipeline
--------
1. Pull every expiration's option chain via ``yfinance`` (strike, open
   interest, implied volatility per side).
2. Compute Black–Scholes gamma per row using the chain's IV, spot, and
   risk-free rate.
3. Aggregate to dealer-positioning GEX:

   .. math::
      GEX_{strike} = \\Gamma \\times OI \\times 100 \\times S^2
                     \\times 0.01
                     \\times \\text{sign}_{\\,dealer}

   with the common vendor comparison convention:

      * call open interest contributes **positive** GEX
      * put open interest contributes **negative** GEX

   It is a sign convention, not direct knowledge of dealers' books.

4. Produce two views:

   * **2D heatmap**: rows = strikes, columns = expirations, color = net GEX.
   * **1D profile**:  net GEX by strike, aggregated across the included
     expirations (the curve used to find the zero-gamma flip).

Caveats
-------
* yfinance OI is end-of-day-ish (one session stale). That's fine for GEX
  which is a slow-moving positioning metric, but do not pitch this as live.
* IV in yfinance can be 0 or NaN for illiquid strikes — those rows are
  dropped before computing gamma.
* The call-positive / put-negative convention is common, but actual dealer
  positioning is proprietary and can differ contract by contract.
* Black–Scholes here does not model dividends, borrow, early exercise, or
  American-option effects; those choices can differ from premium vendors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import erf, exp, log, sqrt, pi

import numpy as np
import pandas as pd
import yfinance as yf


# Risk-free rate used for Black-Scholes. yfinance's 13-week T-bill (``^IRX``)
# could be fetched dynamically, but a 4-5% constant is well within the noise
# floor of gamma estimates and avoids extra HTTP roundtrips.
DEFAULT_RISK_FREE = 0.045

# yfinance can return ridiculous IV values for stale/illiquid contracts; clip.
MIN_IV = 0.01
MAX_IV = 5.0

# Each US listed option represents 100 shares.
CONTRACT_MULT = 100

# Scale the dollar-delta change to a one-percent move in the underlying.
# Omitting this factor reports exposure per 100% move and overstates the
# conventionally quoted GEX number by 100x.
ONE_PERCENT_MOVE = 0.01


# ---------------------------------------------------------------------------
# Black-Scholes gamma
# ---------------------------------------------------------------------------

def _norm_pdf(x: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * x * x) / sqrt(2.0 * pi)


def bs_gamma(S: float | np.ndarray,
             K: float | np.ndarray,
             T: float | np.ndarray,
             r: float,
             sigma: float | np.ndarray) -> np.ndarray:
    """Black–Scholes gamma for European options on a non-dividend stock.

    Same formula for calls and puts. ``T`` is in **years**, ``sigma`` is
    annualized vol. Inputs are broadcast like numpy arrays.
    """
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)

    # Guard against zero-division for expired / zero-IV rows.
    safe = (T > 0) & (sigma > 0) & (S > 0) & (K > 0)
    out = np.zeros_like(S * K * T * sigma, dtype=float)

    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * np.sqrt(T))
        gamma = _norm_pdf(d1) / (S * sigma * np.sqrt(T))

    out = np.where(safe, gamma, 0.0)
    return out


# ---------------------------------------------------------------------------
# Public result container
# ---------------------------------------------------------------------------

@dataclass
class GexResult:
    symbol: str
    spot: float
    as_of: str
    expirations: list[str] = field(default_factory=list)
    expiration_dtes: list[int] = field(default_factory=list)
    strikes: list[float] = field(default_factory=list)
    # heatmap[strike_idx][exp_idx] = net GEX in $
    heatmap: list[list[float]] = field(default_factory=list)
    # per-strike net GEX summed across all included expirations
    profile: list[float] = field(default_factory=list)
    call_profile: list[float] = field(default_factory=list)
    put_profile: list[float] = field(default_factory=list)
    call_oi_profile: list[float] = field(default_factory=list)
    put_oi_profile: list[float] = field(default_factory=list)
    # cumulative strike profile (diagnostic only; not the gamma flip)
    cumulative: list[float] = field(default_factory=list)
    # Whole-chain GEX after repricing gamma across hypothetical spot levels.
    scenario_spots: list[float] = field(default_factory=list)
    scenario_gex: list[float] = field(default_factory=list)
    flip_price: float | None = None
    total_gex: float = 0.0
    call_gex: float = 0.0
    put_gex: float = 0.0
    call_oi: float = 0.0
    put_oi: float = 0.0
    expiration_gex: list[dict] = field(default_factory=list)
    call_walls: list[dict] = field(default_factory=list)
    put_walls: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rows: int = 0  # raw rows used (debug)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _years_to(expiry: str, now: datetime) -> float:
    """Return time-to-expiry in years assuming 4 pm ET expiration."""
    try:
        exp_dt = datetime.fromisoformat(expiry)
    except ValueError:
        # yfinance returns "YYYY-MM-DD"; isoformat handles that fine.
        return 0.0
    # 4 pm ET ≈ 20:00 UTC; close enough for gamma sizing.
    exp_dt = exp_dt.replace(hour=20)
    seconds = (exp_dt - now).total_seconds()
    return max(seconds, 0.0) / (365.0 * 24 * 3600)


def _expiration_dte(expiry: str, reference_date) -> int | None:
    """Calendar DTE for a listed expiration relative to a session date."""
    try:
        return (datetime.fromisoformat(expiry).date() - reference_date).days
    except (TypeError, ValueError):
        return None


def _select_expirations(all_expirations: list[str],
                        max_expirations: int,
                        dtes: list[int] | None,
                        reference_date) -> tuple[list[str], list[int]]:
    selected_dtes: set[int] = set()
    for value in dtes or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            selected_dtes.add(parsed)

    matched: list[tuple[str, int]] = []
    for expiry in all_expirations:
        dte = _expiration_dte(expiry, reference_date)
        if dte is None or dte < 0:
            continue
        if selected_dtes and dte not in selected_dtes:
            continue
        matched.append((expiry, dte))

    limit = max(1, int(max_expirations))
    matched = matched[:limit]
    return [expiry for expiry, _ in matched], [dte for _, dte in matched]


def _spot_from_history(tk: yf.Ticker) -> float | None:
    try:
        # Match the current chain to the freshest freely available spot.
        h = tk.history(period="1d", interval="1m", auto_adjust=False,
                       prepost=False)
        if h is not None and not h.empty:
            close = pd.to_numeric(h["Close"], errors="coerce").dropna()
            if not close.empty:
                return float(close.iloc[-1])
    except Exception:
        pass
    try:
        h = tk.history(period="2d", interval="1d", auto_adjust=False)
        if h is not None and not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    try:
        h = tk.history(period="5d", interval="1d", auto_adjust=False)
        if h is not None and not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _normalize_iv(iv: pd.Series) -> pd.Series:
    iv = pd.to_numeric(iv, errors="coerce")
    iv = iv.where((iv > 0) & np.isfinite(iv))
    iv = iv.clip(lower=MIN_IV, upper=MAX_IV)
    return iv


def _scenario_curve(K: np.ndarray,
                    T: np.ndarray,
                    r: float,
                    sigma: np.ndarray,
                    oi: np.ndarray,
                    sign: np.ndarray,
                    low: float,
                    high: float,
                    points: int = 121) -> tuple[np.ndarray, np.ndarray]:
    """Reprice the entire chain across spot levels for a true GEX curve."""
    if low <= 0 or high <= low or len(K) == 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    spots = np.linspace(low, high, max(21, int(points)))
    spot_grid = spots[:, None]
    gamma = bs_gamma(
        S=spot_grid,
        K=np.asarray(K, dtype=float)[None, :],
        T=np.asarray(T, dtype=float)[None, :],
        r=r,
        sigma=np.asarray(sigma, dtype=float)[None, :],
    )
    gex = (
        gamma * np.asarray(oi, dtype=float)[None, :]
        * np.asarray(sign, dtype=float)[None, :]
        * CONTRACT_MULT * (spot_grid ** 2) * ONE_PERCENT_MOVE
    )
    return spots, np.sum(gex, axis=1)


def _find_level_crossing(levels: np.ndarray,
                         values: np.ndarray,
                         reference: float | None = None) -> float | None:
    """Interpolate zero crossings and return the one nearest ``reference``."""
    if len(levels) < 2 or len(levels) != len(values):
        return None
    crossings: list[float] = []
    for i in range(1, len(values)):
        a, b = float(values[i - 1]), float(values[i])
        if not (np.isfinite(a) and np.isfinite(b)):
            continue
        if a == 0:
            crossings.append(float(levels[i - 1]))
        elif (a < 0 < b) or (b < 0 < a):
            x0, x1 = float(levels[i - 1]), float(levels[i])
            crossings.append(x0 + (-a / (b - a)) * (x1 - x0))
    if not crossings:
        return None
    ref = float(reference) if reference is not None else float(np.mean(levels))
    return min(crossings, key=lambda x: abs(x - ref))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_gex(symbol: str,
                max_expirations: int = 8,
                strike_window_pct: float = 0.20,
                risk_free: float = DEFAULT_RISK_FREE,
                strike_bin: float | None = None,
                dtes: list[int] | None = None) -> GexResult:
    """Compute dealer-positioning GEX for ``symbol``.

    Parameters
    ----------
    symbol:
        Underlying ticker (e.g. ``"SPY"``, ``"TSLA"``). Indexes like
        ``"SPX"`` are not on yfinance — use the ETF proxy.
    max_expirations:
        Cap on how many expirations to include (sorted ascending in time).
        More expirations = more HTTP calls; 6-10 is a reasonable balance.
    strike_window_pct:
        Only include strikes within ``±strike_window_pct`` of spot. Far
        OTM strikes contribute negligible gamma and just add noise.
    risk_free:
        Annualised risk-free rate used in Black-Scholes. Default 4.5%.
    strike_bin:
        Optional bucket width to round strikes to. ``None`` keeps native
        strikes; useful for high-priced tickers where strike spacing is
        irregular across expirations.
    dtes:
        Optional exact calendar-DTE values to include, such as ``[0, 1]``.
        ``None`` or an empty list includes all expirations up to the cap.
    """

    sym = (symbol or "").strip().upper()
    if not sym:
        return GexResult(symbol="", spot=0.0, as_of="",
                         notes=["No symbol provided."])

    tk = yf.Ticker(sym)

    # Spot ------------------------------------------------------------------
    spot = _spot_from_history(tk)
    if spot is None or spot <= 0:
        return GexResult(symbol=sym, spot=0.0, as_of="",
                         notes=[f"Could not fetch spot price for {sym}."])

    # Expirations -----------------------------------------------------------
    try:
        all_exps = list(tk.options or [])
    except Exception as exc:
        return GexResult(symbol=sym, spot=spot, as_of="",
                         notes=[f"yfinance returned no options chain: {exc}"])

    if not all_exps:
        return GexResult(symbol=sym, spot=spot, as_of="",
                         notes=[f"No options listed for {sym} on yfinance."])

    now = datetime.utcnow()
    exps, _ = _select_expirations(
        all_exps, max_expirations, dtes, now.date())
    if not exps:
        requested = ", ".join(f"{int(v)}DTE" for v in sorted(set(dtes or [])))
        return GexResult(
            symbol=sym, spot=spot, as_of=now.strftime("%Y-%m-%d %H:%M UTC"),
            notes=[f"No listed expirations match {requested or 'the filter'}."],
        )

    lo_strike = spot * (1.0 - strike_window_pct)
    hi_strike = spot * (1.0 + strike_window_pct)

    # ---------------------------------------------------------------------
    # Build long-form rows: one per (strike, expiry, side)
    # ---------------------------------------------------------------------
    rows: list[dict] = []
    notes: list[str] = []
    used_exps: list[str] = []
    used_dtes: list[int] = []

    for exp in exps:
        try:
            chain = tk.option_chain(exp)
        except Exception as exc:
            notes.append(f"{exp}: chain fetch failed ({exc})")
            continue

        T = _years_to(exp, now)
        if T <= 0:
            notes.append(f"{exp}: already expired, skipped")
            continue

        for side, df in (("C", chain.calls), ("P", chain.puts)):
            if df is None or df.empty:
                continue
            d = df.copy()
            d["openInterest"] = pd.to_numeric(
                d.get("openInterest"), errors="coerce").fillna(0)
            d["impliedVolatility"] = _normalize_iv(d.get("impliedVolatility"))
            d["strike"] = pd.to_numeric(d.get("strike"), errors="coerce")
            d = d.dropna(subset=["strike", "impliedVolatility"])
            d = d[(d["strike"] >= lo_strike) & (d["strike"] <= hi_strike)]
            d = d[d["openInterest"] > 0]
            if d.empty:
                continue

            gamma = bs_gamma(
                S=spot,
                K=d["strike"].to_numpy(),
                T=T,
                r=risk_free,
                sigma=d["impliedVolatility"].to_numpy(),
            )
            sign = +1.0 if side == "C" else -1.0
            gex_dollars = (
                sign * gamma * d["openInterest"].to_numpy()
                * CONTRACT_MULT * (spot ** 2) * ONE_PERCENT_MOVE
            )

            for k, oi, iv, g, gx in zip(
                d["strike"].to_numpy(),
                d["openInterest"].to_numpy(),
                d["impliedVolatility"].to_numpy(),
                gamma, gex_dollars,
            ):
                rows.append({
                    "expiry": exp,
                    "strike": float(k),
                    "model_strike": float(k),
                    "side": side,
                    "oi": float(oi),
                    "iv": float(iv),
                    "T": float(T),
                    "gamma": float(g),
                    "gex": float(gx),
                })
        used_exps.append(exp)
        exp_dte = _expiration_dte(exp, now.date())
        used_dtes.append(int(exp_dte) if exp_dte is not None else -1)

    if not rows:
        return GexResult(symbol=sym, spot=spot,
                         as_of=now.strftime("%Y-%m-%d %H:%M UTC"),
                         expirations=used_exps,
                         expiration_dtes=used_dtes,
                         notes=notes + ["No usable option rows in window."])

    long_df = pd.DataFrame(rows)

    # Optional strike bucketing ------------------------------------------
    if strike_bin and strike_bin > 0:
        long_df["strike"] = (long_df["strike"] / strike_bin).round() * strike_bin

    # 2D heatmap: rows = strikes, cols = expirations ---------------------
    pivot = (long_df.groupby(["strike", "expiry"])["gex"].sum()
             .unstack(fill_value=0.0))
    pivot = pivot.reindex(columns=used_exps, fill_value=0.0)
    pivot = pivot.sort_index(ascending=True)

    strikes = [float(s) for s in pivot.index.tolist()]
    heatmap = [[float(v) for v in row] for row in pivot.to_numpy()]

    # 1D net GEX per strike (sum across expirations + sides) -------------
    profile_series = pivot.sum(axis=1)
    profile = [float(v) for v in profile_series.to_numpy()]
    total_gex = float(profile_series.sum())

    # Keep the cumulative-by-strike series as a diagnostic, but calculate
    # the gamma flip correctly by repricing the full chain at hypothetical
    # underlying prices and finding where total net GEX crosses zero.
    cumulative_arr = np.cumsum(profile_series.to_numpy())
    cumulative = [float(v) for v in cumulative_arr]

    scenario_spots_arr, scenario_gex_arr = _scenario_curve(
        K=long_df["model_strike"].to_numpy(),
        T=long_df["T"].to_numpy(),
        r=risk_free,
        sigma=long_df["iv"].to_numpy(),
        oi=long_df["oi"].to_numpy(),
        sign=np.where(long_df["side"].to_numpy() == "C", 1.0, -1.0),
        low=lo_strike,
        high=hi_strike,
    )
    flip_price = _find_level_crossing(
        scenario_spots_arr, scenario_gex_arr, reference=spot)

    # Top call / put walls (largest +/- contributors) --------------------
    side_sums = (long_df.groupby(["strike", "side"])["gex"].sum()
                 .unstack(fill_value=0.0))
    if "C" not in side_sums.columns:
        side_sums["C"] = 0.0
    if "P" not in side_sums.columns:
        side_sums["P"] = 0.0
    side_sums = side_sums.reindex(pivot.index, fill_value=0.0)
    call_profile = [float(v) for v in side_sums["C"].to_numpy()]
    put_profile = [float(v) for v in side_sums["P"].to_numpy()]

    oi_sums = (long_df.groupby(["strike", "side"])["oi"].sum()
               .unstack(fill_value=0.0).reindex(pivot.index, fill_value=0.0))
    if "C" not in oi_sums.columns:
        oi_sums["C"] = 0.0
    if "P" not in oi_sums.columns:
        oi_sums["P"] = 0.0
    call_oi_profile = [float(v) for v in oi_sums["C"].to_numpy()]
    put_oi_profile = [float(v) for v in oi_sums["P"].to_numpy()]

    expiry_sums = (long_df.groupby(["expiry", "side"])["gex"].sum()
                   .unstack(fill_value=0.0).reindex(used_exps, fill_value=0.0))
    if "C" not in expiry_sums.columns:
        expiry_sums["C"] = 0.0
    if "P" not in expiry_sums.columns:
        expiry_sums["P"] = 0.0
    expiration_gex = [
        {"expiry": str(exp), "call_gex": float(row["C"]),
         "put_gex": float(row["P"]),
         "net_gex": float(row["C"] + row["P"]),
         "dte": _expiration_dte(str(exp), now.date())}
        for exp, row in expiry_sums.iterrows()
    ]
    call_walls_df = side_sums.sort_values("C", ascending=False).head(5)
    put_walls_df = side_sums.sort_values("P", ascending=True).head(5)

    call_walls = [
        {"strike": float(k), "gex": float(r["C"])}
        for k, r in call_walls_df.iterrows() if r["C"] > 0
    ]
    put_walls = [
        {"strike": float(k), "gex": float(r["P"])}
        for k, r in put_walls_df.iterrows() if r["P"] < 0
    ]

    return GexResult(
        symbol=sym,
        spot=float(spot),
        as_of=now.strftime("%Y-%m-%d %H:%M UTC"),
        expirations=used_exps,
        expiration_dtes=used_dtes,
        strikes=strikes,
        heatmap=heatmap,
        profile=profile,
        call_profile=call_profile,
        put_profile=put_profile,
        call_oi_profile=call_oi_profile,
        put_oi_profile=put_oi_profile,
        cumulative=cumulative,
        scenario_spots=[float(v) for v in scenario_spots_arr],
        scenario_gex=[float(v) for v in scenario_gex_arr],
        flip_price=flip_price,
        total_gex=total_gex,
        call_gex=float(long_df.loc[long_df["side"] == "C", "gex"].sum()),
        put_gex=float(long_df.loc[long_df["side"] == "P", "gex"].sum()),
        call_oi=float(long_df.loc[long_df["side"] == "C", "oi"].sum()),
        put_oi=float(long_df.loc[long_df["side"] == "P", "oi"].sum()),
        expiration_gex=expiration_gex,
        call_walls=call_walls,
        put_walls=put_walls,
        notes=notes,
        rows=len(long_df),
    )


def _find_zero_crossing(strikes: list[float], cum: np.ndarray) -> float | None:
    """Linearly interpolate the strike where cumulative net GEX crosses 0."""
    if len(strikes) < 2 or len(cum) != len(strikes):
        return None
    for i in range(1, len(cum)):
        a, b = cum[i - 1], cum[i]
        if a == 0:
            return float(strikes[i - 1])
        if (a < 0 < b) or (b < 0 < a):
            ka, kb = strikes[i - 1], strikes[i]
            # x where cum = 0:  ka + (0-a)/(b-a) * (kb-ka)
            t = -a / (b - a)
            return float(ka + t * (kb - ka))
    return None


# ---------------------------------------------------------------------------
# Intraday GEX replay
# ---------------------------------------------------------------------------

@dataclass
class IntradayGexResult:
    symbol: str
    day: str                       # "YYYY-MM-DD" (Pacific Time)
    interval: str                  # "5m", "15m", ...
    timestamps: list[str] = field(default_factory=list)   # PT ISO
    spot_series: list[float] = field(default_factory=list)
    open_series: list[float] = field(default_factory=list)
    high_series: list[float] = field(default_factory=list)
    low_series: list[float] = field(default_factory=list)
    close_series: list[float] = field(default_factory=list)
    volume_series: list[float] = field(default_factory=list)
    net_gex_series: list[float] = field(default_factory=list)
    flip_series: list[float | None] = field(default_factory=list)
    strikes: list[float] = field(default_factory=list)
    # heatmap[strike_idx][time_idx] = net GEX in $ at that strike/time
    heatmap: list[list[float]] = field(default_factory=list)
    final_profile: list[float] = field(default_factory=list)   # last bar's net GEX by strike
    final_spot: float = 0.0
    final_flip: float | None = None
    final_total_gex: float = 0.0
    call_walls: list[dict] = field(default_factory=list)
    put_walls: list[dict] = field(default_factory=list)
    expirations: list[str] = field(default_factory=list)
    expiration_dtes: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rows: int = 0


# Maps the UI timeframe to a yfinance interval string.
_INTRADAY_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m"}


def compute_intraday_gex(symbol: str,
                         day: str,
                         interval: str = "5m",
                         max_expirations: int = 8,
                         strike_window_pct: float = 0.20,
                         risk_free: float = DEFAULT_RISK_FREE,
                         strike_bin: float | None = None,
                         dtes: list[int] | None = None,
                         tz: str = "America/Los_Angeles") -> IntradayGexResult:
    """Replay GEX through a single trading day at ``interval`` resolution.

    Approach
    --------
    yfinance only exposes the **current** option chain (today's settlement
    OI). It does not store an intraday history of OI / IV. We therefore
    snapshot the chain *once*, then for each intraday bar of the chosen
    day we re-evaluate Black-Scholes gamma with that bar's close price as
    the new spot. This captures the dominant source of intraday GEX
    variance (spot moving through a fixed gamma curve) while accepting
    that OI / IV themselves are held constant.

    Parameters
    ----------
    symbol:
        Underlying ticker (e.g. ``"SPY"``).
    day:
        Trading day to replay, ``"YYYY-MM-DD"`` (Pacific Time).
    interval:
        yfinance bar interval; one of ``"1m"``, ``"5m"``, ``"15m"``, ``"30m"``.
    Other args mirror :func:`compute_gex`.

    Notes / limits
    --------------
    * yfinance 1-minute data is only available for the last ~7 days; 5m /
      15m / 30m go back ~60 days. Older days return empty.
    * Time to expiry is recomputed at each bar, so the gamma curve breathes
      correctly through the day even for 0DTE chains.
    """

    sym = (symbol or "").strip().upper()
    if not sym:
        return IntradayGexResult(symbol="", day=day, interval=interval,
                                 notes=["No symbol provided."])

    if interval not in _INTRADAY_INTERVALS:
        interval = "5m"

    tk = yf.Ticker(sym)

    # ------------------------------------------------------------------
    # 1) Intraday price tape for the chosen day
    # ------------------------------------------------------------------
    # Request a small buffer around the target day so timezone-edge bars
    # don't get dropped, then filter by PT calendar date.
    try:
        # yfinance accepts start/end as YYYY-MM-DD; request a 2-day window.
        day_dt = pd.Timestamp(day).normalize()
    except Exception:
        return IntradayGexResult(symbol=sym, day=str(day), interval=interval,
                                 notes=[f"Invalid day '{day}'."])

    start = (day_dt - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    end = (day_dt + pd.Timedelta(days=2)).strftime("%Y-%m-%d")

    try:
        bars = yf.download(
            sym, start=start, end=end, interval=interval,
            progress=False, auto_adjust=False, prepost=False,
            threads=False,
        )
    except Exception as exc:
        return IntradayGexResult(symbol=sym, day=day, interval=interval,
                                 notes=[f"price fetch failed: {exc}"])

    if bars is None or bars.empty:
        return IntradayGexResult(
            symbol=sym, day=day, interval=interval,
            notes=[("No intraday bars for that day. "
                    "5m history is limited to the last ~60 days.")])

    if isinstance(bars.columns, pd.MultiIndex):
        bars.columns = bars.columns.get_level_values(0)

    # tz-localize to UTC then convert to user TZ for calendar filtering.
    idx = bars.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    bars = bars.copy()
    bars.index = idx.tz_convert(tz)
    target_date = day_dt.date()
    bars = bars[bars.index.date == target_date]
    bars = bars.dropna(subset=["Close"])
    if bars.empty:
        return IntradayGexResult(
            symbol=sym, day=day, interval=interval,
            notes=[("No bars on that calendar day (market closed / "
                    "outside yfinance history window).")])

    # ------------------------------------------------------------------
    # 2) Snapshot the option chain once
    # ------------------------------------------------------------------
    try:
        all_exps = list(tk.options or [])
    except Exception as exc:
        return IntradayGexResult(symbol=sym, day=day, interval=interval,
                                 notes=[f"options chain unavailable: {exc}"])

    if not all_exps:
        return IntradayGexResult(symbol=sym, day=day, interval=interval,
                                 notes=[f"No options listed for {sym}."])

    exps, _ = _select_expirations(
        all_exps, max_expirations, dtes, target_date)
    if not exps:
        requested = ", ".join(f"{int(v)}DTE" for v in sorted(set(dtes or [])))
        return IntradayGexResult(
            symbol=sym, day=day, interval=interval,
            spot_series=[float(x) for x in bars["Close"]],
            timestamps=[t.isoformat() for t in bars.index],
            notes=[f"No listed expirations match {requested or 'the filter'} "
                   f"for {day}."],
        )
    # Use the chosen day's first bar to size the strike window so the
    # included strikes are anchored to that session, not to "now".
    anchor_spot = float(bars["Close"].iloc[0])
    lo_strike = anchor_spot * (1.0 - strike_window_pct)
    hi_strike = anchor_spot * (1.0 + strike_window_pct)

    notes: list[str] = []
    used_exps: list[str] = []
    used_dtes: list[int] = []
    rows: list[dict] = []
    now_for_T = datetime.utcnow()

    for exp in exps:
        try:
            chain = tk.option_chain(exp)
        except Exception as exc:
            notes.append(f"{exp}: chain fetch failed ({exc})")
            continue

        for side, df in (("C", chain.calls), ("P", chain.puts)):
            if df is None or df.empty:
                continue
            d = df.copy()
            d["openInterest"] = pd.to_numeric(
                d.get("openInterest"), errors="coerce").fillna(0)
            d["impliedVolatility"] = _normalize_iv(d.get("impliedVolatility"))
            d["strike"] = pd.to_numeric(d.get("strike"), errors="coerce")
            d = d.dropna(subset=["strike", "impliedVolatility"])
            d = d[(d["strike"] >= lo_strike) & (d["strike"] <= hi_strike)]
            d = d[d["openInterest"] > 0]
            if d.empty:
                continue

            for k, oi, iv in zip(
                d["strike"].to_numpy(),
                d["openInterest"].to_numpy(),
                d["impliedVolatility"].to_numpy(),
            ):
                rows.append({
                    "expiry": exp,
                    "strike": float(k),
                    "model_strike": float(k),
                    "side": side,
                    "oi": float(oi),
                    "iv": float(iv),
                })
        used_exps.append(exp)
        exp_dte = _expiration_dte(exp, target_date)
        used_dtes.append(int(exp_dte) if exp_dte is not None else -1)

    if not rows:
        return IntradayGexResult(
            symbol=sym, day=day, interval=interval,
            spot_series=[float(x) for x in bars["Close"]],
            timestamps=[t.isoformat() for t in bars.index],
            expirations=used_exps,
            expiration_dtes=used_dtes,
            notes=notes + ["No usable option rows in window."])

    chain_df = pd.DataFrame(rows)
    if strike_bin and strike_bin > 0:
        chain_df["strike"] = (chain_df["strike"] / strike_bin).round() * strike_bin

    # Expiry → time-to-expiry (years), recomputed per bar using bar time
    # so 0DTE behavior is correct.
    exp_to_dt = {}
    for e in used_exps:
        try:
            exp_to_dt[e] = datetime.fromisoformat(e).replace(hour=20)
        except ValueError:
            exp_to_dt[e] = None

    # Convenience numpy arrays of the static chain
    # ``K_model_arr`` remains the native contract strike for Black–Scholes;
    # ``K_arr`` may be a rounded display bucket used only for aggregation.
    K_model_arr = chain_df["model_strike"].to_numpy()
    K_arr = chain_df["strike"].to_numpy()
    OI_arr = chain_df["oi"].to_numpy()
    IV_arr = chain_df["iv"].to_numpy()
    SIGN_arr = np.where(chain_df["side"].to_numpy() == "C", 1.0, -1.0)
    EXP_arr = chain_df["expiry"].to_numpy()

    # Precompute years-to-expiry per bar timestamp × expiry combination
    # (cheap: ~80 bars × ~10 exps).
    exp_years_by_bar: dict[pd.Timestamp, np.ndarray] = {}
    for ts in bars.index:
        ts_utc = ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)
        years = np.zeros(len(EXP_arr), dtype=float)
        for i, e in enumerate(EXP_arr):
            dt = exp_to_dt.get(e)
            if dt is None:
                continue
            secs = (dt - ts_utc).total_seconds()
            years[i] = max(secs, 0.0) / (365.0 * 24 * 3600)
        exp_years_by_bar[ts] = years

    # ------------------------------------------------------------------
    # 3) Replay: for each bar, recompute gamma & GEX at the bar's spot
    # ------------------------------------------------------------------
    unique_strikes = np.sort(np.unique(K_arr))
    strike_to_idx = {float(k): i for i, k in enumerate(unique_strikes)}

    heatmap = np.zeros((len(unique_strikes), len(bars)), dtype=float)
    spot_series = []
    net_gex_series = []
    flip_series: list[float | None] = []
    timestamps_iso = []

    final_profile_arr = np.zeros(len(unique_strikes), dtype=float)

    for j, (ts, row) in enumerate(bars.iterrows()):
        S = float(row["Close"])
        spot_series.append(S)
        timestamps_iso.append(ts.isoformat())

        T_arr = exp_years_by_bar[ts]
        gamma = bs_gamma(S=S, K=K_model_arr, T=T_arr,
                         r=risk_free, sigma=IV_arr)
        gex = (SIGN_arr * gamma * OI_arr * CONTRACT_MULT
               * (S * S) * ONE_PERCENT_MOVE)

        # bucket by strike
        col = np.zeros(len(unique_strikes), dtype=float)
        for i, k in enumerate(K_arr):
            col[strike_to_idx[float(k)]] += gex[i]
        heatmap[:, j] = col
        net_gex_series.append(float(col.sum()))

        scenario_spots_arr, scenario_gex_arr = _scenario_curve(
            K=K_model_arr,
            T=T_arr,
            r=risk_free,
            sigma=IV_arr,
            oi=OI_arr,
            sign=SIGN_arr,
            low=max(float(np.min(unique_strikes)), S * (1.0 - strike_window_pct)),
            high=min(float(np.max(unique_strikes)), S * (1.0 + strike_window_pct)),
            points=81,
        )
        flip_series.append(_find_level_crossing(
            scenario_spots_arr, scenario_gex_arr, reference=S))

        if j == len(bars) - 1:
            final_profile_arr = col

    # Walls based on the final bar (close-of-day snapshot for that session)
    final_spot = spot_series[-1]
    # split final by side again to compute walls (need side-aware view)
    last_T = exp_years_by_bar[bars.index[-1]]
    gamma_last = bs_gamma(S=final_spot, K=K_model_arr, T=last_T,
                          r=risk_free, sigma=IV_arr)
    gex_last = (SIGN_arr * gamma_last * OI_arr * CONTRACT_MULT
                * (final_spot ** 2) * ONE_PERCENT_MOVE)
    side_df = pd.DataFrame({"strike": K_arr,
                             "side": chain_df["side"].to_numpy(),
                             "gex": gex_last})
    side_sums = (side_df.groupby(["strike", "side"])["gex"].sum()
                 .unstack(fill_value=0.0))
    if "C" not in side_sums.columns:
        side_sums["C"] = 0.0
    if "P" not in side_sums.columns:
        side_sums["P"] = 0.0
    call_walls_df = side_sums.sort_values("C", ascending=False).head(5)
    put_walls_df = side_sums.sort_values("P", ascending=True).head(5)
    call_walls = [{"strike": float(k), "gex": float(r["C"])}
                  for k, r in call_walls_df.iterrows() if r["C"] > 0]
    put_walls = [{"strike": float(k), "gex": float(r["P"])}
                 for k, r in put_walls_df.iterrows() if r["P"] < 0]

    return IntradayGexResult(
        symbol=sym,
        day=day,
        interval=interval,
        timestamps=timestamps_iso,
        spot_series=spot_series,
        open_series=[float(v) for v in bars["Open"].to_numpy()],
        high_series=[float(v) for v in bars["High"].to_numpy()],
        low_series=[float(v) for v in bars["Low"].to_numpy()],
        close_series=[float(v) for v in bars["Close"].to_numpy()],
        volume_series=[float(v) for v in bars.get(
            "Volume", pd.Series(0.0, index=bars.index)).fillna(0).to_numpy()],
        net_gex_series=net_gex_series,
        flip_series=flip_series,
        strikes=[float(s) for s in unique_strikes],
        heatmap=[[float(v) for v in row] for row in heatmap],
        final_profile=[float(v) for v in final_profile_arr],
        final_spot=float(final_spot),
        final_flip=flip_series[-1] if flip_series else None,
        final_total_gex=float(np.sum(final_profile_arr)),
        call_walls=call_walls,
        put_walls=put_walls,
        expirations=used_exps,
        expiration_dtes=used_dtes,
        notes=notes,
        rows=len(chain_df),
    )
