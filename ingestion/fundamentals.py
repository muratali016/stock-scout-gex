import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, timezone
from pymongo import UpdateOne
from db.connection import get_collection
from config import (
    MIN_AVG_DOLLAR_VOLUME, MIN_ADR_PCT, FUNDAMENTAL_STALE_DAYS,
)


def _prefilter_symbols() -> list[str]:
    """Return symbols that pass the OHLCV-only volume/ADR pre-filter.
    This avoids fetching fundamentals for thousands of illiquid tickers."""
    col = get_collection("daily_ohlcv")
    pipeline = [
        {"$sort": {"date": -1}},
        {"$group": {
            "_id": "$symbol",
            "docs": {"$push": {
                "close": "$close", "high": "$high",
                "low": "$low", "volume": "$volume",
            }},
        }},
        {"$project": {
            "symbol": "$_id",
            "recent": {"$slice": ["$docs", 20]},
        }},
    ]
    results = list(col.aggregate(pipeline, allowDiskUse=True))

    passing = []
    for r in results:
        recent = r.get("recent", [])
        if len(recent) < 10:
            continue
        dollar_vols, adrs = [], []
        for d in recent:
            c, h, l, v = d["close"], d["high"], d["low"], d["volume"]
            if c and c > 0:
                dollar_vols.append(c * v)
                adrs.append((h - l) / c * 100)
        avg_dvol = sum(dollar_vols) / len(dollar_vols) if dollar_vols else 0
        avg_adr = sum(adrs) / len(adrs) if adrs else 0
        if avg_dvol >= MIN_AVG_DOLLAR_VOLUME and avg_adr >= MIN_ADR_PCT:
            passing.append(r["symbol"])

    return passing


def fetch_fundamentals(symbols: list[str] | None = None, force: bool = False) -> int:
    """Fetch market cap & revenue from yfinance for pre-filtered symbols."""
    if symbols is None:
        symbols = _prefilter_symbols()

    if not symbols:
        print("  [Fundamentals] No symbols passed pre-filter.")
        return 0

    col = get_collection("fundamentals")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=FUNDAMENTAL_STALE_DAYS)

    if not force:
        fresh = set()
        for doc in col.find(
            {"symbol": {"$in": symbols}, "updated_at": {"$gte": cutoff}},
            {"symbol": 1, "_id": 0},
        ):
            fresh.add(doc["symbol"])
        symbols = [s for s in symbols if s not in fresh]
        if not symbols:
            print("  [Fundamentals] All symbols are fresh. Skipping.")
            return 0

    print(f"  [Fundamentals] Fetching data for {len(symbols):,} symbols...")
    ops = []
    errors = 0

    for i, symbol in enumerate(symbols, 1):
        try:
            info = yf.Ticker(symbol).info
            market_cap = info.get("marketCap") or info.get("totalAssets")
            rev_annual = info.get("totalRevenue") or info.get("revenue")
            rev_quarterly = info.get("revenuePerShare")  # fallback estimate
            if rev_quarterly and info.get("sharesOutstanding"):
                rev_quarterly = rev_quarterly * info["sharesOutstanding"] / 4
            else:
                rev_quarterly = None

            ops.append(UpdateOne(
                {"symbol": symbol},
                {"$set": {
                    "symbol": symbol,
                    "name": info.get("shortName") or info.get("longName") or "",
                    "sector": info.get("sector") or "",
                    "industry": info.get("industry") or "",
                    "market_cap": market_cap,
                    "revenue_annual": rev_annual,
                    "revenue_quarterly": rev_quarterly,
                    "updated_at": now,
                }},
                upsert=True,
            ))
        except Exception:
            errors += 1

        if i % 50 == 0:
            print(f"    Progress: {i}/{len(symbols)}"
                  f" ({i * 100 // len(symbols)}%)"
                  f" [{errors} errors]")
            if ops:
                col.bulk_write(ops, ordered=False)
                ops = []

    if ops:
        col.bulk_write(ops, ordered=False)

    return len(symbols) - errors
