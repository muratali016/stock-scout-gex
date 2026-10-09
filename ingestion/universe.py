import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus
from pymongo import UpdateOne
from db.connection import get_collection
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY


def fetch_universe() -> int:
    """Fetch all active, tradable US equities from Alpaca and upsert into MongoDB."""
    client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
    request = GetAssetsRequest(
        asset_class=AssetClass.US_EQUITY,
        status=AssetStatus.ACTIVE,
    )
    assets = client.get_all_assets(request)

    col = get_collection("tickers")
    ops = []
    now = datetime.now(timezone.utc)

    for asset in assets:
        if not asset.tradable:
            continue
        ops.append(UpdateOne(
            {"symbol": asset.symbol},
            {"$set": {
                "symbol": asset.symbol,
                "name": asset.name or "",
                "exchange": str(asset.exchange) if asset.exchange else None,
                "asset_class": str(asset.asset_class),
                "status": str(asset.status),
                "updated_at": now,
            }},
            upsert=True,
        ))

    if ops:
        result = col.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    return 0


def get_all_symbols() -> list[str]:
    """Return all symbols stored in the tickers collection."""
    col = get_collection("tickers")
    return [doc["symbol"] for doc in col.find({}, {"symbol": 1, "_id": 0})]
