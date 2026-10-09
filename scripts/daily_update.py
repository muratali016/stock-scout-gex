#!/usr/bin/env python
"""Nightly update: pull latest bars, refresh stale fundamentals, re-screen."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import ping
from ingestion.universe import fetch_universe
from ingestion.ohlcv import fetch_latest_bars
from ingestion.fundamentals import fetch_fundamentals
from engine.screener import run_screen


def main():
    print("=" * 60)
    print("  STOCK SCOUT  —  Daily Update")
    print("=" * 60)

    if not ping():
        print("ERROR: Cannot reach MongoDB.")
        sys.exit(1)

    # Step 1: refresh universe (catches new IPOs / delistings)
    print("\n[1/4] Refreshing ticker universe...")
    count = fetch_universe()
    print(f"  -> {count:,} tickers updated.")

    # Step 2: latest OHLCV
    print("\n[2/4] Fetching latest daily bars...")
    bars = fetch_latest_bars()
    print(f"  -> {bars:,} new bar records.")

    # Step 3: fundamentals (only stale ones)
    print("\n[3/4] Refreshing stale fundamentals...")
    fund = fetch_fundamentals()
    print(f"  -> {fund:,} symbols refreshed.")

    # Step 4: full screen
    print("\n[4/4] Running screening pipeline...")
    results = run_screen()
    print(f"  -> {len(results):,} stocks pass all filters.")

    print("\n" + "=" * 60)
    print("  Daily update complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
