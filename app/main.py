import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dash
import dash_bootstrap_components as dbc
from app.layout import build_layout
from app.callbacks import register_callbacks
from app.data import fetch_etf_data

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")

print("[Stock Scout] Fetching sector ETF data ...")
fetch_etf_data()
print("[Stock Scout] Data loaded.")

saved_tickers: list[str] = []
saved_indicators: list[str] = []
try:
    from db.connection import ping
    if ping():
        print("[Stock Scout] MongoDB connected.")
        from app.data import load_saved_tickers, load_indicator_prefs
        saved_tickers = load_saved_tickers()
        saved_indicators = load_indicator_prefs()
        if saved_tickers:
            print(f"[Stock Scout] Loaded {len(saved_tickers)} saved tickers from MongoDB.")
        if saved_indicators:
            print(f"[Stock Scout] Loaded {len(saved_indicators)} saved indicators from MongoDB.")
    else:
        print("[Stock Scout] MongoDB not reachable — Screened Stocks will use local storage only.")
except Exception:
    print("[Stock Scout] MongoDB not available — Screened Stocks will use local storage only.")

print("[Stock Scout] Starting dashboard ...")

app = dash.Dash(
    __name__,
    assets_folder=ASSETS_DIR,
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap",
    ],
    title="Stock Scout  |  Quantitative Screener",
    update_title="Refreshing...",
    suppress_callback_exceptions=True,
)

app.layout = build_layout(saved_tickers=saved_tickers, saved_indicators=saved_indicators)
register_callbacks(app)
server = app.server

if __name__ == "__main__":
    app.run(
        debug=os.getenv("DASH_DEBUG", "0") == "1",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8050")),
    )
