"""Implied-volatility wall model using yfinance or Alpaca option chains.

"IV wall" is not a field published by either provider.  This module defines a
wall as a strike with concentrated open-interest-weighted vega exposure.  The
reported dollar value estimates how much the listed contracts' theoretical
value changes for a one-volatility-point move, before any dealer-sign model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from math import pi, sqrt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from engine.gex import MAX_IV, MIN_IV
from engine.gex_alpaca import (
    _clients as _alpaca_clients,
    _contract_pages,
    _discover_expirations,
    _implied_volatility,
    _market_option_price,
    _option_feed,
    _select_expirations as _select_alpaca_expirations,
    _stock_spot,
)


ET = ZoneInfo("America/New_York")


@dataclass
class IVWallResult:
    symbol: str
    provider: str
    spot: float
    as_of: str
    expirations: list[str] = field(default_factory=list)
    expiration_dtes: list[int] = field(default_factory=list)
    strikes: list[float] = field(default_factory=list)
    call_vex: list[float] = field(default_factory=list)
    put_vex: list[float] = field(default_factory=list)
    call_iv: list[float | None] = field(default_factory=list)
    put_iv: list[float | None] = field(default_factory=list)
    heatmap: list[list[float]] = field(default_factory=list)
    iv_heatmap: list[list[float | None]] = field(default_factory=list)
    expiration_summary: list[dict] = field(default_factory=list)
    call_walls: list[dict] = field(default_factory=list)
    put_walls: list[dict] = field(default_factory=list)
    total_call_vex: float = 0.0
    total_put_vex: float = 0.0
    rows: int = 0
    notes: list[str] = field(default_factory=list)


def _select_expirations(expirations: list[str], max_expirations: int,
                        dtes: list[int] | None, reference: date):
    wanted = set()
    for value in dtes or []:
        try:
            parsed = int(value)
            if parsed >= 0:
                wanted.add(parsed)
        except (TypeError, ValueError):
            continue
    selected: list[str] = []
    selected_dtes: list[int] = []
    for expiry in sorted(expirations):
        try:
            dte = (date.fromisoformat(str(expiry)) - reference).days
        except ValueError:
            continue
        if dte < 0 or (wanted and dte not in wanted):
            continue
        selected.append(str(expiry))
        selected_dtes.append(dte)
        if len(selected) >= max(1, int(max_expirations)):
            break
    return selected, selected_dtes


def _years(expiry: str, now_et: datetime) -> float:
    close = datetime.combine(date.fromisoformat(expiry), time(16, 0), ET)
    return max((close-now_et).total_seconds(), 0.0) / (365.25*24*60*60)


def _yfinance_rows(symbol: str, max_expirations: int, window: float,
                    dtes: list[int] | None):
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="2d", interval="1m", auto_adjust=False,
                             prepost=False)
    if history is None or history.empty:
        raise RuntimeError(f"yfinance returned no underlying price for {symbol}")
    spot = float(pd.to_numeric(history["Close"], errors="coerce").dropna().iloc[-1])
    now_et = datetime.now(ET)
    expirations, expiration_dtes = _select_expirations(
        list(ticker.options or []), max_expirations, dtes, now_et.date())
    rows: list[dict] = []
    for expiry, dte in zip(expirations, expiration_dtes):
        chain = ticker.option_chain(expiry)
        years = _years(expiry, now_et)
        if years <= 0:
            continue
        for side, frame in (("C", chain.calls), ("P", chain.puts)):
            if frame is None or frame.empty:
                continue
            for _, contract in frame.iterrows():
                try:
                    strike = float(contract["strike"])
                    oi = float(contract["openInterest"])
                    iv = float(contract["impliedVolatility"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not spot*(1-window) <= strike <= spot*(1+window):
                    continue
                if oi <= 0 or not MIN_IV <= iv <= MAX_IV:
                    continue
                rows.append({
                    "expiry": expiry, "dte": dte, "strike": strike,
                    "side": side, "oi": oi, "iv": iv, "years": years,
                })
    notes = ["yfinance displayed IV and open interest.",
             "Open interest is generally updated once per session."]
    return spot, expirations, expiration_dtes, pd.DataFrame(rows), notes


def _alpaca_rows(symbol: str, max_expirations: int, window: float,
                  dtes: list[int] | None, risk_free: float):
    trading, option_data, stock_data = _alpaca_clients()
    now_et = datetime.now(ET)
    spot = _stock_spot(stock_data, symbol)
    all_expirations = _discover_expirations(
        trading, symbol, spot, now_et.date())
    expirations, expiration_dtes = _select_alpaca_expirations(
        all_expirations, max_expirations, dtes, now_et.date())
    low, high = spot*(1-window), spot*(1+window)
    rows: list[dict] = []
    feeds: set[str] = set()
    oi_dates: set[str] = set()
    derived_iv = 0
    for expiry, dte in zip(expirations, expiration_dtes):
        contracts = _contract_pages(
            trading, underlying_symbols=[symbol], expiration_date=expiry,
            strike_price_gte=f"{low:.2f}", strike_price_lte=f"{high:.2f}")
        snapshots, feed = _option_feed(option_data, {
            "underlying_symbol": symbol, "expiration_date": expiry,
            "strike_price_gte": low, "strike_price_lte": high,
        })
        feeds.add(feed)
        years = _years(expiry, now_et)
        if years <= 0:
            continue
        for contract in contracts:
            snapshot = snapshots.get(contract.symbol)
            if snapshot is None:
                continue
            try:
                strike = float(contract.strike_price)
                oi = float(contract.open_interest)
            except (TypeError, ValueError):
                continue
            if oi <= 0:
                continue
            side = "C" if "call" in str(contract.type).lower() else "P"
            try:
                iv = float(snapshot.implied_volatility)
            except (TypeError, ValueError):
                price = _market_option_price(snapshot, contract)
                iv = (_implied_volatility(
                    price, spot, strike, years, risk_free, side)
                      if price is not None else None)
                if iv is not None:
                    derived_iv += 1
            if iv is None or not MIN_IV <= iv <= MAX_IV:
                continue
            rows.append({
                "expiry": expiry, "dte": dte, "strike": strike,
                "side": side, "oi": oi, "iv": iv, "years": years,
            })
            if contract.open_interest_date:
                oi_dates.add(str(contract.open_interest_date))
    notes = [
        f"Alpaca option feed: {', '.join(sorted(feeds)) or 'unknown'}.",
        f"Alpaca OI date(s): {', '.join(sorted(oi_dates)) or 'not supplied'}.",
        f"IV derived from Alpaca quote/trade prices for {derived_iv} rows when absent.",
    ]
    return spot, expirations, expiration_dtes, pd.DataFrame(rows), notes


def _weighted_iv(group: pd.DataFrame) -> float | None:
    weights = group["vex"].abs().to_numpy(float)
    values = group["iv"].to_numpy(float)
    total = float(weights.sum())
    return float(np.average(values, weights=weights)) if total > 0 else None


def compute_iv_walls(symbol: str, provider: str = "yfinance",
                     max_expirations: int = 8,
                     strike_window_pct: float = 0.15,
                     risk_free: float = 0.045,
                     dtes: list[int] | None = None) -> IVWallResult:
    symbol = (symbol or "").strip().upper()
    provider = (provider or "yfinance").strip().lower()
    if not symbol:
        return IVWallResult(symbol="", provider=provider, spot=0, as_of="",
                            notes=["No symbol provided."])
    window = max(.02, min(.60, float(strike_window_pct)))
    if provider == "alpaca":
        spot, expirations, dte_values, frame, notes = _alpaca_rows(
            symbol, max_expirations, window, dtes, risk_free)
    else:
        provider = "yfinance"
        spot, expirations, dte_values, frame, notes = _yfinance_rows(
            symbol, max_expirations, window, dtes)
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if frame.empty:
        return IVWallResult(
            symbol=symbol, provider=provider, spot=spot, as_of=as_of,
            expirations=expirations, expiration_dtes=dte_values,
            notes=notes + ["No usable IV/open-interest rows returned."],
        )

    # Dollar vega for a 1 percentage-point IV move across listed open interest:
    # vega/share per 1.0 vol × 100 shares × .01 vol point × OI.
    d1 = ((np.log(spot/frame["strike"].to_numpy(float))
           + (risk_free + .5*frame["iv"].to_numpy(float)**2)
           * frame["years"].to_numpy(float))
          / (frame["iv"].to_numpy(float)
             * np.sqrt(frame["years"].to_numpy(float))))
    normal_pdf = np.exp(-.5*d1*d1) / sqrt(2*pi)
    frame["vex"] = (spot * normal_pdf
                    * np.sqrt(frame["years"].to_numpy(float))
                    * frame["oi"].to_numpy(float))

    strikes = sorted(float(value) for value in frame["strike"].unique())
    used_expirations = [expiry for expiry in expirations
                        if expiry in set(frame["expiry"])]
    used_dtes = [(date.fromisoformat(expiry)-datetime.now(ET).date()).days
                 for expiry in used_expirations]
    call = (frame[frame["side"] == "C"].groupby("strike")["vex"].sum()
            .reindex(strikes, fill_value=0.0))
    put = (frame[frame["side"] == "P"].groupby("strike")["vex"].sum()
           .reindex(strikes, fill_value=0.0))

    call_iv_map = (frame[frame["side"] == "C"].groupby("strike")
                   .apply(_weighted_iv, include_groups=False).to_dict())
    put_iv_map = (frame[frame["side"] == "P"].groupby("strike")
                  .apply(_weighted_iv, include_groups=False).to_dict())
    call_iv = [call_iv_map.get(strike) for strike in strikes]
    put_iv = [put_iv_map.get(strike) for strike in strikes]

    signed = frame.assign(
        signed_vex=np.where(frame["side"] == "C", frame["vex"], -frame["vex"]))
    heat = (signed.groupby(["strike", "expiry"])["signed_vex"].sum()
            .unstack(fill_value=0.0)
            .reindex(index=strikes, columns=used_expirations, fill_value=0.0))
    iv_cells = (frame.groupby(["strike", "expiry"])
                .apply(_weighted_iv, include_groups=False).unstack()
                .reindex(index=strikes, columns=used_expirations))

    def walls_for(side: str, count: int = 8):
        side_frame = frame[frame["side"] == side]
        grouped = side_frame.groupby("strike").agg(
            vex=("vex", "sum"), oi=("oi", "sum"), expirations=("expiry", "nunique"))
        ivs = side_frame.groupby("strike").apply(
            _weighted_iv, include_groups=False)
        grouped["iv"] = ivs
        grouped = grouped.sort_values("vex", ascending=False).head(count)
        return [{
            "side": "CALL" if side == "C" else "PUT",
            "strike": float(strike), "vex": float(row.vex),
            "iv": float(row.iv), "oi": int(round(row.oi)),
            "expirations": int(row.expirations),
            "distance_pct": (float(strike)/spot-1)*100,
        } for strike, row in grouped.iterrows()]

    call_walls = walls_for("C")
    put_walls = walls_for("P")
    expiration_summary = []
    for expiry in used_expirations:
        chunk = frame[frame["expiry"] == expiry]
        calls = chunk[chunk["side"] == "C"]
        puts = chunk[chunk["side"] == "P"]
        expiration_summary.append({
            "expiry": expiry,
            "dte": (date.fromisoformat(expiry)-datetime.now(ET).date()).days,
            "call_vex": float(calls["vex"].sum()),
            "put_vex": float(puts["vex"].sum()),
            "call_iv": _weighted_iv(calls) if not calls.empty else None,
            "put_iv": _weighted_iv(puts) if not puts.empty else None,
        })

    return IVWallResult(
        symbol=symbol, provider=provider, spot=spot, as_of=as_of,
        expirations=used_expirations, expiration_dtes=used_dtes,
        strikes=strikes, call_vex=call.astype(float).tolist(),
        put_vex=put.astype(float).tolist(), call_iv=call_iv, put_iv=put_iv,
        heatmap=heat.to_numpy(float).tolist(),
        iv_heatmap=iv_cells.where(pd.notna(iv_cells), None).values.tolist(),
        expiration_summary=expiration_summary,
        call_walls=call_walls, put_walls=put_walls,
        total_call_vex=float(call.sum()), total_put_vex=float(put.sum()),
        rows=len(frame), notes=notes,
    )
