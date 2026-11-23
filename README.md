# QuantLens

Personal, educational stock **analysis** platform for NSE/BSE. Not investment advice. See `docs/PLAN.md` for the architecture and phase checklist.

## Quick start (no API keys needed)
```bash
make install
make dev        # backend http://127.0.0.1:8000/docs, frontend http://127.0.0.1:3000
make seed       # optional: backfill 5y daily bars for the default watchlist
make test
```
Copy `.env.example` to `.env` to add keys later. Without keys the app uses Yahoo Finance (unofficial, can break).

## Status
Phase 1 done: provider abstraction (rate limiter, retry/backoff, fallback router, health), Yahoo provider, NSE calendar, price/quote/watchlist/search API, candlestick page. Later phases are tracked in `docs/PLAN.md`.

## Known limits (Phase 1)
- NSE holiday table covers 2025 and 2026 only and must be refreshed yearly.
- Intraday history from Yahoo is limited (1m: 7 days, 5m/15m: 60 days).
- Index quotes (NIFTY / VIX) in the top bar show `n/a` if Yahoo is unreachable.
