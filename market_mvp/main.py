"""Run the standalone three-product MVP with ``python -m market_mvp.main``."""

from __future__ import annotations

import os

import dash
import dash_bootstrap_components as dbc

from market_mvp.callbacks import register_callbacks
from market_mvp.config import APP_NAME
from market_mvp.layout import build_layout


ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

app = dash.Dash(
    __name__,
    assets_folder=ASSETS_DIR,
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap",
    ],
    title=f"{APP_NAME} · GEX & Volume",
    update_title="Updating market data…",
    suppress_callback_exceptions=True,
)
app.layout = build_layout()
register_callbacks(app)
server = app.server


if __name__ == "__main__":
    app.run(
        debug=os.getenv("DASH_DEBUG", "0") == "1",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8060")),
    )
