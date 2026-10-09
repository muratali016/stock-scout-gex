"""Cached access to the existing analytics engines.

The UI imports this module instead of reaching directly into a data vendor.
That boundary makes replacing yfinance with a licensed feed much easier.
"""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any, Callable

import pandas as pd
import yfinance as yf

from engine.gex import compute_gex
from engine.volume_scanner import (
    get_intraday_timeline,
    get_volume_history,
    scan_symbols,
)


class TTLCache:
    def __init__(self) -> None:
        self._values: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._lock = RLock()

    def get_or_set(self, key: tuple[Any, ...], ttl: int,
                   loader: Callable[[], Any]) -> Any:
        now = monotonic()
        with self._lock:
            hit = self._values.get(key)
            if hit and hit[0] > now:
                return deepcopy(hit[1])
        value = loader()
        with self._lock:
            self._values[key] = (now + ttl, deepcopy(value))
        return value


_cache = TTLCache()


def get_gex(symbol: str, dtes: list[int] | None, max_expirations: int,
            strike_window_pct: float):
    symbol = symbol.strip().upper()
    normalized_dtes = tuple(sorted(set(dtes or [])))
    key = ("gex", symbol, normalized_dtes, max_expirations,
           round(strike_window_pct, 4))
    return _cache.get_or_set(
        key, 60,
        lambda: compute_gex(
            symbol,
            max_expirations=max_expirations,
            strike_window_pct=strike_window_pct,
            dtes=list(normalized_dtes),
        ),
    )


def get_volume_scan(symbols: list[str]):
    normalized = tuple(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    return _cache.get_or_set(
        ("volume-scan", normalized), 45,
        lambda: scan_symbols(normalized),
    )


def get_volume_detail(symbol: str, timeframe: str, lookback_days: int):
    symbol = symbol.strip().upper()
    key = ("volume-detail", symbol, timeframe, lookback_days)
    return _cache.get_or_set(
        key, 30,
        lambda: {
            "timeline": get_intraday_timeline(symbol, lookback_days),
            "history": get_volume_history(symbol, timeframe, lookback_days),
        },
    )


def get_price_bars(symbol: str, period: str = "1d", interval: str = "5m"):
    symbol = symbol.strip().upper()

    def _load():
        bars = yf.download(
            symbol, period=period, interval=interval, auto_adjust=False,
            prepost=False, progress=False, threads=False,
        )
        if bars is None or bars.empty:
            return pd.DataFrame()
        if isinstance(bars.columns, pd.MultiIndex):
            bars.columns = bars.columns.get_level_values(0)
        bars = bars.copy()
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        bars.index = bars.index.tz_convert("America/Los_Angeles")
        return bars

    return _cache.get_or_set(("price-bars", symbol, period, interval), 25, _load)
