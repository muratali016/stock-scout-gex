import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from datetime import datetime, timedelta, timezone
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from pymongo import UpdateOne
from db.connection import get_collection
from ingestion.universe import get_all_symbols
from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    OHLCV_BATCH_SIZE, LOOKBACK_CALENDAR_DAYS,
)


def _get_data_client():
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def _store_bars(bars_response, col) -> int:
    """Convert Alpaca BarSet into MongoDB upsert operations."""
    ops = []
    bar_dict = bars_response if isinstance(bars_response, dict) else bars_response.data

    for symbol, bars in bar_dict.items():
        for bar in bars:
            dt = bar.timestamp
            date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
            ops.append(UpdateOne(
                {"symbol": str(symbol), "date": date_str},
                {"$set": {
                    "symbol": str(symbol),
                    "date": date_str,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": int(bar.volume),
                    "vwap": float(bar.vwap) if bar.vwap else None,
                }},
                upsert=True,
            ))

    if ops:
        col.bulk_write(ops, ordered=False)
    return len(ops)


def backfill_ohlcv(days: int = LOOKBACK_CALENDAR_DAYS) -> int:
    """Pull daily bars for the entire ticker universe and store in MongoDB."""
    symbols = get_all_symbols()
    if not symbols:
        print("  [OHLCV] No tickers in universe. Run universe fetch first.")
        return 0

    client = _get_data_client()
    col = get_collection("daily_ohlcv")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    total_bars = 0
    batches = [symbols[i:i + OHLCV_BATCH_SIZE]
               for i in range(0, len(symbols), OHLCV_BATCH_SIZE)]

    for idx, batch in enumerate(batches, 1):
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
            )
            bars = client.get_stock_bars(request)
            count = _store_bars(bars, col)
            total_bars += count
            print(f"  [OHLCV] Batch {idx}/{len(batches)} "
                  f"({len(batch)} symbols) -> {count:,} bars")
        except Exception as e:
            print(f"  [OHLCV] Batch {idx}/{len(batches)} FAILED: {e}")

        if idx % 10 == 0:
            time.sleep(1)

    return total_bars


def fetch_latest_bars() -> int:
    """Pull only the most recent trading day's bars (for daily updates)."""
    symbols = get_all_symbols()
    if not symbols:
        return 0

    client = _get_data_client()
    col = get_collection("daily_ohlcv")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=5)

    total_bars = 0
    batches = [symbols[i:i + OHLCV_BATCH_SIZE]
               for i in range(0, len(symbols), OHLCV_BATCH_SIZE)]

    for idx, batch in enumerate(batches, 1):
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
            )
            bars = client.get_stock_bars(request)
            count = _store_bars(bars, col)
            total_bars += count
        except Exception as e:
            print(f"  [OHLCV] Latest batch {idx} FAILED: {e}")

        if idx % 10 == 0:
            time.sleep(1)

    return total_bars
