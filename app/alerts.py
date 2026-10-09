"""Price alert system — MongoDB persistence, price checking, email notifications."""

from __future__ import annotations

import smtplib
import uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yfinance as yf

from config import (
    ALERT_SENDER_EMAIL,
    ALERT_SENDER_PASSWORD,
    ALERT_SMTP_SERVER,
    ALERT_SMTP_PORT,
    ALERT_RECIPIENTS,
)


# ── MongoDB helpers ──────────────────────────────────────────────────────

def _get_alerts_col():
    """Return the 'price_alerts' collection, or None."""
    try:
        from db.connection import get_db, ping
        if not ping():
            return None
        return get_db()["price_alerts"]
    except Exception:
        return None


def load_alerts() -> list[dict]:
    col = _get_alerts_col()
    if col is None:
        return []
    try:
        docs = list(col.find({}, {"_id": 0}).sort("created_at", -1))
        return docs
    except Exception:
        return []


def save_alert(alert: dict):
    col = _get_alerts_col()
    if col is None:
        return
    try:
        col.insert_one(alert)
    except Exception as e:
        print(f"[Alerts] save error: {e}")


def update_alert_status(alert_id: str, status: str, triggered_price: float | None = None):
    col = _get_alerts_col()
    if col is None:
        return
    try:
        update = {"$set": {"status": status, "updated_at": datetime.utcnow()}}
        if triggered_price is not None:
            update["$set"]["triggered_price"] = triggered_price
            update["$set"]["triggered_at"] = datetime.utcnow()
        col.update_one({"alert_id": alert_id}, update)
    except Exception as e:
        print(f"[Alerts] update error: {e}")


def delete_alert(alert_id: str):
    col = _get_alerts_col()
    if col is None:
        return
    try:
        col.delete_one({"alert_id": alert_id})
    except Exception as e:
        print(f"[Alerts] delete error: {e}")


def create_alert(symbol: str, target_price: float, direction: str, note: str = "") -> dict:
    """Build and persist a new alert document."""
    alert = {
        "alert_id": str(uuid.uuid4())[:8],
        "symbol": symbol.upper().strip(),
        "target_price": target_price,
        "direction": direction,
        "note": note,
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "triggered_at": None,
        "triggered_price": None,
    }
    save_alert(alert)
    return alert


# ── Price fetching (batch via yfinance) ──────────────────────────────────

def fetch_current_prices(symbols: list[str]) -> dict[str, float]:
    """Return {SYMBOL: latest_price} for a list of tickers."""
    prices: dict[str, float] = {}
    for sym in set(symbols):
        try:
            t = yf.Ticker(sym)
            try:
                p = t.fast_info["lastPrice"]
            except Exception:
                hist = t.history(period="1d")
                p = float(hist["Close"].iloc[-1]) if not hist.empty else None
            if p is not None:
                prices[sym] = float(p)
        except Exception:
            pass
    return prices


# ── Core check loop (called from a Dash Interval callback) ──────────────

def check_alerts() -> list[str]:
    """Check all active alerts against live prices.
    Returns a list of log messages for any triggered alerts."""
    alerts = load_alerts()
    active = [a for a in alerts if a.get("status") == "active"]
    if not active:
        return []

    symbols = list({a["symbol"] for a in active})
    prices = fetch_current_prices(symbols)
    if not prices:
        return []

    triggered_msgs: list[str] = []

    for a in active:
        sym = a["symbol"]
        price = prices.get(sym)
        if price is None:
            continue

        target = a["target_price"]
        direction = a["direction"]
        hit = False

        if direction == "above" and price >= target:
            hit = True
        elif direction == "below" and price <= target:
            hit = True

        if hit:
            update_alert_status(a["alert_id"], "triggered", triggered_price=price)
            arrow = "above" if direction == "above" else "below"
            msg = f"{sym} hit ${price:.2f} ({arrow} ${target:.2f})"
            triggered_msgs.append(msg)
            _send_email_notification(a, price)

    return triggered_msgs


# ── Email sender ─────────────────────────────────────────────────────────

def _send_email_notification(alert: dict, current_price: float):
    if not ALERT_SENDER_EMAIL or not ALERT_SENDER_PASSWORD or not ALERT_RECIPIENTS:
        print("[Alerts] Email not configured, skipping notification.")
        return

    sym = alert["symbol"]
    direction = alert["direction"]
    target = alert["target_price"]
    note = alert.get("note", "")

    subject = f"Stock Scout Alert: {sym} {'above' if direction == 'above' else 'below'} ${target:.2f}"

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
                background:#1a1a2e;color:#e0e0e0;border-radius:12px;overflow:hidden">
        <div style="background:#0f3460;padding:20px 24px">
            <h2 style="margin:0;color:#4ecdc4;letter-spacing:2px">STOCK SCOUT</h2>
            <p style="margin:4px 0 0;color:#aaa;font-size:0.85rem">Price Alert Triggered</p>
        </div>
        <div style="padding:24px">
            <h1 style="color:#fff;margin:0 0 8px">{sym}</h1>
            <p style="font-size:1.2rem;margin:0 0 16px">
                Current Price:
                <span style="color:#4ecdc4;font-weight:700;font-size:1.4rem">${current_price:.2f}</span>
            </p>
            <table style="width:100%;border-collapse:collapse;margin:0 0 16px">
                <tr>
                    <td style="padding:8px 0;color:#888;border-bottom:1px solid rgba(255,255,255,0.06)">
                        Condition</td>
                    <td style="padding:8px 0;color:#fff;font-weight:600;border-bottom:1px solid rgba(255,255,255,0.06)">
                        Price goes {'above' if direction == 'above' else 'below'} ${target:.2f}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;color:#888;border-bottom:1px solid rgba(255,255,255,0.06)">
                        Triggered At</td>
                    <td style="padding:8px 0;color:#fff;font-weight:600;border-bottom:1px solid rgba(255,255,255,0.06)">
                        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td>
                </tr>
                {"<tr><td style='padding:8px 0;color:#888'>Note</td><td style='padding:8px 0;color:#fff'>" + note + "</td></tr>" if note else ""}
            </table>
            <p style="color:#666;font-size:0.75rem;margin-top:24px">
                This is an automated alert from Stock Scout. Do not reply to this email.</p>
        </div>
    </div>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = ALERT_SENDER_EMAIL
        msg["To"] = ", ".join(ALERT_RECIPIENTS)
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(ALERT_SMTP_SERVER, ALERT_SMTP_PORT) as server:
            server.starttls()
            server.login(ALERT_SENDER_EMAIL, ALERT_SENDER_PASSWORD)
            server.sendmail(ALERT_SENDER_EMAIL, ALERT_RECIPIENTS, msg.as_string())

        print(f"[Alerts] Email sent for {alert['symbol']} to {len(ALERT_RECIPIENTS)} recipients.")
    except Exception as e:
        print(f"[Alerts] Email error: {e}")
