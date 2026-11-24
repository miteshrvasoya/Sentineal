# Features (indicators) implemented so far

All indicators live in `backend/app/features/` and are **causal**: the value at bar *t* uses only bars <= *t*.
This is enforced by `tests/test_leakage.py` (prefix-invariance for every set, a deliberately leaky canary that must be caught, and a check that no honest feature predicts next-day return on a random walk).
Wilder smoothing (RSI, ATR, ADX) is seeded with the SMA of the first *n* values, as in the textbook and TradingView `ta.rma`.

| Set | Features | Formula / how to read |
|---|---|---|
| trend | returns (1/5/10/21/63d, simple+log) | C_t / C_{t-h} - 1 |
| | SMA/EMA 9/20/50/100/200 | EMA a = 2/(n+1). Price above a rising MA = uptrend |
| | MACD(12,26,9) | EMA12 - EMA26; histogram = MACD - signal. Crossovers show momentum shifts |
| | ADX/DI(14) | Trend strength (not direction). >25 usually means trending; +DI vs -DI gives direction |
| | Supertrend(10,3) | ATR bands that ratchet; direction flips when close crosses the band |
| | Parabolic SAR | Wilder trailing stop-and-reverse |
| | Ichimoku (tenkan 9, kijun 26, spans 26/52) | Chikou omitted (needs future bars) |
| | Aroon(25), Donchian(20), linreg slope/R2(20) | Time since extreme, channel, trend line fit |
| momentum | RSI(14), Connors RSI, Stoch(14,3), StochRSI, CCI, Williams %R, ROC, TSI | Overbought/oversold oscillators; none predict by themselves |
| | z-score(20), distance to 52w high/low | Mean-reversion stretch |
| volatility | ATR(14), Bollinger(20,2) %B/bandwidth, Keltner, TTM squeeze | Squeeze = Bollinger inside Keltner |
| | Realized vol: close-to-close, Parkinson, Garman-Klass, Yang-Zhang (annualised, 252d) + percentile | Range-based estimators use more of the bar than close-to-close |
| volume | OBV, A/D line, CMF(20), MFI(14), VW-MACD | Flow indicators |
| | VWAP (rolling 20; session VWAP for intraday), anchored VWAP (function; swing anchors in Phase 4) | sum(TP*V)/sum(V) |
| | RVOL, volume z-score (baseline excludes the current bar), up/down volume ratio | Unusual participation |

Not yet implemented: GARCH vol, India VIX features, volume profile, delivery %, market structure (Phases 4+).

## Phase 4: market structure, volume profile, patterns (`features/structure.py`, `features/patterns.py`)

**Point-in-time rule.** A swing at bar *i* needs *k* bars on both sides, so it is only *known* at bar *i+k* (`confirmed`). Every event (BOS/CHoCH/sweep/FVG/order block) is produced bar-by-bar using swings confirmed up to that bar. `resolved` (FVG filled / OB invalidated) deliberately describes what happened *after* formation. `tests/test_structure.py` and `tests/test_patterns.py` prove prefix-invariance.

| Concept | Definition used here |
|---|---|
| Swing high/low | `high[i] >` the k bars before and `>=` the k after (mirror for lows); consecutive same-kind swings are cleaned to the more extreme |
| HH/HL/LH/LL, trend | Compared with the previous swing of the same kind. Uptrend = HH+HL, downtrend = LH+LL, else range |
| BOS / CHoCH | Close beyond the last unbroken swing. With the trend = BOS, against it = CHoCH |
| Liquidity sweep | Wick beyond an unbroken swing, close back inside (once per swing) |
| FVG | Bullish: `low[i] > high[i-2]` (bearish mirror), gap >= 0.1 ATR. Resolved when price fully trades back through |
| Order block | Last opposite-colour candle (within 5 bars of the leg origin) before the leg that broke structure. Resolved by a close through the far side |
| Dealing range | Latest confirmed swing high/low. Premium/discount around the 50% equilibrium; "above/below range" when price is outside |
| Fibonacci | 0.236/0.382/0.5/0.618/0.786 retracements, 1.272/1.618 extensions of the latest confirmed leg |
| Pivots | Classic, Fibonacci, Camarilla from the last completed day (intraday), week and month |
| S/R zones | Complete-linkage clustering of the last 40 swing prices, zone width <= 1 ATR (DBSCAN chained swings into one giant zone, so it was replaced). Touches = cluster size |
| Volume profile | Each bar's volume spread uniformly across its high-low range into 48 bins over the window. POC = peak bin, value area = 70% around the POC, HVN/LVN = smoothed peaks/troughs |
| Wyckoff read | **Heuristic only**: range-bound + up/down volume ratio + position in range |

**Candlestick patterns** (doji, hammer, shooting star, engulfing, morning/evening star, harami, three soldiers/crows, inside/outside bar) are detected causally. Edge statistics use the stock's own history: forward 1/5/10-day return after the signal bar, hit rate versus the stock's base rate (binomial test), a Bonferroni correction across all pattern/horizon tests, and "insufficient sample" under 30 occurrences. Most patterns will show "no demonstrated edge"; that is the honest expected result.


## Phase 5: news and sentiment (`providers/*`, `data/news_ingest.py`, `nlp/*`, `features/sentiment.py`)

**Sources.** Always on (no key): Google News RSS, GDELT. With a key: Finnhub, Marketaux (100/day budget counter), Alpha Vantage (25/day), NewsAPI (100/day). Every call goes through the shared rate limiter and retry/backoff; one failing source never blocks the others; keys never appear in errors. *The request/response shapes were written from the public docs and tested against hand-made fixtures, not live APIs.*

**Dedupe.** Articles are keyed by the normalized URL (host lower-cased, `www.`, tracking params, fragment and trailing slash removed) and also matched by a normalized title hash, so the same story from another outlet merges and its tickers are unioned.

**Ticker resolution.** `data/aliases.csv` (hand-curated). Company names match case-insensitively; aliases of three characters or fewer (TCS, ITC, SBI, L&T) must match in exact upper case; no sub-word matches. Provider tags and the queried symbol are added.

**Scoring.** FinBERT (`ProsusAI/finbert`, local, optional extra `uv sync --extra nlp`, one-time download) with VADER as the offline fallback. Each article is scored at most once per model; a series always uses one model (the scales differ) and the UI says which. Signed score = P(positive) - P(negative).

**Daily features per ticker.** Mean and std of score, article count, news-volume z-score (vs the prior 30 days; spread floored at sqrt(mean) so a flat baseline still flags spikes) and spike flag (z > 2), smoothed positive/negative ratio, recency-weighted score (24h half-life, 7-day window), sentiment momentum (EMA5 - EMA20), and a price/sentiment divergence flag. Market-wide sentiment index = mean score across all stored news.

**Point-in-time.** Articles at or after the 15:30 IST close count on the next day. Windows only look backwards. A test proves that adding later news never changes earlier days.

**Lead/lag.** corr(sentiment_t, return_{t+lag}) for lags -5..+5 with Bonferroni-corrected p-values and a 30-day minimum. Expect most stocks to show nothing significant; sentiment is often a reaction to price.

Not yet built: earnings-date proximity (needs a results calendar, Phase 6) and social sentiment (optional, skipped).


## Phase 5A: LLM layer (`backend/app/llm/`)

See the in-app Guide (`/guide`, source `frontend/content/GUIDE.md`) for the full walkthrough. Summary:

- `base.py` provider interface + JSON validation with one repair retry; `providers/` Anthropic, Gemini, OpenAI, OpenAI-compatible (Groq, Ollama).
- `router.py` task routing from `config/llm.yaml` with fallback, cache (`cache.py`), budget hard stop and usage table (`usage.py`), guardrail regeneration.
- `guardrails.py` prompt-injection fencing and flags, no-advice post-check, number validator. `prompts/*.v1.md` versioned prompts. `context.py` context packs.
- `tasks/news_enrich.py` (event type, direction, materiality, horizon, new-vs-rehash, summary, tickers) and `tasks/sentiment_llm.py` (second opinion stored as model `llm:<model>`).
- `eval.py` + `data/llm_eval/headlines.jsonl`: accuracy, agreement, JSON validity, hallucinated-number and advice rates per provider/prompt version.
- Forward-only rule: LLM output on articles published before collection began is `valid_for_backtest = false`.


## Phase 6: fundamentals, risk, scorecard (`features/fundamentals.py`, `features/risk.py`, `models/scorecard.py`, `data/analysis.py`)

See the in-app Guide for the full walkthrough and the Phase 6 tour. Summary:

- **Fundamentals:** alias-based extraction from yfinance-shaped statements (missing = None, never 0); ratios (P/E, P/B, EV/EBITDA, ROE, ROCE, debt/equity, margins, growth, dividend yield, PEG); Piotroski F-score with per-criterion pass/fail/na; Altman Z (original formula; not applicable to financials); Graham number; two-stage DCF with sensitivity grid and editable assumptions; sector percentiles among stored same-sector peers (needs >= 3).
- **Risk:** CAGR, volatility, Sharpe, Sortino, Calmar, drawdown (max, longest, current), historical and parametric VaR/CVaR at 95/99%, beta/alpha/correlation vs Nifty 50, Kelly (display only), rolling volatility/Sharpe/beta/correlation (causal), correlation matrix. Risk-free rate is an editable assumption (default 7%). Vanishing denominators (std below 1e-12) are reported as undefined.
- **Scorecard:** six sub-scores (trend, momentum, volume/flow, volatility-as-stability, sentiment, valuation) from explicit rules voting +1/0/-1 with a reason; weights 25/20/15/10/15/15 renormalised over available parts; mild labels; no advice language (tested). Thresholds are rules of thumb, not validated.
- **API:** `POST /fundamentals/{symbol}/refresh`, `/fundamentals/{symbol}?r=&g1=&g2=&years=`, `/risk/{symbol}`, `/risk/correlation`, `/scorecard/{symbol}`, `/watchlist/summary`.


## Phase 7: statistical models and the evaluation harness (`app/models/`, `app/eval/`)

See the in-app Guide for the full walkthrough and the Phase 7 tour. Summary:

- **Interface:** `Model.fit(train)` / `predict(history, horizon) -> ModelView` (probabilities up/flat/down, quantiles 5-95, drivers, training window, version). Register in `models/registry.py`.
- **Models:** ARIMA (AIC order search), ETS (damped trend), GARCH / GJR-GARCH / EGARCH (Student-t, volatility cone), Monte Carlo GBM and 5-day block bootstrap (fan chart, level-touch probabilities), 3-state Gaussian HMM (forward-filtered regimes, regime table). Baselines: base_rate (naive), buy_hold, ma_rule.
- **Analysis tools:** day-of-week / month seasonality with step-down Welch tests and Bonferroni correction, Kruskal-Wallis omnibus, STL decomposition; Engle-Granger pairs scan with half-life, hedge ratio, split-half stability and Bonferroni correction.
- **Harness:** walk-forward (expanding or rolling) with refit schedule and non-overlapping outcomes; metrics: 3-class accuracy, up/down hit rate with binomial tests (vs 50% and vs naive), precision/recall, confusion matrix, Brier (multiclass and up-vs-not), calibration curve and ECE, MAE/RMSE/MASE, pinball loss, interval coverage, rank IC (overall and rolling), cumulative skill, rolling accuracy. Verdicts: `demonstrated edge` / `no demonstrated edge` / `insufficient sample` / `baseline`.
- **Robustness:** GARCH-family forecasts use filtered historical simulation (bounded tails; free-running t-shocks made EGARCH explode); every forecast is sanity-checked (finite, |log return| <= 2) and failures are counted; a failing model is skipped with a warning; > 5% failed forecasts forbids the edge verdict.
- **Registry and jobs:** every run saved as a new version (window, parameters, feature hash, metrics); background jobs with progress.
- **API:** `GET /models`, `POST /models/{symbol}/run`, `GET /jobs/{id}`, `GET /analysis/{symbol}`, `GET /models/{symbol}/evaluation`, `GET /models/{symbol}/registry`, `GET /analysis/seasonality/{symbol}`, `GET /analysis/pairs/{symbol}`.
- **Measured behaviour:** on 20 simulated no-signal series (5 models each) a "demonstrated edge" was declared for 1 of 20 series (5%); a strong planted next-day momentum is detected (skill 7-15%, p 1e-7 to 0.01) while the same momentum at a 5-day horizon is correctly not over-claimed (low power).

## Phase 8: machine learning, ensembles and the Model Lab (`app/models/ml*.py`, `deep.py`, `ensemble.py`, `app/eval/purged_cv.py`)

See the in-app Guide and the Phase 8 tour. Summary: LightGBM, XGBoost, random forest, logistic regression, news-only and price+news LightGBM, experimental GRU/LSTM (optional `deep` extra); shrinkage toward the base rate with a one-standard-error rule; SHAP, permutation importance and partial dependence; a causal ensemble; `GET /models/{symbol}/ablation`; the Model Lab page `/s/{symbol}/lab`; registry drift check.

## Phase 8A: AI analyst, model explainer, why-did-it-move, backtest reviewer (`app/llm/packs.py`, `app/llm/tasks/analyst.py`)

Endpoints: `POST /ai/analyst/{symbol}`, `POST /ai/explain-model/{symbol}`, `POST /ai/explain-move/{symbol}`, `POST /ai/backtest-review`. Frontend: `/s/{symbol}/analyst`, explain button on the Models page. Prompts: `analyst`, `explain_model`, `explain_move`, `backtest_review` (v1). Without a provider the endpoints return `available: false` plus the facts.

## Phase 9: backtester (`app/backtest/`)

`GET /backtest/strategies`, `POST /backtest/{symbol}`. Modules: `costs.py` (Indian delivery cost model), `strategies.py` (4 rules + parameter grids), `engine.py` (event loop), `stats.py` (metrics, stationary bootstrap, random-timing test), `service.py` (orchestration, held-out split, verdict, reviewer input). Frontend: `/s/{symbol}/backtest`.

## Phase 10: screener, breadth, scheduler, migrations (`app/screener/`, `app/scheduler.py`, `backend/alembic/`)

`GET /screener/fields`, `POST /screener/run`, `GET /market/breadth`, `GET /market/sectors`, `GET /scheduler/status`, `POST /scheduler/run/{job}`. Frontend: `/screener`, `/market`, `/learn`, scheduler card on `/settings`. Migrations: `make migrate`.

## Phase 10A: chat agent, NL screener, briefing, red flags, safety evaluation (`app/agent/`, `app/llm/tasks/assistant.py`, `app/llm/eval_agent.py`)

`POST /ai/chat`, `POST /ai/nl-screen`, `POST /ai/briefing`, `GET /ai/briefing/latest`, `GET /redflags/{symbol}`, `GET /redflags`, `GET /llm/eval/safety`. Frontend: `/chat`, `/briefing`, NL box on `/screener`, red flags on the AI analyst tab, safety panel on `/settings`. Prompts: `chat_agent`, `nl_screener`, `briefing` (v1). Corpora: `data/llm_eval/injections.jsonl`, `agent_questions.jsonl`.
