# Stock Scout Free GEX & Market Analytics

<img width="2531" height="1169" alt="stock scout pic" src="https://github.com/user-attachments/assets/bed851da-e700-4a9b-8e71-22fe534252ec" />


**Explore gamma exposure without a $700/month analytics subscription.**

Stock Scout is a free, self-hosted Dash dashboard that calculates GEX locally
from currently available yfinance option-chain data. The core yfinance GEX,
volume, screening, and charting sections need no paid market-data key.

## Free GEX features

- Net, call, and put GEX by strike
- Positive and negative gamma walls
- Gamma-flip estimate and whole-chain scenario curve
- Strike × expiration and strike × time heatmaps
- 0DTE, 1DTE, and custom contract-DTE filters
- Intraday modeled GEX replay with real yfinance OHLC candles
- TradingView-style historical wall bands over price
- Expiration contribution and current wall tables
- Configurable strike window, strike bins, risk-free rate, and refresh interval

Stock Scout calculates Black–Scholes gamma from the public chain's underlying
price, strike, expiration, implied volatility, and open interest, then converts
it to estimated dollar gamma exposure per 1% underlying move. No paid GEX API
or Alpaca account is required for the **GEX Heatmap** tab.

## More market tools

- Abnormal-volume and intraday-spike scanners
- IV wall discovery using yfinance
- Sector and stock screening
- Options screening and risk tools
- TradingView views and alerts
- Optional Alpaca GEX comparison and paper/live trading integration

## Quick start

```powershell
git clone https://github.com/muratali016/stock-scout-gex.git
cd stock-scout-gex
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

Open `http://127.0.0.1:8050`, then choose **GEX Heatmap** to use the free
yfinance GEX tools immediately.

## Alpaca is optional

Public-data and yfinance tabs do not ask for Alpaca credentials. The dashboard
shows its secure activation dialog only when you:

- open **GEX Alpaca**;
- open **Trade**; or
- select **Alpaca API** in **IV Walls**.

The supplied key pair is validated with a read-only account request and stored
only in the local `.env` file, which Git ignores. Start with paper credentials.
Live credentials can submit real orders from the Trade tab after confirmation.

## What “free GEX” means

This project produces transparent estimates from currently accessible public
option-chain fields. It does **not** claim to reproduce a premium vendor's
proprietary feed, trade classification, historical chain archive, or dealer
inventory assumptions.

## Compared with premium GEX tools

I tested Stock Scout side by side with premium GEX platforms. In those
comparisons, the free calculations were very close on the levels that matter
most for trading: major positive and negative gamma walls, the overall gamma
regime, important support/resistance zones, and directional structure.

Exact GEX dollar values will not always match. Commercial tools can use
different feeds, snapshot times, expiration filters, smoothing, and dealer-sign
assumptions. The useful result is that this free model can identify much of the
same actionable gamma structure without requiring an expensive subscription.

yfinance does not provide historical intraday open-interest and implied-
volatility snapshots. Intraday GEX replay therefore holds the current chain's
OI/IV fixed and reprices gamma through historical underlying prices. It is a
modeled replay—not a record of true historical dealer positions. Expect values
to differ from commercial platforms because feeds, timestamps, smoothing,
contract filters, and sign conventions differ.

## Optional configuration

Copy `.env.example` to `.env` if you prefer manual configuration. MongoDB,
Gemini, Massive/Polygon, email, and Alpaca are optional; related features
degrade gracefully when they are not configured.

## Security and disclaimer

- Never commit `.env` or paste credentials into source files.
- Prefer Alpaca paper credentials while testing.
- Review changes with a secret scanner before publishing.
- This software is for research and education, not financial advice.
