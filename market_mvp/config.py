"""Small, centralized product configuration for the standalone MVP."""

import os


APP_NAME = os.getenv("MARKET_MVP_NAME", "FLOW SCOUT")
APP_TAGLINE = "Gamma structure. Unusual volume. One workflow."
DEFAULT_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "AAPL", "NVDA", "TSLA", "AMD",
    "META", "AMZN", "MSFT", "GOOGL", "NFLX", "COIN", "PLTR",
]

COLORS = {
    "bg": "#070a0e",
    "panel": "#0d1218",
    "panel_2": "#111820",
    "border": "#1c2833",
    "text": "#edf4f7",
    "muted": "#7f919d",
    "cyan": "#37d8d2",
    "green": "#31d08b",
    "red": "#ff5573",
    "amber": "#f4bd4b",
    "purple": "#9d7bf2",
}
