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
- Phase 6 decisions: Finnhub basic financials and macro series (USDINR, Brent, US 10Y, India VIX features) are deferred (limited Indian coverage / not needed yet). Ratios, scores and the DCF are recomputed from stored raw statement inputs on every read. Charts for risk are small SVG components (Plotly arrives with the model pages).
- Database decision: Docker runs only PostgreSQL 16 (docker-compose.yml); backend and frontend run locally. The earlier backend/frontend Dockerfiles were removed because rebuilding images on every change was too slow. SQLite stays the zero-setup default. With a server database the app applies Alembic migrations at start-up; `make db-import` copies an existing SQLite file across. PostgreSQL support was verified against a real PostgreSQL 16 (migrations, price upserts, model runs and jobs from worker threads, scheduler, screener, backtest); the main test suite still runs on SQLite, with an opt-in `tests/test_postgres.py` (TEST_PG_URL).
- Phase 10A decisions: the chat agent is a bounded (5-step) structured tool loop over eight read-only tools; tool results and headlines are fenced as untrusted data; answers must cite tool-call ids and only use numbers from tool results or the user's message, else they are withheld. The natural-language screener reuses the screener validator plus a percent-scale check. Red flags are deterministic rules. The briefing is built from a Python fact list; the scheduler can write one daily. The safety evaluation (12 injections, 10 agent questions) is a live run against the configured model; automated tests use scripted models only. Found and fixed along the way: the screener's sentiment field read a key that did not exist.
- Phase 10 decisions: the screener works on a cached per-stock snapshot built from stored data (no network); missing data never matches; relative strength is a cross-sectional percentile over the stored universe; breadth and sector rotation are computed from the same rows. The scheduler is an in-process asyncio loop (off by default) with a table-backed run log, trading-day awareness, catch-up and bounded retries. Alembic added with a test that migrations match the models. Docker and CI already existed from earlier phases; compose and .env.example were extended. Deferred: Plotly charts, Angel One websocket, macro/delivery/FII-DII/PCR/earnings-date features, Finnhub basic financials.
- Phase 9 decisions: daily bars, long-only, one position; signal at close t fills at open t+1 with slippage; Indian delivery cost model with editable rates (defaults approximate, to be verified); optional held-out tail and an in-sample-only grid search; stationary block bootstrap p-value (Bonferroni over parameter sets) and a circular-shift random-timing test; the verdict is rule-based. Intraday, shorting, portfolios, walk-forward re-optimisation and persistence of runs are deferred.
- Phase 8A decisions: AI output must cite fact ids from a context pack and may only quote numbers in it (fractions may appear as percentages; windows in fact ids are quotable); advice, invented numbers or unknown citations trigger one regeneration, then the answer is withheld. AI output is display-only (never a feature). The backtest reviewer has deterministic red flags that run without an LLM; Phase 9 supplies the metrics automatically.
- Phase 8 decisions: ML models shrink their probabilities toward the training base rate, with the weight chosen on held-out days by a one-standard-error rule (temperature scaling was rejected: it pushed useless models below the base rate). Features are stationary and label windows purged; interpretation (SHAP, permutation, PDP) runs on held-out rows. Ensemble weights are causal and the ensemble counts in the Bonferroni correction. Deep models are optional (PyTorch extra) and experimental. Sentiment features come only from the non-LLM scorer. Triple-barrier labels and fractional differentiation are library-only for now.
- Phase 7 decisions: models predict a distribution of the h-day return (probabilities of up/flat/down plus quantiles); "flat" = |log return| < 0.25 x trailing-60d daily vol x sqrt(h) (causal). The verdict is a one-sided Diebold-Mariano test (Newey-West) on per-forecast Brier loss vs the base-rate baseline, Bonferroni-corrected over the models tried; default forecast stride = horizon so outcomes never overlap. HMM regime probabilities are FILTERED (forward pass only), never smoothed. GARCH/ARIMA reuse fitted parameters between refits (arch `fix`, statsmodels `smooth`). Jobs are an in-process asyncio manager backed by a `jobs` table. Purged K-fold and meta-labeling arrive with the ML models in Phase 8; macro features (USDINR, Brent, US10Y, India VIX) are still deferred.
- Tests never make live network calls, and never call a live LLM (scripted providers; SDK adapters tested with the SDKs' own response/exception types).
- LLM: official SDKs (anthropic, openai, google-genai) behind one `LLMProvider` interface; routing in `config/llm.yaml`; the LLM is a *second opinion*, never the default sentiment series; LLM output is forward-only for backtests; spend figures are estimates.
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

## Standing rule: every phase ships a guide section and an in-app tour
Each phase appends a section to `frontend/content/GUIDE.md` (symlinked at `docs/GUIDE.md`, rendered in-app at `/guide`): what's new, where to find it,
how to try it, how it works, the trading/ML ideas explained for an engineer who is not a trader, and how far to trust it. Also add a row to its "What's new" table.
It also ships an **interactive tour** in `frontend/lib/tours.ts`: add `data-tour="..."` markers to the new UI, define the steps (route, target, plain-language text), and set `isNew` on the newest tour only. The tour engine (`components/TourProvider.tsx`) spotlights the real elements, navigates between pages, and falls back to a centred card when an element has no data yet.

## Phase checklist
- [x] 1. Scaffold, config, DB, provider abstraction, rate limiter, Yahoo provider, calendar, price API, candlestick page
- [x] 2. Angel One provider, instrument master, backfill, data-quality report
- [x] 3. Indicator/feature library + tests, overlay UI
- [x] 4. Market structure, volume profile, Fibonacci, pivots, S/R, patterns with edge stats
- [x] 5. News providers, dedupe, ticker resolution, FinBERT, sentiment aggregates, page
- [x] 5A. LLM layer: provider interface, router, cache, budget, guardrails, news enrichment
- [x] 6. Fundamentals, risk, DCF, scorecard
- [x] 7. Model interface, statistical models, walk-forward, baselines
- [x] 8. ML models, SHAP, ablation, deep model, ensemble, Model Lab
- [x] 8A. Context packs, AI Analyst, model explainer, why-did-it-move, backtest reviewer
- [x] 9. Backtester with Indian cost model, bootstrap, UI
- [x] 10. Screener, scheduler, Learn, docs, Docker, CI
- [x] 10A. Chat agent, NL screener, briefing, red flags, LLM eval, injection tests

Phases 2 to 10A are large; each is built, tested and committed separately.
