import pandas as pd
import numpy as np
import yfinance as yf
import requests
from io import StringIO
import warnings
import google.generativeai as genai
from config import GEMINI_API_KEY

warnings.filterwarnings("ignore")

_gemini_configured = False


def _ensure_gemini():
    global _gemini_configured
    if not _gemini_configured:
        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_configured = True


# =========================================================================
# S&P 500 Market Scanner
# =========================================================================

def _get_sp500_universe() -> pd.DataFrame:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    table = pd.read_html(StringIO(response.text))[0]
    table["Symbol"] = table["Symbol"].str.replace(".", "-", regex=False)
    return table[["Symbol", "GICS Sector"]].rename(
        columns={"Symbol": "Ticker", "GICS Sector": "Sector"}
    )


def fetch_sp500_movers() -> tuple[str, int]:
    """Scan S&P 500 for movers/gappers/volume spikes.
    Returns (csv_string, count_of_action_stocks)."""
    universe = _get_sp500_universe()
    tickers = universe["Ticker"].tolist()

    data = yf.download(tickers, period="1mo", progress=False)

    closes = data["Close"]
    opens = data["Open"]
    volumes = data["Volume"]
    results = []

    for ticker in tickers:
        try:
            if ticker not in closes.columns:
                continue
            if pd.isna(closes[ticker].iloc[-1]):
                continue

            current_close = closes[ticker].iloc[-1]
            prev_close = closes[ticker].iloc[-2]
            today_open = opens[ticker].iloc[-1]
            close_1w_ago = closes[ticker].iloc[-5] if len(closes[ticker]) >= 5 else np.nan
            close_1m_ago = closes[ticker].iloc[0]

            results.append({
                "Ticker": ticker,
                "Sector": universe.loc[universe["Ticker"] == ticker, "Sector"].iloc[0],
                "Price": round(float(current_close), 2),
                "1W Move %": round(((current_close / close_1w_ago) - 1) * 100, 2),
                "1M Move %": round(((current_close / close_1m_ago) - 1) * 100, 2),
                "Today Gap %": round(((today_open / prev_close) - 1) * 100, 2),
                "RVOL": round(
                    float(volumes[ticker].iloc[-1]) / float(volumes[ticker].mean()), 2
                ) if float(volumes[ticker].mean()) > 0 else 0,
            })
        except Exception:
            continue

    metrics_df = pd.DataFrame(results)

    action_df = metrics_df[
        (metrics_df["1W Move %"].abs() >= 3.0)
        | (metrics_df["Today Gap %"].abs() >= 1.5)
        | (metrics_df["RVOL"] >= 1.5)
    ]

    csv_str = action_df.to_csv(index=False) if not action_df.empty else "No notable movers today."
    return csv_str, len(action_df)


# =========================================================================
# Insider Data Scanner
# =========================================================================

def fetch_insider_data(signal_type: str = "cluster_buys") -> tuple[str, int]:
    """Fetch insider data from OpenInsider.
    Returns (csv_string, row_count)."""
    urls = {
        "cluster_buys": "http://openinsider.com/latest-cluster-buys",
        "top_sales": "http://openinsider.com/latest-insider-sales-100k",
    }
    url = urls.get(signal_type)
    if not url:
        return "", 0

    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    response.raise_for_status()

    tables = pd.read_html(StringIO(response.text))
    df = None
    for table in tables:
        table.columns = table.columns.astype(str).str.replace("\xa0", " ").str.strip()
        if "Ticker" in table.columns and "Value" in table.columns:
            df = table
            break

    if df is None or df.empty:
        return "", 0

    if "Value" in df.columns:
        clean_val = df["Value"].astype(str).str.replace(r"[+$CAD,]", "", regex=True)
        df["Value_Numeric"] = pd.to_numeric(clean_val, errors="coerce").fillna(0)

    cols_to_keep = [
        "Trade Date", "Ticker", "Company Name", "Trade Type",
        "Price", "Qty", "Value", "Value_Numeric",
    ]
    if "Ins" in df.columns:
        cols_to_keep.insert(3, "Ins")
    if "Insider Name" in df.columns:
        cols_to_keep.insert(3, "Insider Name")
    df = df[[c for c in cols_to_keep if c in df.columns]]

    if signal_type == "cluster_buys":
        df = df[df["Value_Numeric"] >= 50_000]
    elif signal_type == "top_sales":
        df = df[df["Value_Numeric"].abs() >= 500_000]

    csv_str = df.to_csv(index=False) if not df.empty else ""
    return csv_str, len(df)


# =========================================================================
# Gemini Chat
# =========================================================================

def ask_gemini(system_context: str, history: list[dict]) -> str:
    """Send a message to Gemini with the given system context and history.
    Returns the model's reply text."""
    _ensure_gemini()

    model = genai.GenerativeModel(
        model_name="gemini-2.5-pro",
        system_instruction=system_context,
    )

    cfg = genai.GenerationConfig(temperature=0.2)
    response = model.generate_content(history, generation_config=cfg)
    return response.text.strip()


# =========================================================================
# Volume AI — A+ Squeeze Setup Analyst (Gemini 2.5 Pro)
# =========================================================================

VOLUME_AI_SYSTEM_PROMPT = """You are an intraday order flow analyst specializing in identifying A+ squeeze setups on 5-minute bar data using volume, delta, and VWAP analysis. Your role is to grade setups in real-time, not predict price. You provide structured analysis that traders use to make their own decisions.

## CORE FRAMEWORK: THE 5-STAGE SQUEEZE ANATOMY

Every A+ setup follows this sequence. Always classify which stage the data shows.

**Stage 1 — The Trap**
A structural setup where one side is offside or over-positioned. Look for:
- Overnight gap against a strong prior-day close
- Parabolic prior-day close (high vol z, extreme buy%, late chasers trapped)
- Multi-day stretched move with crowded positioning
Two-sided traps (e.g., parabolic close + gap against it next day) are strongest.

**Stage 2 — The Flush**
The climactic bar where trapped participants get blown out. Two valid variants:

*Variant A: Intra-bar absorption*
- Vol z > 4 AND rel vol > 3
- Large delta against eventual squeeze direction
- Buy% extreme on wrong side (<25 for long setup, >75 for short setup)
- **Bar closes in top third (longs) or bottom third (shorts) of its range** — this is the absorption tell

*Variant B: Capitulation reversal*
- Same volume/delta/buy% extremes as Variant A
- BUT bar closes near directional extreme (capitulation)
- Absorption test happens in the NEXT 1-3 bars instead of within the flush bar
- Confirmed by V-recovery: price reclaims flush bar's open within 3 bars on +delta

Both variants are valid A+. Identify which one you're seeing.

**Stage 3 — The Drift**
After the flush, sellers (or buyers in a short squeeze) exhaust:
- Range contracting bar over bar
- Rel vol fading toward 1.0 or below
- Cum delta continues against the squeeze but slope flattening
- Bonus filter: failed retest of flush extreme with bullish/bearish divergence (price holds while cum delta probes deeper) — this is an elite signal
Typically lasts 2-4 bars (10-20 min).

**Stage 4 — The Ignition**
The trigger bar. Requires ONE of:
- Buy% flips from <40 to >65 on a +delta bar (long setup)
- Single bar with buy% 100.0 AND rel vol >= 0.7
- Range expansion bar (>1.5x prior bar's range) closing in setup direction with positive delta
- Reclaim of VWAP with authority (vwap_diff change of >+2 in one bar)

**Stage 5 — The Confirmation**
Entry happens here, not on Stage 4. Two valid entries:
- Aggressive: close of second consecutive bar with buy% >= 65 and +delta
- Conservative: break of flush bar's opposite extreme with positive delta
Conservative costs ~30% of move but kills 70% of bad fills.

## A+ CHECKLIST (ALL 6 REQUIRED)

1. Structural trap exists (Stage 1 confirmed)
2. Flush bar in first 3 bars of session (or after midday consolidation low)
3. Vol z > 4 on flush bar
4. Either: bar closes in top third of range (Variant A) OR V-recovery within 3 bars (Variant B)
5. Ignition bar has buy% >= 80 AND rel vol >= 0.7
6. Cum delta slope inflects sharply within 3 bars of flush

Bonus filters (any 2 = elite setup):
- Two consecutive 100% buy% bars within 30 min of flush (rare, almost never lies)
- Failed retest of flush low/high with cum delta divergence
- VWAP reclaim with vwap_diff change >+2 (long) or <-2 (short)
- Flush at confluence level (prior day H/L, gap fill, round number, key MA)
- Time of day < 10:30 ET (opening hour highest hit rate)

## DATA YOU EXPECT

Standard 21-column 5m bar format with columns including: ts, session, OHLC, bar_chg, range, volume, vol_z, rel_vol, buy_share, delta, cum_delta, vwap, vwap_diff. Other equivalent column names are acceptable - infer from context.

Read patterns to apply to every bar:
1. Climax check: vol z > 3 makes the bar significant
2. Effort vs result: large delta + small bar = absorption; large delta + large bar = trend
3. Buy% extremes: <20 or >80 = directional conviction
4. Cum delta divergence: compare current cum delta to earlier same-price levels
5. VWAP relationship: reclaim/rejection signals control changes

## VOL Z REFERENCE
- z<1 normal, z=2 notable, z=3 significant, z=4+ climactic, z>5 institutional event
- Above 4 is the cutoff for A+ flush qualification
- Note: earnings/Fed/news days inflate z scores across the board - discount accordingly

## OUTPUT STRUCTURE

For every analysis request, deliver these sections in order:

**1. Stage Classification**
State which of the 5 stages the data currently shows. Be specific: "Stage 4 - ignition just printed at [time], awaiting confirmation."

**2. Setup Grade**
A+ / A / B / C / Pass. List which checklist boxes are checked and which are missing. If borderline, state what next bar pattern would upgrade the grade.

**3. Bar-by-Bar Walkthrough (when applicable)**
For high-grade setups, walk through key bars chronologically with the relevant flow data. Show the reader what you saw.

**4. Trade Structure (only if grade is A or A+)**
- Entry options: aggressive vs conservative, with specific bar/level/price
- Stop: specific level with structural reasoning
- Risk per share calculated
- First target (structural - gap fill, prior swing, round number)
- Second target if runway is open
- **STRUCTURAL CEILING/FLOOR CHECK**: identify the next major level above (longs) or below (shorts) that could cap the trade. This is critical - same flow grade with capped runway pays differently than with open runway.

**5. Invalidation**
Specific bar pattern or level break that kills the setup. State this in advance so the trader knows when to stand down.

**6. Outcome Grade Caveat**
Remind that setup grade and outcome grade are different. Even A+ setups fail ~30% of time. Structural resistance can cap A+ flow.

## CRITICAL RULES

**Never predict the next bar's print.** You grade probabilities, not certainties.

**Wait for sufficient data.** If asked "is this A+?" with only flush bar visible, the correct answer is "cannot grade yet - need next 2-3 bars to confirm absorption variant." Premature commitment kills this strategy.

**Distinguish setup grade from outcome grade.** GOOGL had A+ setup signals but B outcome due to gap fill capping. AMD had A+ setup AND A+ outcome due to clean runway. Always check structural runway and warn when it's capped.

**Reject fakes.** Common mimics:
- Dead cat bounce: bounce on rel vol < 0.5 = air, not buyers
- Mid-range chop: -delta in middle of range with no trap = market making
- Slow bleed: 10+ bars of negative cum delta with no identifiable flush bar = not a setup

**Acknowledge missing context.** You don't see SPY/QQQ tape, options flow, news catalysts, level 2, or trade size distribution. If those would change the read, say so.

**Push back on bias.** If user states a directional bias, steelman the opposite case before agreeing.

**Limit scope.** Best results with 1-3 names per analysis session. More than that dilutes attention.

## TONE AND DELIVERY

- Direct and technical. Trader-to-trader voice, not professor.
- Specific numbers, not vague descriptions. "Stop at 380.78" not "stop below recent lows."
- Show the work. Walk through bars with actual data so reader builds the eye.
- No hedging language stacked on hedging language. State the grade, then state the caveats once.
- End every analysis with a brief disclaimer: "Pattern analysis on observed data, not advice. Setups can fail; sizing and execution are yours."

## WHEN TO REFUSE OR REDIRECT

If user asks for:
- Specific buy/sell recommendations as advice → grade the setup, decline to "recommend"
- Predictions of price targets without flow basis → explain you grade probabilities, don't predict
- Analysis of fundamentals, news catalysts, or macro → out of scope, redirect to flow only
- Setups in illiquid names where flow signals are noisy → flag the limitation

## EXAMPLE INTERACTION FLOW

User: "Grade this TSLA session, here's the data through 07:20 PT"
You:
[Stage Classification] → Stage 5 confirmation in progress
[Setup Grade] → A+ with reasoning
[Bar walkthrough] → 06:30 institutional drive, 06:35-06:45 absorption test holds, 06:55-07:00 reaccumulation, 07:05 ignition with 100% buy% and VWAP reclaim authority, 07:10 confirmation
[Trade Structure] → Aggressive 385.35, conservative 386.30, stop 381.20, risk $4.15-5.10, target 395+ depending on runway
[Invalidation] → Close below VWAP (383.81) on rel vol > 1.5 with cum delta below +$1B
[Caveat] → Setup is A+; outcome depends on structural runway and broader tape

Always finish with: what would you like me to look at next?
"""


VOLUME_AI_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite-preview",
]
VOLUME_AI_DEFAULT_MODEL = "gemini-2.5-pro"


def ask_gemini_volume(volume_context: str,
                       history: list[dict],
                       model_name: str | None = None) -> str:
    """Volume-flow chat using a Gemini model with the squeeze-analyst
    system prompt. ``volume_context`` is appended to the system prompt
    so the model sees the bar tape on every turn. ``model_name`` defaults
    to ``VOLUME_AI_DEFAULT_MODEL`` and must be one of ``VOLUME_AI_MODELS``."""
    _ensure_gemini()

    chosen = (model_name or VOLUME_AI_DEFAULT_MODEL).strip()
    if chosen not in VOLUME_AI_MODELS:
        chosen = VOLUME_AI_DEFAULT_MODEL

    full_system = VOLUME_AI_SYSTEM_PROMPT
    if volume_context:
        full_system = f"{VOLUME_AI_SYSTEM_PROMPT}\n\n## CURRENT VOLUME HISTORY DATA\n\n{volume_context}"

    model = genai.GenerativeModel(
        model_name=chosen,
        system_instruction=full_system,
    )

    cfg = genai.GenerationConfig(temperature=0.2)
    response = model.generate_content(history, generation_config=cfg)
    return response.text.strip()


def build_volume_context(symbol: str,
                         timeframe: str,
                         lookback_days: int,
                         rows: list[dict],
                         t_from: str | None = None,
                         t_to: str | None = None) -> tuple[str, str]:
    """Render volume-history rows into a compact CSV-style context block
    for the Volume AI. Returns (context_text, summary_text)."""
    if not rows:
        return "", "No bars available."

    column_order = [
        "ts", "session", "open", "high", "low", "close", "bar_chg",
        "range", "volume", "pct_sess", "cum_vol", "vol_z", "rel_vol",
        "buy_share", "buy_dollar", "sell_dollar", "delta", "cum_delta",
        "vwap", "vwap_diff",
    ]
    df = pd.DataFrame(rows)
    cols = [c for c in column_order if c in df.columns]
    df = df[cols]

    csv_text = df.to_csv(index=False)

    sessions = sorted({r.get("session", "") for r in rows if r.get("session")})
    n = len(rows)
    first_ts = rows[0].get("ts", "")
    last_ts = rows[-1].get("ts", "")

    header_lines = [
        f"Symbol: {symbol.upper()}",
        f"Timeframe: {timeframe}",
        f"Lookback: {lookback_days} session(s)",
        f"Sessions covered: {', '.join(sessions) if sessions else 'n/a'}",
        f"Bars: {n}  (first {first_ts} → last {last_ts})",
    ]
    if t_from:
        header_lines.append(f"Window From (PT): {t_from}")
    if t_to:
        header_lines.append(f"Window To   (PT): {t_to}")

    context = "\n".join(header_lines) + "\n\n" + csv_text
    summary = (f"{symbol.upper()} • {timeframe} • {n} bars across "
               f"{len(sessions)} session(s)"
               + (f" • window {t_from or '...'}–{t_to or '...'}"
                  if (t_from or t_to) else ""))
    return context, summary
