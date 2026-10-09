"""Alpaca Trading & Options helpers for the Trade tab.

IMPORTANT: execute_trade() and close_all_positions() are wired but gated
behind explicit confirmation callbacks.  They are intentionally NOT called
from any auto-triggered callback to prevent accidental orders.
"""

from __future__ import annotations

import traceback
from datetime import datetime

import yfinance as yf

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOptionContractsRequest,
    GetOrdersRequest,
    OptionLegRequest,
)
from alpaca.trading.enums import (
    OrderSide, TimeInForce, AssetStatus, OrderClass, PositionIntent,
    QueryOrderStatus,
)

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest
from alpaca.data.enums import OptionsFeed

from credential_store import get_alpaca_credentials

# ── Module-level clients (lazy-initialised) ─────────────────────────────

_trading_client: TradingClient | None = None
_data_client: OptionHistoricalDataClient | None = None
_is_paper: bool = True


def reset_clients() -> None:
    """Discard cached clients after credentials are changed in the UI."""
    global _trading_client, _data_client
    _trading_client = None
    _data_client = None


def get_clients(paper: bool = True) -> tuple[TradingClient, OptionHistoricalDataClient]:
    """Return (trading_client, option_data_client), creating them if needed."""
    global _trading_client, _data_client, _is_paper
    if _trading_client is None or paper != _is_paper:
        environment = "paper" if paper else "live"
        key, sec = get_alpaca_credentials(environment)
        if not key or not sec:
            raise RuntimeError(
                f"Alpaca {environment} credentials are not configured."
            )
        _trading_client = TradingClient(key, sec, paper=paper)
        _data_client = OptionHistoricalDataClient(key, sec)
        _is_paper = paper
    return _trading_client, _data_client


# ── Account & positions ─────────────────────────────────────────────────

def fetch_account_summary(paper: bool = True) -> dict:
    try:
        tc, _ = get_clients(paper)
        acct = tc.get_account()
        return {
            "equity": float(acct.equity),
            "buying_power": float(acct.buying_power),
            "cash": float(acct.cash),
        }
    except Exception as exc:
        return {"equity": 0, "buying_power": 0, "cash": 0, "error": str(exc)}


def fetch_positions(paper: bool = True) -> list[dict]:
    try:
        tc, _ = get_clients(paper)
        positions = tc.get_all_positions()
        rows = []
        for p in positions:
            cost_basis = float(p.cost_basis) if p.cost_basis else 0.0
            mkt_val = float(p.market_value) if p.market_value else 0.0
            upl = float(p.unrealized_pl) if p.unrealized_pl else 0.0
            plpc_raw = getattr(p, "unrealized_plpc", 0.0)
            upl_pct = float(plpc_raw) * 100 if plpc_raw else 0.0
            rows.append({
                "symbol": p.symbol,
                "qty": str(p.qty),
                "cost_basis": cost_basis,
                "market_value": mkt_val,
                "unrealized_pl": upl,
                "return_pct": round(upl_pct, 2),
            })
        return rows
    except Exception as exc:
        return [{"symbol": f"ERROR: {exc}", "qty": "", "cost_basis": 0,
                 "market_value": 0, "unrealized_pl": 0, "return_pct": 0}]


# ── Options chain ────────────────────────────────────────────────────────

def fetch_expiration_dates(symbol: str) -> tuple[list[str], float]:
    """Return (list of expiration date strings, current price)."""
    ticker = yf.Ticker(symbol.upper().strip())
    try:
        price = ticker.fast_info["lastPrice"]
    except Exception:
        hist = ticker.history(period="1d")
        price = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
    dates = list(ticker.options) if ticker.options else []
    return dates, float(price)


def fetch_options_chain(
    symbol: str,
    expiration_date: str,
    spread: int = 5,
    current_price: float = 0.0,
    paper: bool = True,
) -> list[dict]:
    """Fetch options chain around ATM for a given date.  Returns list of
    dicts ready for a Dash DataTable."""
    tc, dc = get_clients(paper)

    req = GetOptionContractsRequest(
        underlying_symbols=[symbol.upper()],
        status=AssetStatus.ACTIVE,
        expiration_date_gte=expiration_date,
        expiration_date_lte=expiration_date,
        limit=2000,
    )
    res = tc.get_option_contracts(req)
    contracts = res.option_contracts if res.option_contracts else []
    if not contracts:
        return []

    calls = sorted(
        [c for c in contracts if "call" in str(c.type).lower()],
        key=lambda x: float(x.strike_price),
    )
    puts = sorted(
        [c for c in contracts if "put" in str(c.type).lower()],
        key=lambda x: float(x.strike_price),
    )

    def closest_idx(lst, target):
        if not lst:
            return -1
        return min(range(len(lst)), key=lambda i: abs(float(lst[i].strike_price) - target))

    ci = closest_idx(calls, current_price)
    pi = closest_idx(puts, current_price)

    sliced_calls = calls[max(0, ci - spread): ci + spread + 1] if ci >= 0 else []
    sliced_puts = puts[max(0, pi - spread): pi + spread + 1] if pi >= 0 else []

    all_syms = [c.symbol for c in sliced_calls] + [c.symbol for c in sliced_puts]
    snaps: dict = {}
    if all_syms:
        try:
            snap_req = OptionSnapshotRequest(
                symbol_or_symbols=all_syms, feed=OptionsFeed.INDICATIVE
            )
            snaps = dc.get_option_snapshot(snap_req)
        except Exception:
            pass

    def greek(sym, name):
        if sym in snaps and snaps[sym].greeks:
            v = getattr(snaps[sym].greeks, name, None)
            return round(v, 4) if v is not None else None
        return None

    def iv(sym):
        if sym in snaps and snaps[sym].implied_volatility is not None:
            return round(snaps[sym].implied_volatility * 100, 2)
        return None

    def quote(sym, side):
        if sym in snaps and snaps[sym].latest_quote:
            q = snaps[sym].latest_quote
            v = q.bid_price if side == "bid" else q.ask_price
            return round(float(v), 2) if v is not None else None
        return None

    rows: list[dict] = []
    for c in sliced_calls:
        strike = float(c.strike_price)
        atm = ci >= 0 and c == calls[ci]
        rows.append({
            "type": "CALL",
            "strike": strike,
            "atm": atm,
            "bid": quote(c.symbol, "bid"),
            "ask": quote(c.symbol, "ask"),
            "delta": greek(c.symbol, "delta"),
            "gamma": greek(c.symbol, "gamma"),
            "theta": greek(c.symbol, "theta"),
            "vega": greek(c.symbol, "vega"),
            "rho": greek(c.symbol, "rho"),
            "iv": iv(c.symbol),
            "option_symbol": c.symbol,
        })

    for c in sliced_puts:
        strike = float(c.strike_price)
        atm = pi >= 0 and c == puts[pi]
        rows.append({
            "type": "PUT",
            "strike": strike,
            "atm": atm,
            "bid": quote(c.symbol, "bid"),
            "ask": quote(c.symbol, "ask"),
            "delta": greek(c.symbol, "delta"),
            "gamma": greek(c.symbol, "gamma"),
            "theta": greek(c.symbol, "theta"),
            "vega": greek(c.symbol, "vega"),
            "rho": greek(c.symbol, "rho"),
            "iv": iv(c.symbol),
            "option_symbol": c.symbol,
        })

    return rows


# ── Trade execution (gated — only called via explicit user action) ──────

def execute_trade(
    symbol: str,
    qty: float,
    side: str,
    order_type: str = "Market",
    limit_price: float | None = None,
    tif: str = "DAY",
    paper: bool = True,
) -> str:
    """Submit an order.  Returns a status message string."""
    tc, _ = get_clients(paper)
    tif_enum = getattr(TimeInForce, tif, TimeInForce.DAY)
    side_enum = OrderSide.BUY if side == "BUY" else OrderSide.SELL

    try:
        if order_type == "Limit" and limit_price is not None:
            req = LimitOrderRequest(
                symbol=symbol, qty=qty, side=side_enum,
                limit_price=limit_price, time_in_force=tif_enum,
            )
        else:
            req = MarketOrderRequest(
                symbol=symbol, qty=qty, side=side_enum,
                time_in_force=tif_enum,
            )
        tc.submit_order(order_data=req)
        return f"Order sent: {side} {qty} x {symbol} ({order_type})"
    except Exception as exc:
        return f"Order FAILED: {exc}"


def close_all_positions(paper: bool = True) -> str:
    tc, _ = get_clients(paper)
    try:
        tc.close_all_positions(cancel_orders=True)
        return "Liquidation orders sent for all positions."
    except Exception as exc:
        return f"Close-all FAILED: {exc}"


# ── Multi-leg (mleg) execution ──────────────────────────────────────────

_SIDE_MAP = {"buy": OrderSide.BUY, "sell": OrderSide.SELL}
_INTENT_MAP = {
    "buy_to_open":   PositionIntent.BUY_TO_OPEN,
    "sell_to_open":  PositionIntent.SELL_TO_OPEN,
    "buy_to_close":  PositionIntent.BUY_TO_CLOSE,
    "sell_to_close": PositionIntent.SELL_TO_CLOSE,
}


def execute_mleg_order(
    legs: list[dict],
    limit_price: float,
    qty: int = 1,
    tif: str = "DAY",
    paper: bool = True,
) -> dict:
    """Submit an Alpaca multi-leg (mleg) limit order.

    `legs` is a list of dicts shaped like::

        {"symbol": "...", "side": "buy"|"sell",
         "ratio_qty": 1, "position_intent": "buy_to_open"|...}

    2-leg vertical spreads, 3-leg butterflies, and 4-leg Iron Condors
    all flow through this function — Alpaca caps mleg at 4 legs.

    `limit_price` is the absolute net price per spread (positive),
    representing the max debit you'll pay (debit spreads) or the min
    credit you'll accept (credit spreads / Iron Condors).

    Returns ``{ok, message, order_id, status, payload}``; failures are
    surfaced rather than raised.
    """
    payload = {
        "qty": str(int(qty)),
        "type": "limit",
        "time_in_force": str(tif).lower(),
        "order_class": "mleg",
        "limit_price": f"{round(float(limit_price), 2):.2f}",
        "legs": [
            {"symbol": l.get("symbol"),
             "side": str(l.get("side") or "").lower(),
             "ratio_qty": str(int(l.get("ratio_qty") or 1)),
             "position_intent": str(l.get("position_intent")
                                    or "buy_to_open").lower()}
            for l in (legs or [])
        ],
    }

    if not legs or len(legs) < 2:
        return {"ok": False, "message": "Order FAILED: mleg needs \u22652 legs",
                "order_id": None, "status": None, "payload": payload}
    if len(legs) > 4:
        return {"ok": False, "message": "Order FAILED: Alpaca mleg supports max 4 legs",
                "order_id": None, "status": None, "payload": payload}
    if any(not l.get("symbol") for l in legs):
        return {"ok": False, "message": "Order FAILED: missing leg symbols",
                "order_id": None, "status": None, "payload": payload}
    try:
        lp = float(limit_price)
    except (TypeError, ValueError):
        lp = 0.0
    if lp <= 0:
        return {"ok": False, "message": "Order FAILED: limit_price must be > 0",
                "order_id": None, "status": None, "payload": payload}

    tc, _ = get_clients(paper)
    tif_enum = getattr(TimeInForce, str(tif).upper(), TimeInForce.DAY)

    try:
        leg_requests = []
        for l in legs:
            side_key = str(l.get("side") or "").lower()
            intent_key = str(l.get("position_intent") or "buy_to_open").lower()
            side_enum = _SIDE_MAP.get(side_key)
            intent_enum = _INTENT_MAP.get(intent_key)
            if side_enum is None or intent_enum is None:
                return {"ok": False,
                        "message": f"Order FAILED: bad leg side/intent ({side_key}/{intent_key})",
                        "order_id": None, "status": None, "payload": payload}
            leg_requests.append(OptionLegRequest(
                symbol=l["symbol"],
                side=side_enum,
                ratio_qty=int(l.get("ratio_qty") or 1),
                position_intent=intent_enum,
            ))

        req = LimitOrderRequest(
            qty=int(qty),
            limit_price=round(lp, 2),
            time_in_force=tif_enum,
            order_class=OrderClass.MLEG,
            legs=leg_requests,
        )
        order = tc.submit_order(order_data=req)
        order_id = str(getattr(order, "id", "") or "")
        status = str(getattr(order, "status", "") or "")
        return {
            "ok": True,
            "message": f"Order accepted: id={order_id} status={status}",
            "order_id": order_id,
            "status": status,
            "payload": payload,
        }
    except Exception as exc:
        body = getattr(exc, "_error", None) or str(exc)
        return {
            "ok": False,
            "message": f"Order FAILED: {body}",
            "order_id": None,
            "status": None,
            "payload": payload,
        }


def fetch_filled_mleg_orders(paper: bool = True, limit: int = 100) -> list[dict]:
    """Return filled multi-leg orders with enough data to construct closes."""
    tc, _ = get_clients(paper)
    try:
        orders = tc.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            limit=limit,
            nested=True,
        ))
    except Exception as exc:
        return [{"error": str(exc)}]

    result = []
    for order in orders or []:
        order_class = getattr(order, "order_class", "")
        if str(getattr(order_class, "value", order_class)).lower() != "mleg":
            continue
        status_obj = getattr(order, "status", "")
        status = str(getattr(status_obj, "value", status_obj)).lower()
        if status not in {"filled", "partially_filled"}:
            continue
        legs = []
        for leg in (getattr(order, "legs", None) or []):
            side_obj = getattr(leg, "side", "")
            intent_obj = getattr(leg, "position_intent", "")
            side = str(getattr(side_obj, "value", side_obj)).lower()
            intent = str(getattr(intent_obj, "value", intent_obj)).lower()
            if side not in {"buy", "sell"}:
                continue
            legs.append({
                "symbol": getattr(leg, "symbol", ""),
                "side": side,
                "ratio_qty": float(getattr(leg, "ratio_qty", 1) or 1),
                "position_intent": intent,
            })
        if len(legs) < 2:
            continue
        submitted = getattr(order, "submitted_at", None)
        result.append({
            "id": str(getattr(order, "id", "")),
            "status": status,
            "qty": float(getattr(order, "qty", 1) or 1),
            "limit_price": float(getattr(order, "limit_price", 0) or 0),
            "submitted_at": submitted.isoformat() if submitted else "",
            "legs": legs,
        })
    return result


def build_mleg_close_legs(order: dict) -> list[dict]:
    """Reverse each filled leg into a buy/sell-to-close leg."""
    close_legs = []
    for leg in order.get("legs") or []:
        side = str(leg.get("side") or "").lower()
        close_legs.append({
            "symbol": leg.get("symbol"),
            "side": "sell" if side == "buy" else "buy",
            "ratio_qty": leg.get("ratio_qty", 1),
            "position_intent": "sell_to_close" if side == "buy" else "buy_to_close",
        })
    return close_legs
