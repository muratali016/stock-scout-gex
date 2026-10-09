import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

ALPACA_PAPER_API_KEY = os.getenv("ALPACA_PAPER_API_KEY", "")
ALPACA_PAPER_SECRET_KEY = os.getenv("ALPACA_PAPER_SECRET_KEY", "")
ALPACA_LIVE_API_KEY = os.getenv("ALPACA_LIVE_API_KEY", "")
ALPACA_LIVE_SECRET_KEY = os.getenv("ALPACA_LIVE_SECRET_KEY", "")
# Compatibility aliases used by the optional ingestion scripts.
ALPACA_API_KEY = ALPACA_PAPER_API_KEY or ALPACA_LIVE_API_KEY
ALPACA_SECRET_KEY = ALPACA_PAPER_SECRET_KEY or ALPACA_LIVE_SECRET_KEY
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "my_stocks")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "my_stocks_screen")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "")

ALERT_SENDER_EMAIL = os.getenv("ALERT_SENDER_EMAIL", "")
ALERT_SENDER_PASSWORD = os.getenv("ALERT_SENDER_PASSWORD", "")
ALERT_SMTP_SERVER = os.getenv("ALERT_SMTP_SERVER", "smtp.gmail.com")
ALERT_SMTP_PORT = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_RECIPIENTS = [
    e.strip() for e in os.getenv("ALERT_RECIPIENTS", "").split(",") if e.strip()
]

SECTOR_ETFS = {
    "XLK":  {"sector": "Technology",              "industries": "Software, Semiconductors, Hardware, IT Services"},
    "XLF":  {"sector": "Financials",              "industries": "Banks, Insurance, Capital Markets, Consumer Finance"},
    "XLV":  {"sector": "Healthcare",              "industries": "Pharmaceuticals, Biotech, Healthcare Equipment"},
    "XLY":  {"sector": "Consumer Discretionary",  "industries": "Retail, Automobiles, Hotels, Luxury Goods"},
    "XLP":  {"sector": "Consumer Staples",        "industries": "Food & Beverage, Household Products, Tobacco"},
    "XLI":  {"sector": "Industrials",             "industries": "Aerospace & Defense, Machinery, Transportation"},
    "XLE":  {"sector": "Energy",                  "industries": "Oil & Gas Exploration, Production, Equipment"},
    "XLC":  {"sector": "Communication Services",  "industries": "Interactive Media, Entertainment, Telecom"},
    "XLB":  {"sector": "Materials",               "industries": "Chemicals, Mining, Metals, Forest Products"},
    "XLU":  {"sector": "Utilities",               "industries": "Electric, Gas, Water Utilities"},
    "XLRE": {"sector": "Real Estate",             "industries": "Equity REITs, Real Estate Management & Development"},
    "ITA":  {"sector": "Industrials",             "industries": "Aerospace & Defense"},
    "IYJ":  {"sector": "Industrials",             "industries": "U.S. Industrials"},
    "EXI":  {"sector": "Industrials",             "industries": "Global Industrials"},
    "IYT":  {"sector": "Industrials",             "industries": "Transportation"},
    "IYW":  {"sector": "Technology",              "industries": "U.S. Technology"},
    "IGM":  {"sector": "Technology",              "industries": "Expanded Tech Sector"},
    "IXN":  {"sector": "Technology",              "industries": "Global Technology"},
    "IYH":  {"sector": "Healthcare",              "industries": "U.S. Healthcare"},
    "IBB":  {"sector": "Healthcare",              "industries": "Biotechnology"},
    "IYE":  {"sector": "Energy",                  "industries": "U.S. Energy"},
    "IYM":  {"sector": "Materials",               "industries": "U.S. Basic Materials"},
    "IYC":  {"sector": "Consumer Discretionary",  "industries": "U.S. Consumer Discretionary"},
    "IYK":  {"sector": "Consumer Staples",        "industries": "U.S. Consumer Staples"},
    "IYF":  {"sector": "Financials",              "industries": "U.S. Financials"},
    "IGF":  {"sector": "Industrials",             "industries": "Global Infrastructure"},
}

CACHE_TTL_MINUTES = 15

# ---------------------------------------------------------------------------
# Volume Scanner — default watchlists
# ---------------------------------------------------------------------------
# "Magnificent 7" mega-cap technology names used as the default universe
# for the Abnormal Volume Scanner tab.
MAG7_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]

# Volume scanner thresholds
VOL_REL_ABNORMAL = 1.50      # >= 150% of typical-by-this-time → abnormal
VOL_REL_EXTREME  = 2.50      # >= 250% → extreme
VOL_BUY_PRESSURE = 0.60      # buy share >= 60% of executed → buying skew
VOL_SELL_PRESSURE = 0.40     # buy share <= 40% → selling skew
VOL_INTRADAY_LOOKBACK_DAYS = 5   # session profile baseline (intraday)
VOL_DAILY_LOOKBACK_DAYS = 20     # daily-average volume baseline

# Intraday 5-minute spike detector
VOL_SPIKE_TIMEFRAME = "5m"
VOL_SPIKE_LOOKBACK_BARS = 20     # rolling baseline length (~100 min)
VOL_SPIKE_Z_THRESHOLD = 2.0      # default z-score to flag
VOL_SPIKE_REL_THRESHOLD = 1.8    # default rel-vol to flag (vs rolling mean)
VOL_SPIKE_MAX_RESULTS = 80       # cap rows in the spike feed
VOL_SPIKE_DELTA_THRESHOLD = 0.65 # buy share that flips to ↑ BUY / ↓ SELL tag

# ---------------------------------------------------------------------------
# Screener thresholds
# ---------------------------------------------------------------------------
MIN_AVG_DOLLAR_VOLUME = 20_000_000   # $20M trailing-20-day average
MIN_MARKET_CAP = 1_000_000_000       # $1B
MIN_ANNUAL_REVENUE = 100_000_000     # $100M
MIN_QUARTERLY_REVENUE = 25_000_000   # $25M
MIN_ADR_PCT = 2.0                    # 2%

SMA_LONG = 200
SMA_SHORT = 50
SMA_SLOPE_PERIOD = 21                # trading days (~1 month)
RMV_SHORT_PERIOD = 15
RMV_LONG_PERIOD = 50
PERF_PERCENTILE_THRESHOLD = 67       # top 33rd percentile

LOOKBACK_CALENDAR_DAYS = 500         # ~2 years of trading days for backfill
OHLCV_BATCH_SIZE = 100               # symbols per Alpaca bars request
FUNDAMENTAL_STALE_DAYS = 7           # refresh fundamentals older than this
