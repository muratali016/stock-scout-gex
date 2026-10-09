import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SECTOR_ETFS, CACHE_TTL_MINUTES, MONGO_COLLECTION_NAME

# =========================================================================
# Sector ETF data (yfinance — works without MongoDB)
# =========================================================================

_summary_cache: pd.DataFrame | None = None
_ohlcv_cache: dict[str, pd.DataFrame] = {}
_last_fetch: datetime | None = None


def fetch_etf_data(force: bool = False) -> tuple[pd.DataFrame, dict]:
    global _summary_cache, _ohlcv_cache, _last_fetch

    if not force and _summary_cache is not None and _last_fetch:
        elapsed = (datetime.now() - _last_fetch).total_seconds() / 60
        if elapsed < CACHE_TTL_MINUTES:
            return _summary_cache, _ohlcv_cache

    tickers = list(SECTOR_ETFS.keys())
    end = datetime.now()
    start = end - timedelta(days=500)

    rows = []
    ohlcv: dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        try:
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty or len(df) < 50:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])
            ohlcv[ticker] = df

            c = df["Close"].astype(float)
            h = df["High"].astype(float)
            l = df["Low"].astype(float)
            v = df["Volume"].astype(float)

            price = float(c.iloc[-1])
            prev = float(c.iloc[-2]) if len(c) > 1 else price
            chg = (price / prev - 1) * 100

            def _perf(n: int) -> float:
                return (price / float(c.iloc[-(n + 1)]) - 1) * 100 if len(c) >= n + 1 else 0.0

            adr = float(((h - l) / c * 100).tail(20).mean())
            dvol = float((c * v).tail(20).mean() / 1e6)
            sma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
            sma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else None
            above_sma = price > sma200 if sma200 is not None else None

            if sma200 is not None and len(c) >= 221:
                sma200_series = c.rolling(200).mean().dropna()
                sma_slope = float(sma200_series.iloc[-1] - sma200_series.iloc[-21])
            else:
                sma_slope = None

            info = SECTOR_ETFS[ticker]
            rows.append({
                "ticker": ticker,
                "sector": info["sector"],
                "industries": info["industries"],
                "price": round(price, 2),
                "chg": round(chg, 2),
                "perf_1d": round(_perf(1), 2),
                "perf_1w": round(_perf(5), 2),
                "perf_1m": round(_perf(21), 2),
                "perf_3m": round(_perf(63), 2),
                "adr": round(adr, 2),
                "vol": round(dvol, 1),
                "sma50": round(sma50, 2) if sma50 else None,
                "sma200": round(sma200, 2) if sma200 else None,
                "sma_slope": round(sma_slope, 4) if sma_slope is not None else None,
                "trend": "\u2713" if above_sma else ("\u2717" if above_sma is not None else "\u2014"),
            })
        except Exception as e:
            print(f"[WARN] {ticker}: {e}")

    _summary_cache = pd.DataFrame(rows)
    _ohlcv_cache = ohlcv
    _last_fetch = datetime.now()
    return _summary_cache, _ohlcv_cache


def get_chart_data(ticker: str, days: int = 180) -> pd.DataFrame | None:
    if ticker not in _ohlcv_cache:
        return None
    df = _ohlcv_cache[ticker].copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    return df.tail(days)


def get_last_fetch_time() -> str:
    if _last_fetch is None:
        return "Never"
    return _last_fetch.strftime("%Y-%m-%d %H:%M:%S")


# =========================================================================
# ETF Holdings (yfinance) — all holdings as raw data
# =========================================================================

_holdings_cache: dict[str, list[dict]] = {}
_holdings_ts: dict[str, datetime] = {}


def fetch_etf_holdings(ticker: str) -> list[dict]:
    """Return all holdings for an ETF as a list of dicts with
    keys: symbol, name, weight (float percentage)."""

    now = datetime.now()
    if ticker in _holdings_cache and ticker in _holdings_ts:
        if (now - _holdings_ts[ticker]).total_seconds() / 60 < CACHE_TTL_MINUTES:
            return _holdings_cache[ticker]

    try:
        etf = yf.Ticker(ticker)

        try:
            top = etf.funds_data.top_holdings
        except Exception:
            top = None

        if top is None or top.empty:
            _holdings_cache[ticker] = []
            _holdings_ts[ticker] = now
            return []

        top = top.reset_index()
        cols = top.columns.tolist()
        sym_col = cols[0]
        name_col = cols[1] if len(cols) > 1 else None
        pct_col = cols[2] if len(cols) > 2 else (cols[1] if len(cols) > 1 else None)

        result = []
        for _, r in top.iterrows():
            symbol = str(r[sym_col]).strip()
            if not symbol:
                continue
            name = str(r[name_col]) if name_col and name_col != pct_col else symbol
            weight_raw = r[pct_col] if pct_col else None
            if weight_raw is not None:
                weight = float(weight_raw) * 100 if float(weight_raw) < 1 else float(weight_raw)
            else:
                weight = 0.0
            result.append({"symbol": symbol, "name": name, "weight": round(weight, 2)})

        _holdings_cache[ticker] = result
        _holdings_ts[ticker] = now
        return result

    except Exception as e:
        print(f"[Holdings] {ticker}: {e}")
        return []

def fetch_etf_holdings_metrics(ticker: str, top_n: int = 10) -> list[dict]:
    """Return top ETF holdings with quick return metrics for UI display."""
    holdings = fetch_etf_holdings(ticker)
    if not holdings:
        return []

    top = sorted(holdings, key=lambda h: h.get("weight", 0), reverse=True)[:top_n]
    symbols = [h["symbol"] for h in top if h.get("symbol")]
    if not symbols:
        return []

    perf_map: dict[str, dict] = {}
    try:
        px = yf.download(symbols, period="3mo", progress=False, auto_adjust=True)
        closes = px.get("Close")
        if closes is None:
            closes = px
        if isinstance(closes, pd.Series):
            closes = closes.to_frame(name=symbols[0])
    except Exception:
        closes = None

    for sym in symbols:
        perf = {"perf_1d": None, "perf_1w": None, "perf_1m": None}
        if closes is not None and sym in closes.columns:
            s = closes[sym].dropna().astype(float)
            if len(s) >= 2:
                perf["perf_1d"] = round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2)
            if len(s) >= 6:
                perf["perf_1w"] = round((s.iloc[-1] / s.iloc[-6] - 1) * 100, 2)
            if len(s) >= 22:
                perf["perf_1m"] = round((s.iloc[-1] / s.iloc[-22] - 1) * 100, 2)
        perf_map[sym] = perf

    rows = []
    for h in top:
        sym = h["symbol"]
        perf = perf_map.get(sym, {})
        rows.append({
            "symbol": sym,
            "name": h.get("name", sym),
            "weight": h.get("weight", 0.0),
            "perf_1d": perf.get("perf_1d"),
            "perf_1w": perf.get("perf_1w"),
            "perf_1m": perf.get("perf_1m"),
        })
    return rows


# =========================================================================
# Manual watchlist — fetch & screen user-entered tickers via yfinance
# =========================================================================

_watchlist_cache: dict[str, dict] = {}


def fetch_watchlist_stocks(symbols: list[str]) -> pd.DataFrame:
    """Fetch OHLCV + fundamentals for a list of user-entered tickers and
    compute all screening metrics on the fly."""
    global _watchlist_cache

    if not symbols:
        return pd.DataFrame()

    end = datetime.now()
    start = end - timedelta(days=500)
    rows = []

    for sym in symbols:
        sym = sym.strip().upper()
        if not sym:
            continue

        try:
            df = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty or len(df) < 20:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])

            c = df["Close"].astype(float)
            h = df["High"].astype(float)
            lo = df["Low"].astype(float)
            v = df["Volume"].astype(float)

            price = float(c.iloc[-1])
            prev = float(c.iloc[-2]) if len(c) > 1 else price
            chg = (price / prev - 1) * 100

            def _perf(n):
                return (price / float(c.iloc[-(n + 1)]) - 1) * 100 if len(c) >= n + 1 else None

            adr = float(((h - lo) / c * 100).tail(20).mean())
            dvol = float((c * v).tail(20).mean())

            sma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
            sma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else None
            above_sma = price > sma200 if sma200 is not None else None

            if sma200 is not None and len(c) >= 221:
                sma_series = c.rolling(200).mean().dropna()
                sma_slope = float(sma_series.iloc[-1] - sma_series.iloc[-21])
            else:
                sma_slope = None

            # RMV-15
            prev_close = c.shift(1)
            tr = pd.concat([h - lo, (h - prev_close).abs(), (lo - prev_close).abs()], axis=1).max(axis=1)
            atr_15 = float(tr.tail(15).mean()) if len(tr) >= 15 else None
            atr_50 = float(tr.tail(50).mean()) if len(tr) >= 50 else None
            rmv = (atr_15 / atr_50 * 100) if atr_15 and atr_50 and atr_50 > 0 else None

            # Fundamentals from yfinance .info
            try:
                info = yf.Ticker(sym).info
                name = info.get("shortName") or info.get("longName") or sym
                sector = info.get("sector") or ""
                industry = info.get("industry") or ""
                mkt_cap = info.get("marketCap")
            except Exception:
                name, sector, industry, mkt_cap = sym, "", "", None

            row = {
                "symbol": sym,
                "name": name,
                "sector": sector,
                "industry": industry,
                "close": round(price, 2),
                "chg": round(chg, 2),
                "perf_1d": round(_perf(1), 2) if _perf(1) is not None else None,
                "perf_1w": round(_perf(5), 2) if _perf(5) is not None else None,
                "perf_1m": round(_perf(21), 2) if _perf(21) is not None else None,
                "perf_3m": round(_perf(63), 2) if _perf(63) is not None else None,
                "adr_pct": round(adr, 2),
                "avg_dollar_vol": round(dvol, 0),
                "rmv_15": round(rmv, 1) if rmv else None,
                "sma_200": round(sma200, 2) if sma200 else None,
                "sma_200_slope": round(sma_slope, 4) if sma_slope is not None else None,
                "above_sma": above_sma,
                "market_cap": mkt_cap,
                "vol_contraction": rmv is not None and rmv < 75,
            }
            rows.append(row)
            _watchlist_cache[sym] = row

        except Exception as e:
            print(f"[Watchlist] {sym}: {e}")

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)

    # Cross-sectional Abs Strength ranking within the watchlist
    if len(result) > 1 and "perf_1m" in result.columns:
        valid = result["perf_1m"].notna()
        result.loc[valid, "abs_strength"] = (
            result.loc[valid, "perf_1m"]
            .rank(pct=True).multiply(98).add(1).round(0).astype(int)
        )
    elif len(result) == 1:
        result["abs_strength"] = 50
    else:
        result["abs_strength"] = None

    result["passes_screen"] = True
    return result


# =========================================================================
# Screened stocks — MongoDB persistence
# =========================================================================

_mongo_ok: bool | None = None


def _get_mongo_col():
    """Return the MongoDB collection, or None if unreachable."""
    global _mongo_ok
    try:
        from db.connection import get_collection, ping
        if _mongo_ok is None:
            _mongo_ok = ping()
        if not _mongo_ok:
            return None
        return get_collection(MONGO_COLLECTION_NAME)
    except Exception:
        _mongo_ok = False
        return None


def load_saved_tickers() -> list[str]:
    """Load all saved ticker symbols from MongoDB."""
    col = _get_mongo_col()
    if col is None:
        return []
    try:
        docs = col.find({}, {"_id": 0, "symbol": 1})
        return [d["symbol"] for d in docs if "symbol" in d]
    except Exception:
        return []


def save_screened_stocks(df: pd.DataFrame):
    """Upsert screened stock records into MongoDB (keyed by symbol)."""
    col = _get_mongo_col()
    if col is None or df.empty:
        return
    try:
        from pymongo import UpdateOne
        ops = []
        for _, row in df.iterrows():
            doc = row.dropna().to_dict()
            sym = doc.get("symbol")
            if not sym:
                continue
            doc["updated_at"] = datetime.utcnow()
            ops.append(UpdateOne({"symbol": sym}, {"$set": doc}, upsert=True))
        if ops:
            col.bulk_write(ops, ordered=False)
    except Exception as e:
        print(f"[MongoDB] save error: {e}")


def remove_all_screened():
    """Delete all documents from the screened stocks collection."""
    col = _get_mongo_col()
    if col is None:
        return
    try:
        col.delete_many({})
    except Exception as e:
        print(f"[MongoDB] clear error: {e}")


def remove_tickers(symbols: list[str]):
    """Remove specific tickers from MongoDB."""
    col = _get_mongo_col()
    if col is None or not symbols:
        return
    try:
        col.delete_many({"symbol": {"$in": symbols}})
    except Exception as e:
        print(f"[MongoDB] remove error: {e}")


def load_screened_stocks(force: bool = False) -> pd.DataFrame:
    """Load the latest screened-stock results from MongoDB."""
    col = _get_mongo_col()
    if col is None:
        return pd.DataFrame()
    try:
        docs = list(col.find({}, {"_id": 0}))
        if not docs:
            return pd.DataFrame()
        return pd.DataFrame(docs)
    except Exception:
        return pd.DataFrame()


# =========================================================================
# User settings — indicator presets (MongoDB)
# =========================================================================

def _get_settings_col():
    """Return a 'user_settings' collection, or None."""
    global _mongo_ok
    try:
        from db.connection import get_db, ping
        if _mongo_ok is None:
            _mongo_ok = ping()
        if not _mongo_ok:
            return None
        return get_db()["user_settings"]
    except Exception:
        _mongo_ok = False
        return None


def load_indicator_prefs() -> list[dict]:
    """Load saved TradingView indicator configs from MongoDB.

    Each item is a dict like:
        {"key": "EMA_9", "study_id": "MAExp@tv-basicstudies",
         "label": "EMA 9", "inputs": {"length": 9}}
    """
    col = _get_settings_col()
    if col is None:
        return []
    try:
        doc = col.find_one({"_id": "tv_indicators"})
        if not doc:
            return []
        raw = doc.get("studies", [])
        if raw and isinstance(raw[0], str):
            return []
        return raw
    except Exception:
        return []


def save_indicator_prefs(studies: list[dict]):
    """Persist TradingView indicator configs to MongoDB."""
    col = _get_settings_col()
    if col is None:
        return
    try:
        col.update_one(
            {"_id": "tv_indicators"},
            {"$set": {"studies": studies, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
    except Exception as e:
        print(f"[MongoDB] indicator save error: {e}")
