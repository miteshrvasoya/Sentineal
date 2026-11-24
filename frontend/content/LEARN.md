# Learn: market ideas for engineers

Short lessons on the ideas QuantLens uses, each tied to something you can try in the app. They are written for someone who thinks in systems, data and tests rather than trading. Nothing here is investment advice.

## 1. What a candlestick actually is

A candlestick is a **summary record** for one time bucket: open, high, low, close (OHLC), plus volume. The body spans open to close (green if it closed higher), the thin "wicks" reach the high and low. Think of it as the min, max, first and last value of a metric in a window, plus a counter.

- **Try it:** open any stock and switch the chart interval. Same data, different bucket size.
- **Check yourself:** what information is lost when you only keep OHLC? *Everything that happened inside the bucket, including the order of the high and the low.*

## 2. Returns, not prices

Prices are not comparable across stocks or time; **returns** are. A 5 rupee move means different things on a 50 rupee stock and a 5,000 rupee stock. Log returns add up over time, which makes the maths cleaner. Almost every model here works on returns for the same reason ML pipelines normalise inputs: the model should not care about the unit.

- **Try it:** on the Models tab, notice every forecast is a distribution of a *return*, not a price.
- **Check yourself:** a stock goes up 10% then down 10%. Is it back where it started? *No: 1.10 x 0.90 = 0.99, it is 1% lower.*

## 3. Volatility is the noise level

**Volatility** is the standard deviation of returns: how big the random-looking swings are. It is far more predictable than direction because quiet and turbulent periods **cluster** (this is what GARCH models). Position sizing, stop distances and risk numbers all scale with it.

- **Try it:** the Fundamentals and risk tab shows annualised volatility, and the Models tab has the volatility cone.
- **Check yourself:** why can volatility be forecast better than direction? *Because it is autocorrelated: today's turbulence predicts tomorrow's. Direction is close to a coin flip.*

## 4. Trend following versus mean reversion

Two opposite bets. **Trend following** assumes moves continue (buy strength). **Mean reversion** assumes extremes snap back (buy weakness). Markets switch between regimes where one works and the other fails, which is why a single rule rarely works for long.

- **Try it:** in the Backtest tab, run *Moving-average crossover* (trend) and *RSI mean reversion* on the same stock and compare.
- **Check yourself:** which kind of rule loses money in a choppy sideways market? *Trend following: it buys breakouts that reverse.*

## 5. Indicators are just features

RSI, MACD, moving averages and the rest are **feature engineering** on price and volume: smoothed or normalised summaries. None is magic. The Indicators phase proves each one only uses past data, the same leakage check you would run on any time-series feature.

- **Try it:** the Overview tab chart: add an indicator and read its description.
- **Check yourself:** can an indicator predict if it is computed with tomorrow's price? *Yes, perfectly, and uselessly. That is look-ahead leakage.*

## 6. Why most patterns are noise

Test enough patterns and some will "work" by luck. If you try 20 independent ideas at the 5% significance level, you expect one false hit. This is **multiple testing**, and the app corrects for it (Bonferroni) wherever it tries many things: models, patterns, seasonality, parameter searches.

- **Try it:** the Backtest tab with *search parameters* ticked: see the best in-sample setting and what happens on held-out data.
- **Check yourself:** a candlestick pattern wins 60% of 15 trades. Impressive? *No: 15 trades is a tiny sample, and 60% is within what coin flips produce about a quarter of the time.*

## 7. Walk-forward testing and leakage

To judge a forecasting model you must test it only on data it never saw, in time order: train on the past, predict the next block, then roll forward. Shuffling rows (the usual ML cross-validation) leaks the future into training because neighbouring days are correlated and labels overlap. The app also purges rows near the split boundary.

- **Try it:** run models with the walk-forward test, then open the Model Lab.
- **Check yourself:** why is random k-fold wrong for time series? *The future leaks into the training folds, so the score is optimistic.*

## 8. The baseline you must beat

A model's accuracy means nothing alone: "55% right" sounds good until you learn that always guessing "up" is right 54% of the time. QuantLens always compares against simple baselines (base rate, buy and hold, a moving-average rule), and calls an edge only if the difference survives a significance test.

- **Try it:** the Models leaderboard: look at the "naive" hit rate beside each model.
- **Check yourself:** a model scores 53%, the baseline 52.5%. Is that an edge? *Almost certainly not: the gap is far smaller than the noise.*

## 9. Costs eat small edges

Every trade pays brokerage, STT, stamp duty, exchange and SEBI fees, GST and loses a little to **slippage**. A rule that earns 0.2% per trade gross and trades often can be a net loser. The backtester charges Indian delivery costs on every fill.

- **Try it:** run a backtest with *Indian delivery costs*, then with *None*, and compare the "What costs took" panel.
- **Check yourself:** why do high-frequency rules suffer most? *The fixed cost is paid on every round trip, so more trades means more drag.*

## 10. Risk is more than volatility

**Max drawdown** (worst peak-to-trough fall) is what you actually feel. **Sharpe** is return per unit of volatility: a signal-to-noise ratio. **Sortino** only counts downside moves. A strategy with a great return and a 60% drawdown is one most people abandon at the worst moment.

- **Try it:** the Backtest drawdown chart.
- **Check yourself:** you lose 50%. What gain do you need to break even? *100%.*

## 11. Reading the verdicts

Across the app you will see verdicts like **"no demonstrated edge"**. That is the expected, honest result for most ideas. It does not mean the idea is false, only that the data at hand cannot distinguish it from luck. "Demonstrated edge" or "survives these tests" is necessary, not sufficient, evidence.

- **Try it:** run any model or backtest and read the reasons under the verdict.
- **Check yourself:** a backtest says "survives these tests". Should you trade it? *Not on that alone: markets change, and costs, liquidity and behaviour in a real account all differ from a test.*

## 12. What AI can and cannot do here

The AI features **narrate computed facts**; they do not compute or predict. Every claim must cite a fact, numbers must come from the facts, and advice is blocked. Treat AI text as a readable summary of things you can verify, never as a source of facts.

- **Try it:** the AI analyst tab: open "The facts the AI was given" and hover a citation.
- **Check yourself:** why show the AI's input facts? *So you can check its claims against what it was actually given.*
