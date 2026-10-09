from pymongo import ASCENDING
from db.connection import get_db


def ensure_indexes():
    db = get_db()

    db.tickers.create_index("symbol", unique=True)

    db.daily_ohlcv.create_index(
        [("symbol", ASCENDING), ("date", ASCENDING)], unique=True
    )

    db.fundamentals.create_index("symbol", unique=True)

    db.calculated_metrics.create_index(
        [("symbol", ASCENDING), ("date", ASCENDING)], unique=True
    )
    db.calculated_metrics.create_index(
        [("date", ASCENDING), ("passes_screen", ASCENDING)]
    )

    print("[DB] Indexes ensured.")
