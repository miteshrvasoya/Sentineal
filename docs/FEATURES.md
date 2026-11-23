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
