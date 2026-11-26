# Learn: investing, step by step

Short lessons tied to things you can try in the app. **Lessons 1 to 8 are for complete beginners.** Lessons 9 onwards go deeper (written for engineers who like to know how the numbers are made). Nothing here is investment advice, and none of it replaces a SEBI-registered adviser if you want personal advice.

## 1. What is a share?

A share is a tiny slice of ownership in a company. If a company has 1 crore shares and you own 100, you own one hundred-thousandth of it. You make money in two ways: the **price** of your shares rises (and you sell for more than you paid), or the company pays you a share of its profit (a **dividend**). You lose money if the price falls below what you paid and you sell.

- **Try it:** open any stock in this app. The big number is what one share costs today.
- **Check yourself:** if you buy 10 shares at ₹500 and the price becomes ₹450, have you lost money? *On paper yes (₹500). It only becomes a real loss if you sell.*

## 2. Why do prices move?

Prices move because buyers and sellers disagree about what a company is worth. Good results or news push buyers up; bad news, fear, or even the whole market falling pulls prices down. In the **short term** (days to months) moods and news dominate, which is why it is so hard to predict. Over **many years**, prices tend to follow what the company actually earns.

- **Try it:** on a stock's page, switch the price history between 3 months and 5 years. Notice how a long view looks calmer.
- **Check yourself:** why can a good company's share price still fall? *Because the whole market can fall, or the price was already too high for the news.*

## 3. Short term versus long term

**Short term** (weeks to a few months) is about momentum and mood: faster, riskier, harder. **Long term** (years) is about owning good businesses at sensible prices and letting them grow. This app's *Find stocks* page has a tab for each, because they ask different questions. A stock can look weak short term and good long term, or the other way round.

- **Try it:** open *Find stocks* and compare the Short term and Long term tabs.
- **Check yourself:** which one needs you to understand the company's profits and debt? *Long term.*

## 4. Risk and diversification

Risk means the chance of losing money, or of the price swinging so much that you panic and sell at the worst time. The classic protection is **diversification**: spread your money over many companies in different industries, so one bad outcome does not sink you. Putting everything into one stock is the biggest beginner risk.

- **Try it:** *My investments* shows your portfolio check-up: it warns if one stock or one industry is too big a share.
- **Check yourself:** you own 4 bank shares. Are you diversified? *Not really: banks tend to fall together.*

## 5. SIP and index funds

A **SIP** puts a fixed amount in regularly (say ₹5,000 a month). You buy more when prices are low and less when high, and you stop trying to time the market. An **index fund** holds all the stocks in an index such as the Nifty 50, at very low cost, so one purchase spreads your money across many companies. Many beginners find this simple combination easier than picking individual stocks. It is one option among several, not a recommendation.

- **Try it:** the hover tips marked with dotted underlines explain SIP and index fund wherever they appear.
- **Check yourself:** what problem does a SIP reduce? *The risk of putting all your money in just before a fall.*

## 6. Reading this app

*My investments* is your dashboard: what you own, what it is worth, profit or loss, and a check-up. *Find stocks* gives ideas to research, ranked by visible rules. Click any stock for a **plain-English page**: price history, a short-term and a long-term look, warning signs and key numbers explained. Each ✓ is something good the stock passed; each ⚠ is something to look into. The **Simple / Advanced** switch at the top right reveals the professional charts and tools when you are ready.

- **Try it:** take the *Welcome* tour from the Tour button.
- **Check yourself:** what does a "Looks strong" label mean? *It passed most of the checklist. It is not a promise or a "buy" signal.*

## 7. Common beginner mistakes

Buying because a stock is "hot" or someone on social media said so. Putting everything in one stock. Investing money you may need soon (rent, fees, emergencies). Selling in panic after a fall. Checking prices every hour. Ignoring charges and taxes. Chasing a loss by buying more of the same stock. Having no plan for when you would sell.

- **Try it:** write down, before buying, why you are buying and what would make you sell.
- **Check yourself:** which of these is the most common? *Acting on a tip without understanding the company.*

## 8. Before you invest

Most people sensibly sort these first: an emergency fund (several months of expenses in a safe place), no expensive debt (credit cards), and money you will not need for at least 3 to 5 years if you invest in stocks. Decide your goal and time horizon, and how big a fall you could sit through without selling. Stock prices can fall 30% or more and take years to recover. For personal advice, speak to a SEBI-registered investment adviser.

- **Try it:** on *Find stocks*, set "Ups and downs I can handle" to match you honestly.
- **Check yourself:** should money for next month's rent go into stocks? *No.*


## 9. What a candlestick actually is

A candlestick is a **summary record** for one time bucket: open, high, low, close (OHLC), plus volume. The body spans open to close (green if it closed higher), the thin "wicks" reach the high and low. Think of it as the min, max, first and last value of a metric in a window, plus a counter.

- **Try it:** open any stock and switch the chart interval. Same data, different bucket size.
- **Check yourself:** what information is lost when you only keep OHLC? *Everything that happened inside the bucket, including the order of the high and the low.*

## 10. Returns, not prices

Prices are not comparable across stocks or time; **returns** are. A 5 rupee move means different things on a 50 rupee stock and a 5,000 rupee stock. Log returns add up over time, which makes the maths cleaner. Almost every model here works on returns for the same reason ML pipelines normalise inputs: the model should not care about the unit.

- **Try it:** on the Models tab, notice every forecast is a distribution of a *return*, not a price.
- **Check yourself:** a stock goes up 10% then down 10%. Is it back where it started? *No: 1.10 x 0.90 = 0.99, it is 1% lower.*

## 11. Volatility is the noise level

**Volatility** is the standard deviation of returns: how big the random-looking swings are. It is far more predictable than direction because quiet and turbulent periods **cluster** (this is what GARCH models). Position sizing, stop distances and risk numbers all scale with it.

- **Try it:** the Fundamentals and risk tab shows annualised volatility, and the Models tab has the volatility cone.
- **Check yourself:** why can volatility be forecast better than direction? *Because it is autocorrelated: today's turbulence predicts tomorrow's. Direction is close to a coin flip.*

## 12. Trend following versus mean reversion

Two opposite bets. **Trend following** assumes moves continue (buy strength). **Mean reversion** assumes extremes snap back (buy weakness). Markets switch between regimes where one works and the other fails, which is why a single rule rarely works for long.

- **Try it:** in the Backtest tab, run *Moving-average crossover* (trend) and *RSI mean reversion* on the same stock and compare.
- **Check yourself:** which kind of rule loses money in a choppy sideways market? *Trend following: it buys breakouts that reverse.*

## 13. Indicators are just features

RSI, MACD, moving averages and the rest are **feature engineering** on price and volume: smoothed or normalised summaries. None is magic. The Indicators phase proves each one only uses past data, the same leakage check you would run on any time-series feature.

- **Try it:** the Overview tab chart: add an indicator and read its description.
- **Check yourself:** can an indicator predict if it is computed with tomorrow's price? *Yes, perfectly, and uselessly. That is look-ahead leakage.*

## 14. Why most patterns are noise

Test enough patterns and some will "work" by luck. If you try 20 independent ideas at the 5% significance level, you expect one false hit. This is **multiple testing**, and the app corrects for it (Bonferroni) wherever it tries many things: models, patterns, seasonality, parameter searches.

- **Try it:** the Backtest tab with *search parameters* ticked: see the best in-sample setting and what happens on held-out data.
- **Check yourself:** a candlestick pattern wins 60% of 15 trades. Impressive? *No: 15 trades is a tiny sample, and 60% is within what coin flips produce about a quarter of the time.*

## 15. Walk-forward testing and leakage

To judge a forecasting model you must test it only on data it never saw, in time order: train on the past, predict the next block, then roll forward. Shuffling rows (the usual ML cross-validation) leaks the future into training because neighbouring days are correlated and labels overlap. The app also purges rows near the split boundary.

- **Try it:** run models with the walk-forward test, then open the Model Lab.
- **Check yourself:** why is random k-fold wrong for time series? *The future leaks into the training folds, so the score is optimistic.*

## 16. The baseline you must beat

A model's accuracy means nothing alone: "55% right" sounds good until you learn that always guessing "up" is right 54% of the time. QuantLens always compares against simple baselines (base rate, buy and hold, a moving-average rule), and calls an edge only if the difference survives a significance test.

- **Try it:** the Models leaderboard: look at the "naive" hit rate beside each model.
- **Check yourself:** a model scores 53%, the baseline 52.5%. Is that an edge? *Almost certainly not: the gap is far smaller than the noise.*

## 17. Costs eat small edges

Every trade pays brokerage, STT, stamp duty, exchange and SEBI fees, GST and loses a little to **slippage**. A rule that earns 0.2% per trade gross and trades often can be a net loser. The backtester charges Indian delivery costs on every fill.

- **Try it:** run a backtest with *Indian delivery costs*, then with *None*, and compare the "What costs took" panel.
- **Check yourself:** why do high-frequency rules suffer most? *The fixed cost is paid on every round trip, so more trades means more drag.*

## 18. Risk is more than volatility

**Max drawdown** (worst peak-to-trough fall) is what you actually feel. **Sharpe** is return per unit of volatility: a signal-to-noise ratio. **Sortino** only counts downside moves. A strategy with a great return and a 60% drawdown is one most people abandon at the worst moment.

- **Try it:** the Backtest drawdown chart.
- **Check yourself:** you lose 50%. What gain do you need to break even? *100%.*

## 19. Reading the verdicts

Across the app you will see verdicts like **"no demonstrated edge"**. That is the expected, honest result for most ideas. It does not mean the idea is false, only that the data at hand cannot distinguish it from luck. "Demonstrated edge" or "survives these tests" is necessary, not sufficient, evidence.

- **Try it:** run any model or backtest and read the reasons under the verdict.
- **Check yourself:** a backtest says "survives these tests". Should you trade it? *Not on that alone: markets change, and costs, liquidity and behaviour in a real account all differ from a test.*

## 20. What AI can and cannot do here

The AI features **narrate computed facts**; they do not compute or predict. Every claim must cite a fact, numbers must come from the facts, and advice is blocked. Treat AI text as a readable summary of things you can verify, never as a source of facts.

- **Try it:** the AI analyst tab: open "The facts the AI was given" and hover a citation.
- **Check yourself:** why show the AI's input facts? *So you can check its claims against what it was actually given.*
