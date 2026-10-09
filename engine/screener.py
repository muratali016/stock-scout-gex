import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime, timezone
from pymongo import UpdateOne
from db.connection import get_collection
from engine.technicals import load_ohlcv, calculate_all
from engine.strength import rank_absolute_strength
from engine.rmv import flag_contraction
from config import (
    MIN_AVG_DOLLAR_VOLUME, MIN_MARKET_CAP,
    MIN_ANNUAL_REVENUE, MIN_QUARTERLY_REVENUE,
    MIN_ADR_PCT, PERF_PERCENTILE_THRESHOLD,
)


def _load_fundamentals() -> pd.DataFrame:
    col = get_collection("fundamentals")
    docs = list(col.find({}, {"_id": 0}))
    if not docs:
        return pd.DataFrame()
    return pd.DataFrame(docs)


def _store_results(df: pd.DataFrame, date_str: str):
    col = get_collection("calculated_metrics")
    ops = []
    for _, row in df.iterrows():
        doc = row.dropna().to_dict()
        doc["date"] = date_str
        ops.append(UpdateOne(
            {"symbol": row["symbol"], "date": date_str},
            {"$set": doc},
            upsert=True,
        ))
    if ops:
        col.bulk_write(ops, ordered=False)


def run_screen() -> pd.DataFrame:
    """Execute the full 3-tier screening pipeline.

    Returns a DataFrame of stocks that passed all filters.
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Load & compute technicals ---
    print("  [Screen] Loading OHLCV data...")
    ohlcv = load_ohlcv()
    if ohlcv.empty:
        print("  [Screen] No OHLCV data found.")
        return pd.DataFrame()

    print(f"  [Screen] Computing technicals for {ohlcv['symbol'].nunique():,} symbols...")
    tech = calculate_all(ohlcv)
    if tech.empty:
        return pd.DataFrame()

    # --- Merge fundamentals ---
    fund = _load_fundamentals()
    if not fund.empty:
        merge_cols = ["symbol", "name", "sector", "industry",
                      "market_cap", "revenue_annual", "revenue_quarterly"]
        available = [c for c in merge_cols if c in fund.columns]
        tech = tech.merge(fund[available], on="symbol", how="left")
    else:
        for c in ("name", "sector", "industry",
                  "market_cap", "revenue_annual", "revenue_quarterly"):
            tech[c] = None

    # =====================================================================
    # TIER 1 — Liquidity & Fundamentals
    # =====================================================================
    t1 = tech[
        (tech["avg_dollar_vol"] >= MIN_AVG_DOLLAR_VOLUME)
        & (tech["adr_pct"] >= MIN_ADR_PCT)
    ].copy()

    if "market_cap" in t1.columns:
        has_mc = t1["market_cap"].notna()
        t1 = t1[~has_mc | (t1["market_cap"] >= MIN_MARKET_CAP)]

    if "revenue_annual" in t1.columns and "revenue_quarterly" in t1.columns:
        has_rev = t1["revenue_annual"].notna() | t1["revenue_quarterly"].notna()
        rev_ok = (
            (t1["revenue_annual"].fillna(0) >= MIN_ANNUAL_REVENUE)
            | (t1["revenue_quarterly"].fillna(0) >= MIN_QUARTERLY_REVENUE)
        )
        t1 = t1[~has_rev | rev_ok]

    print(f"  [Screen] Tier 1 pass: {len(t1):,} / {len(tech):,}")

    # =====================================================================
    # TIER 2 — Trend & Momentum
    # =====================================================================
    t2 = t1.dropna(subset=["sma_200", "sma_200_slope", "perf_1w", "perf_1m", "perf_3m"])
    t2 = t2[
        (t2["close"] > t2["sma_200"])
        & (t2["sma_200_slope"] > 0)
    ].copy()

    for col in ("perf_1w", "perf_1m", "perf_3m"):
        if len(t2) > 5:
            cutoff = t2[col].quantile(PERF_PERCENTILE_THRESHOLD / 100)
            t2 = t2[t2[col] >= cutoff]

    print(f"  [Screen] Tier 2 pass: {len(t2):,}")

    # =====================================================================
    # TIER 3 — Proprietary Scoring
    # =====================================================================
    t3 = rank_absolute_strength(t2)
    t3 = flag_contraction(t3)
    t3["passes_screen"] = True
    print(f"  [Screen] Tier 3 final: {len(t3):,} stocks")

    # --- Store results ---
    if not t3.empty:
        _store_results(t3, date_str)

    fail = tech[~tech["symbol"].isin(t3["symbol"])].copy()
    fail["passes_screen"] = False
    fail["abs_strength"] = None
    fail["vol_contraction"] = False
    if not fail.empty:
        _store_results(fail, date_str)

    return t3
