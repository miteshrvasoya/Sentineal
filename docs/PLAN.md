# QuantLens: Plan

Personal, educational stock **analysis** platform for NSE/BSE. Not investment advice. No order placement code, ever.

## Decisions (made without asking, per the brief)
- Repo root is the QuantLens root (`backend/`, `frontend/`, `data/`, `docs/`).
- Backend: Python 3.11+, FastAPI, SQLAlchemy 2 (sync sessions, SQLite default), `uv` for deps. Provider I/O is async; blocking SDKs (yfinance) run via `asyncio.to_thread`. DB calls are sync (fast on SQLite; fine for a single-user localhost app).
- Timestamps are stored as **UTC epoch seconds** (integer). Calendar logic uses Asia/Kolkata. The API returns epoch seconds; the frontend shifts to IST for display.
- Both raw `close` and `adj_close` are stored; `adjusted=true` rescales OHL by `adj_close/close`.
- NSE holidays are a curated static table (`app/data/calendar.py`) that must be refreshed yearly. Unknown years fall back to weekday-only and say so.
- Symbols: bare NSE symbols (`RELIANCE`). Index aliases: `NIFTY 50`, `NIFTY BANK`, `INDIA VIX`. Yahoo mapping lives in the Yahoo provider.
- Frontend: Next.js (App Router, TS), Tailwind, TanStack Query, lightweight-charts. Plotly arrives with the analytical pages.
- Tests never make live network calls.
- Angel One uses the documented SmartAPI REST endpoints directly over `httpx` (async, mockable) instead of the sync `smartapi-python` SDK. Login/candle endpoints, field names and the index tokens are from memory of the public docs and are **unverified against the live API** (no credentials here). Websocket live ticks are deferred.
- Angel One candles are raw (unadjusted): `adj_close == close`. Mixing sources in one series is flagged by the data-quality report (`mixed_sources`).

## Architecture
```
Next.js UI ──HTTP──> FastAPI routes ──> services (prices) ──> ProviderRouter ──> [Yahoo | (Angel One) | (NSE)]
                                            │                      │
                                            └──> SQLite/Postgres   └──> provider_health table
```
- `ProviderRouter` tries providers in priority order, validates frames (non-empty, monotonic, sane OHLC), falls back on failure and records health.
- One shared async `RateLimiter` (token bucket) + `retry_with_backoff` (jitter) wrap every outbound call.

## Data model (SQLAlchemy)
`symbols`, `watchlist`, `prices(symbol, interval, ts, o, h, l, c, adj_close, volume, source)` PK(symbol, interval, ts), `provider_health`.
Later phases add: articles, article_scores, features, model_registry, jobs, backtests, llm_usage, llm_cache.

## Phase checklist
- [x] 1. Scaffold, config, DB, provider abstraction, rate limiter, Yahoo provider, calendar, price API, candlestick page
- [x] 2. Angel One provider, instrument master, backfill, data-quality report
- [ ] 3. Indicator/feature library + tests, overlay UI
- [ ] 4. Market structure, volume profile, Fibonacci, pivots, S/R, patterns with edge stats
- [ ] 5. News providers, dedupe, ticker resolution, FinBERT, sentiment aggregates, page
- [ ] 5A. LLM layer: provider interface, router, cache, budget, guardrails, news enrichment
- [ ] 6. Fundamentals, risk, DCF, scorecard
- [ ] 7. Model interface, statistical models, walk-forward, baselines
- [ ] 8. ML models, SHAP, ablation, deep model, ensemble, Model Lab
- [ ] 8A. Context packs, AI Analyst, model explainer, why-did-it-move, backtest reviewer
- [ ] 9. Backtester with Indian cost model, bootstrap, UI
- [ ] 10. Screener, scheduler, Learn, docs, Docker, CI
- [ ] 10A. Chat agent, NL screener, briefing, red flags, LLM eval, injection tests

Phases 2 to 10A are large; each is built, tested and committed separately.
