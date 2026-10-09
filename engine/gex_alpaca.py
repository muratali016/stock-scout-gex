"""Alpaca-backed Gamma Exposure calculation.

All option-chain inputs come from Alpaca:

* contract metadata endpoint: strike, expiration, type and open interest
* option snapshots endpoint: implied volatility and current gamma
* stock snapshot/bars endpoints: underlying spot and chart candles

The output is the same ``GexResult`` used by the yfinance implementation so
both dashboards can render identical analytics for direct comparison.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from math import erf, exp, log, sqrt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

from credential_store import get_alpaca_credentials
from engine.gex import (
    GexResult,
    MAX_IV,
    MIN_IV,
    _find_level_crossing,
    _scenario_curve,
    bs_gamma,
)


ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
CONTRACT_MULT = 100.0
ONE_PERCENT_MOVE = 0.01


_CLIENTS = None


def reset_clients():
    """Discard cached clients after credentials are changed in the UI."""
    global _CLIENTS
    _CLIENTS = None


def _clients():
    """Return authenticated read-only clients, preferring paper credentials."""
    global _CLIENTS
    if _CLIENTS is not None:
        return _CLIENTS
    paper_key, paper_secret = get_alpaca_credentials("paper")
    live_key, live_secret = get_alpaca_credentials("live")
    candidates = [
        (paper_key, paper_secret, True),
        (live_key, live_secret, False),
    ]
    failures = []
    for key, secret, paper in candidates:
        if not key or not secret:
            continue
        try:
            trading = TradingClient(key, secret, paper=paper)
            # Read-only authentication probe; no order or account mutation.
            trading.get_account()
            _CLIENTS = (
                trading,
                OptionHistoricalDataClient(key, secret),
                StockHistoricalDataClient(key, secret),
            )
            return _CLIENTS
        except Exception as exc:
            failures.append(f"{'paper' if paper else 'live'}: {type(exc).__name__}")
    detail = ", ".join(failures) or "no credentials configured"
    raise RuntimeError(f"No working Alpaca credentials ({detail})")


def _stock_spot(client: StockHistoricalDataClient, symbol: str) -> float:
    snapshots = client.get_stock_snapshot(
        StockSnapshotRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX))
    snapshot = snapshots.get(symbol)
    if snapshot is None:
        raise RuntimeError(f"Alpaca returned no stock snapshot for {symbol}")
    candidates = [
        getattr(getattr(snapshot, "latest_trade", None), "price", None),
        getattr(getattr(snapshot, "minute_bar", None), "close", None),
        getattr(getattr(snapshot, "daily_bar", None), "close", None),
        getattr(getattr(snapshot, "previous_daily_bar", None), "close", None),
    ]
    for value in candidates:
        if value is not None and float(value) > 0:
            return float(value)
    raise RuntimeError(f"Alpaca snapshot has no usable price for {symbol}")


def _contract_pages(client: TradingClient, **kwargs):
    contracts = []
    page_token = None
    for _ in range(20):
        request = GetOptionContractsRequest(
            **kwargs, limit=1000, page_token=page_token)
        response = client.get_option_contracts(request)
        page = list(getattr(response, "option_contracts", []) or [])
        contracts.extend(page)
        page_token = getattr(response, "next_page_token", None)
        if not page_token:
            break
    return contracts


def _discover_expirations(client: TradingClient, symbol: str, spot: float,
                          today: date) -> list[str]:
    # A narrow strike slice discovers listed expiration dates without pulling
    # the full contract universe just to build the expiration selector.
    contracts = _contract_pages(
        client,
        underlying_symbols=[symbol],
        expiration_date_gte=today,
        expiration_date_lte=today + timedelta(days=400),
        strike_price_gte=f"{spot * 0.98:.2f}",
        strike_price_lte=f"{spot * 1.02:.2f}",
    )
    return sorted({str(contract.expiration_date) for contract in contracts})


def _select_expirations(expirations: list[str], max_expirations: int,
                        dtes: list[int] | None, today: date):
    wanted = {int(value) for value in (dtes or []) if int(value) >= 0}
    selected = []
    selected_dtes = []
    for expiry in expirations:
        expiry_date = date.fromisoformat(expiry)
        dte = (expiry_date - today).days
        if dte < 0 or (wanted and dte not in wanted):
            continue
        selected.append(expiry)
        selected_dtes.append(dte)
        if len(selected) >= max(1, int(max_expirations)):
            break
    return selected, selected_dtes


def _years_to_expiry(expiry: str, now_et: datetime) -> float:
    close = datetime.combine(date.fromisoformat(expiry), time(16, 0), ET)
    seconds = max((close - now_et).total_seconds(), 60.0)
    return seconds / (365.25 * 24 * 60 * 60)


def _option_feed(client: OptionHistoricalDataClient, request_kwargs: dict):
    try:
        return client.get_option_chain(OptionChainRequest(
            **request_kwargs, feed=OptionsFeed.OPRA)), "OPRA"
    except Exception:
        return client.get_option_chain(OptionChainRequest(
            **request_kwargs, feed=OptionsFeed.INDICATIVE)), "INDICATIVE"


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _bs_price(spot: float, strike: float, years: float, rate: float,
              volatility: float, side: str) -> float:
    if min(spot, strike, years, volatility) <= 0:
        return 0.0
    root_t = sqrt(years)
    d1 = ((log(spot / strike) + (rate + 0.5 * volatility ** 2) * years)
          / (volatility * root_t))
    d2 = d1 - volatility * root_t
    discounted_strike = strike * exp(-rate * years)
    if side == "C":
        return spot * _norm_cdf(d1) - discounted_strike * _norm_cdf(d2)
    return discounted_strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _market_option_price(snapshot, contract) -> float | None:
    quote = getattr(snapshot, "latest_quote", None)
    bid = getattr(quote, "bid_price", None)
    ask = getattr(quote, "ask_price", None)
    try:
        bid_value, ask_value = float(bid), float(ask)
        if 0 <= bid_value <= ask_value and ask_value > 0:
            return (bid_value + ask_value) / 2.0
    except (TypeError, ValueError):
        pass
    for raw in (
        getattr(getattr(snapshot, "latest_trade", None), "price", None),
        getattr(contract, "close_price", None),
    ):
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            continue
    return None


def _implied_volatility(price: float, spot: float, strike: float, years: float,
                        rate: float, side: str) -> float | None:
    intrinsic = max(0.0, spot-strike) if side == "C" else max(0.0, strike-spot)
    upper_bound = spot if side == "C" else strike * exp(-rate * years)
    if price < intrinsic - 0.03 or price >= upper_bound:
        return None
    low, high = MIN_IV, MAX_IV
    low_price = _bs_price(spot, strike, years, rate, low, side)
    high_price = _bs_price(spot, strike, years, rate, high, side)
    if price < low_price - 0.03 or price > high_price + 0.03:
        return None
    for _ in range(70):
        mid = (low + high) / 2.0
        estimate = _bs_price(spot, strike, years, rate, mid, side)
        if estimate > price:
            high = mid
        else:
            low = mid
    result = (low + high) / 2.0
    return result if MIN_IV <= result <= MAX_IV else None


def compute_gex_alpaca(symbol: str, max_expirations: int = 8,
                       strike_window_pct: float = 0.20,
                       risk_free: float = 0.045,
                       strike_bin: float | None = None,
                       dtes: list[int] | None = None) -> GexResult:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return GexResult(symbol="", spot=0.0, as_of="",
                         notes=["No symbol provided."])

    trading, option_data, stock_data = _clients()
    now_et = datetime.now(ET)
    today = now_et.date()
    spot = _stock_spot(stock_data, symbol)
    window = max(0.02, min(float(strike_window_pct), 0.60))
    strike_low, strike_high = spot * (1-window), spot * (1+window)

    all_expirations = _discover_expirations(trading, symbol, spot, today)
    expirations, expiration_dtes = _select_expirations(
        all_expirations, max_expirations, dtes, today)
    if not expirations:
        return GexResult(
            symbol=symbol, spot=spot,
            as_of=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            notes=["Alpaca returned no expirations matching the DTE filter."],
        )

    rows: list[dict] = []
    feeds: set[str] = set()
    oi_dates: set[str] = set()
    derived_iv_rows = 0
    for expiry in expirations:
        contracts = _contract_pages(
            trading,
            underlying_symbols=[symbol],
            expiration_date=expiry,
            strike_price_gte=f"{strike_low:.2f}",
            strike_price_lte=f"{strike_high:.2f}",
        )
        if not contracts:
            continue
        snapshots, feed = _option_feed(option_data, {
            "underlying_symbol": symbol,
            "expiration_date": expiry,
            "strike_price_gte": strike_low,
            "strike_price_lte": strike_high,
        })
        feeds.add(feed)
        years = _years_to_expiry(expiry, now_et)
        dte = (date.fromisoformat(expiry) - today).days
        for contract in contracts:
            oi_raw = getattr(contract, "open_interest", None)
            snapshot = snapshots.get(contract.symbol)
            if snapshot is None or oi_raw in (None, ""):
                continue
            try:
                oi = float(oi_raw)
                strike = float(contract.strike_price)
            except (TypeError, ValueError):
                continue
            if oi <= 0:
                continue
            side = "C" if "call" in str(contract.type).lower() else "P"
            sign = 1.0 if side == "C" else -1.0
            try:
                iv = float(snapshot.implied_volatility)
            except (TypeError, ValueError):
                option_price = _market_option_price(snapshot, contract)
                iv = (_implied_volatility(
                    option_price, spot, strike, years, risk_free, side)
                      if option_price is not None else None)
                if iv is not None:
                    derived_iv_rows += 1
            if iv is None or not (MIN_IV <= iv <= MAX_IV):
                continue
            gamma_raw = getattr(getattr(snapshot, "greeks", None), "gamma", None)
            try:
                gamma = float(gamma_raw)
            except (TypeError, ValueError):
                gamma = float(bs_gamma(spot, strike, years, risk_free, iv))
            if not np.isfinite(gamma) or gamma <= 0:
                continue
            gex = gamma * oi * CONTRACT_MULT * spot * spot * ONE_PERCENT_MOVE * sign
            rows.append({
                "expiry": expiry, "dte": dte, "strike": strike,
                "side": side, "oi": oi, "iv": iv, "gamma": gamma,
                "years": years, "sign": sign, "gex": gex,
            })
            oi_date = getattr(contract, "open_interest_date", None)
            if oi_date:
                oi_dates.add(str(oi_date))

    if not rows:
        return GexResult(
            symbol=symbol, spot=spot,
            as_of=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            expirations=expirations, expiration_dtes=expiration_dtes,
            notes=["Alpaca contracts had no usable OI/IV/gamma rows."],
        )

    frame = pd.DataFrame(rows)
    if strike_bin and float(strike_bin) > 0:
        width = float(strike_bin)
        frame["strike"] = (frame["strike"] / width).round() * width

    strikes = sorted(float(value) for value in frame["strike"].unique())
    used_exps = [exp for exp in expirations if exp in set(frame["expiry"])]
    used_dtes = [(date.fromisoformat(exp) - today).days for exp in used_exps]
    heat = (frame.groupby(["strike", "expiry"])["gex"].sum()
            .unstack(fill_value=0.0)
            .reindex(index=strikes, columns=used_exps, fill_value=0.0))
    side_gex = (frame.groupby(["strike", "side"])["gex"].sum()
                .unstack(fill_value=0.0).reindex(strikes, fill_value=0.0))
    side_oi = (frame.groupby(["strike", "side"])["oi"].sum()
               .unstack(fill_value=0.0).reindex(strikes, fill_value=0.0))
    for column in ("C", "P"):
        if column not in side_gex:
            side_gex[column] = 0.0
        if column not in side_oi:
            side_oi[column] = 0.0

    call_profile = side_gex["C"].astype(float).to_list()
    put_profile = side_gex["P"].astype(float).to_list()
    profile = (side_gex["C"] + side_gex["P"]).astype(float).to_list()
    cumulative = np.cumsum(profile).astype(float).tolist()
    total_gex = float(frame["gex"].sum())

    scenario_spots, scenario_gex = _scenario_curve(
        K=frame["strike"].to_numpy(float),
        T=frame["years"].to_numpy(float),
        r=float(risk_free),
        sigma=frame["iv"].to_numpy(float),
        oi=frame["oi"].to_numpy(float),
        sign=frame["sign"].to_numpy(float),
        low=spot * (1-window), high=spot * (1+window),
    )
    flip = _find_level_crossing(scenario_spots, scenario_gex, spot)

    expiry_side = (frame.groupby(["expiry", "side"])["gex"].sum()
                   .unstack(fill_value=0.0).reindex(used_exps, fill_value=0.0))
    for column in ("C", "P"):
        if column not in expiry_side:
            expiry_side[column] = 0.0
    expiration_gex = [{
        "expiry": expiry,
        "dte": (date.fromisoformat(expiry) - today).days,
        "call_gex": float(expiry_side.loc[expiry, "C"]),
        "put_gex": float(expiry_side.loc[expiry, "P"]),
        "net_gex": float(expiry_side.loc[expiry, "C"] + expiry_side.loc[expiry, "P"]),
    } for expiry in used_exps]

    call_walls = [
        {"strike": float(strike), "gex": float(value)}
        for strike, value in side_gex["C"].sort_values(ascending=False).head(5).items()
        if value > 0
    ]
    put_walls = [
        {"strike": float(strike), "gex": float(value)}
        for strike, value in side_gex["P"].sort_values(ascending=True).head(5).items()
        if value < 0
    ]
    notes = [
        f"Alpaca feed: {', '.join(sorted(feeds)) or 'unknown'}.",
        f"Alpaca OI date(s): {', '.join(sorted(oi_dates)) or 'not supplied'}.",
        (f"Alpaca supplied IV/Greeks where available; IV was derived from "
         f"Alpaca quote/trade prices for {derived_iv_rows} rows."),
        "Scenario curve reprices the Alpaca-sourced chain with Black-Scholes.",
    ]
    return GexResult(
        symbol=symbol, spot=spot,
        as_of=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        expirations=used_exps, expiration_dtes=used_dtes,
        strikes=strikes, heatmap=heat.to_numpy(float).tolist(),
        profile=profile, call_profile=call_profile, put_profile=put_profile,
        call_oi_profile=side_oi["C"].astype(float).to_list(),
        put_oi_profile=side_oi["P"].astype(float).to_list(),
        cumulative=cumulative,
        scenario_spots=scenario_spots.astype(float).tolist(),
        scenario_gex=scenario_gex.astype(float).tolist(),
        flip_price=flip, total_gex=total_gex,
        call_gex=float(frame.loc[frame["side"] == "C", "gex"].sum()),
        put_gex=float(frame.loc[frame["side"] == "P", "gex"].sum()),
        call_oi=float(frame.loc[frame["side"] == "C", "oi"].sum()),
        put_oi=float(frame.loc[frame["side"] == "P", "oi"].sum()),
        expiration_gex=expiration_gex,
        call_walls=call_walls, put_walls=put_walls,
        notes=notes, rows=len(frame),
    )


def fetch_alpaca_bars(symbol: str, period: str = "1d", interval: str = "5m") -> pd.DataFrame:
    """Return Alpaca stock bars shaped like yfinance OHLCV output."""
    _, _, stock_data = _clients()
    now = datetime.now(timezone.utc)
    days = 8 if period == "5d" else 2
    amount = {"1m": 1, "5m": 5, "15m": 15, "30m": 30}.get(interval, 5)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(amount, TimeFrameUnit.Minute),
        start=now - timedelta(days=days), end=now,
        feed=DataFeed.IEX,
    )
    bars = stock_data.get_stock_bars(request).df
    if bars is None or bars.empty:
        return pd.DataFrame()
    if isinstance(bars.index, pd.MultiIndex):
        try:
            bars = bars.xs(symbol, level=0)
        except KeyError:
            return pd.DataFrame()
    bars = bars.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    bars.index = bars.index.tz_convert(PT)
    return bars[["Open", "High", "Low", "Close", "Volume"]]
