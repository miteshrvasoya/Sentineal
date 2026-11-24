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

## Database in Docker (optional)
```bash
cp .env.example .env   # DATABASE_URL points at the Docker PostgreSQL
make db-up             # starts only the database; data persists in a volume
make dev               # backend and frontend run locally
make db-import         # optional: copy an existing SQLite file into PostgreSQL
```
Leave `DATABASE_URL` unset (or commented out) to use the local SQLite file with no Docker. `make db-down` stops the database, `make db-reset` deletes its data.

## Guide and tours
Open **Guide** in the app's top bar (or read `docs/GUIDE.md`) for a plain-language walkthrough of every feature, written for engineers who are not traders. The **Tour** menu replays an interactive, spotlight-style tour of the real screens for every phase. Each new phase adds a guide section and a tour.

## Status
All planned phases (1 to 10A) are built: data providers with fallback, indicators, market structure, news and sentiment, fundamentals and risk, statistical and machine-learning forecast models with honest walk-forward evaluation, a backtester with Indian costs, a screener with breadth and sector rotation, a scheduler, Alembic migrations, optional AI features (analyst, explainers, chat, plain-English screens, briefing) with guardrails, and a Learn section. Backend tests: 400+ passing (`make test`). Deferred extras are in `docs/PLAN.md`.

Optional extras: `make migrate` (Alembic), `make tour-check` (needs Playwright), a PostgreSQL database in Docker (`make db-up`; only the database runs in Docker, the backend and frontend run locally, and the SQLite default still works with no Docker at all), `SCHEDULER_ENABLED=true` in `.env` for background jobs. AI features need an API key in `.env`; everything else works without one. No live LLM, Yahoo or news provider was reachable during development, so all tests use synthetic data and scripted models.

## Known limits (Phase 1)
- NSE holiday table covers 2025 and 2026 only and must be refreshed yearly.
- Intraday history from Yahoo is limited (1m: 7 days, 5m/15m: 60 days).
- Index quotes (NIFTY / VIX) in the top bar show `n/a` if Yahoo is unreachable.
