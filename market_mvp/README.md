# Flow Scout MVP

A standalone, focused market interface containing only:

1. Free estimated GEX
2. Volume Screener
3. Volume Detail

It reuses the calculation engines in the parent Stock Scout project while
keeping the product UI and callback layer independent.

## Run locally

From the `STOCK SCOUT` directory:

```powershell
python -m market_mvp.main
```

Then open <http://127.0.0.1:8060>.

Optional environment settings:

```powershell
$env:MARKET_MVP_NAME = "YOUR BRAND"
$env:PORT = "8060"
python -m market_mvp.main
```

## MVP data warning

The current prototype uses the existing yfinance-backed engines. Before a
commercial launch, replace the provider behind `market_mvp/services.py` with a
feed whose agreement permits the intended display and derived-data use.
