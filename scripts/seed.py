#!/usr/bin/env python
"""One-time seed: populate ticker universe, backfill OHLCV, fetch
fundamentals, and run the initial screening pipeline."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import ping
from db.indexes import ensure_indexes
from ingestion.universe import fetch_universe
from ingestion.ohlcv import backfill_ohlcv
from ingestion.fundamentals import fetch_fundamentals
from engine.screener import run_screen


def main():
    banner = "=" * 60
    print(banner)
    print("  STOCK SCOUT  —  Initial Seed")
    print(banner)

    # -- Pre-flight: MongoDB reachable? --
    print("\n[0/5] Checking MongoDB connection...")
    if not ping():
        print("  ERROR: Cannot reach MongoDB. Make sure it is running.")
        print("  Expected URI from .env / config: see MONGO_URI")
        sys.exit(1)
    print("  OK")

    # -- Step 1: indexes --
    print("\n[1/5] Ensuring database indexes...")
    ensure_indexes()

    # -- Step 2: universe --
    print("\n[2/5] Fetching ticker universe from Alpaca...")
    count = fetch_universe()
    print(f"  -> {count:,} active US equities loaded.")

    # -- Step 3: OHLCV backfill --
    print("\n[3/5] Backfilling daily OHLCV (this may take a while)...")
    bars = backfill_ohlcv()
    print(f"  -> {bars:,} total bar records stored.")

    # -- Step 4: fundamentals --
    print("\n[4/5] Fetching fundamental data for pre-filtered symbols...")
    fund = fetch_fundamentals()
    print(f"  -> {fund:,} symbols with fundamental data.")

    # -- Step 5: screen --
    print("\n[5/5] Running initial screening pipeline...")
    results = run_screen()
    print(f"  -> {len(results):,} stocks pass all 3 tiers.")

    print(f"\n{banner}")
    print("  Seed complete!")
    print(banner)


if __name__ == "__main__":
    main()
