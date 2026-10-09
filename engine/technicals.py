import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from db.connection import get_collection
from config import SMA_LONG, SMA_SHORT, SMA_SLOPE_PERIOD


def load_ohlcv(min_rows: int = 50) -> pd.DataFrame:
    """Load all OHLCV data from MongoDB into a DataFrame."""
    col = get_collection("daily_ohlcv")
    cursor = col.find({}, {"_id": 0}).sort([("symbol", 1), ("date", 1)])
    df = pd.DataFrame(list(cursor))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def calculate_all(ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate technicals for every symbol in the OHLCV DataFrame.

    Returns one row per symbol with all computed metrics.
    """
    if ohlcv_df.empty:
        return pd.DataFrame()

    results = []
    for symbol, g in ohlcv_df.groupby("symbol"):
        g = g.sort_values("date")
        n = len(g)
        if n < 50:
            continue

        c = g["close"]
        h = g["high"]
        lo = g["low"]
        v = g["volume"]

        price = float(c.iloc[-1])

        # ADR% (20-day)
        adr = float(((h - lo) / c * 100).tail(20).mean())

        # Average Dollar Volume (20-day)
        avg_dvol = float((c * v).tail(20).mean())

        # Simple Moving Averages
        sma_short = float(c.rolling(SMA_SHORT).mean().iloc[-1]) if n >= SMA_SHORT else None
        sma_long = float(c.rolling(SMA_LONG).mean().iloc[-1]) if n >= SMA_LONG else None

        # SMA-200 slope over last 21 trading days
        if sma_long is not None and n >= SMA_LONG + SMA_SLOPE_PERIOD:
            sma_series = c.rolling(SMA_LONG).mean().dropna()
            sma_slope = float(sma_series.iloc[-1] - sma_series.iloc[-SMA_SLOPE_PERIOD])
        else:
            sma_slope = None

        # Performance lookbacks
        def _perf(days):
            if n >= days + 1:
                return (price / float(c.iloc[-(days + 1)]) - 1) * 100
            return None

        perf_1w = _perf(5)
        perf_1m = _perf(21)
        perf_3m = _perf(63)

        # True Range & ATR for RMV
        prev_close = c.shift(1)
        tr = pd.concat([
            h - lo,
            (h - prev_close).abs(),
            (lo - prev_close).abs(),
        ], axis=1).max(axis=1)

        from config import RMV_SHORT_PERIOD, RMV_LONG_PERIOD
        atr_short = float(tr.tail(RMV_SHORT_PERIOD).mean()) if n >= RMV_SHORT_PERIOD else None
        atr_long = float(tr.tail(RMV_LONG_PERIOD).mean()) if n >= RMV_LONG_PERIOD else None
        rmv = (atr_short / atr_long * 100) if atr_short and atr_long and atr_long > 0 else None

        results.append({
            "symbol": symbol,
            "close": round(price, 2),
            "adr_pct": round(adr, 2),
            "avg_dollar_vol": round(avg_dvol, 0),
            "sma_50": round(sma_short, 2) if sma_short else None,
            "sma_200": round(sma_long, 2) if sma_long else None,
            "sma_200_slope": round(sma_slope, 4) if sma_slope is not None else None,
            "perf_1w": round(perf_1w, 2) if perf_1w is not None else None,
            "perf_1m": round(perf_1m, 2) if perf_1m is not None else None,
            "perf_3m": round(perf_3m, 2) if perf_3m is not None else None,
            "rmv_15": round(rmv, 2) if rmv is not None else None,
        })

    return pd.DataFrame(results)
