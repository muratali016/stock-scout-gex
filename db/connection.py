import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from config import MONGO_URI, MONGO_DB_NAME

_client: MongoClient | None = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _db = _client[MONGO_DB_NAME]
    return _db


def get_collection(name: str):
    return get_db()[name]


def ping() -> bool:
    try:
        get_db().command("ping")
        return True
    except Exception:
        return False
