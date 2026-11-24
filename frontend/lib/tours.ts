// Interactive product tours. One per phase, newest first. Each step highlights a real element on a real page
// (elements carry `data-tour="<target>"`). If an element is not on screen (for example no data yet) the tour shows
// the explanation in the centre of the screen instead, so it never breaks.
//
// RULE FOR FUTURE PHASES: add a tour here, add data-tour attributes to the new UI, flip `isNew` on the newest
// tour only, and add a matching section to content/GUIDE.md.

export type Step = {
  /** Page to show. `{symbol}` is replaced by the stock you are looking at (default RELIANCE). */
  route?: string;
  /** Value of the data-tour attribute to spotlight. Omit for a centred card. */
  target?: string;
  title: string;
  body: string; // blank line = new paragraph
  note?: string; // shown when the target is not on screen
};

export type TourDef = { id: string; phase: string; title: string; blurb: string; isNew?: boolean; steps: Step[] };

const OV = "/s/{symbol}";
const ST = "/s/{symbol}/structure";
const NW = "/s/{symbol}/news";
const FD = "/s/{symbol}/fundamentals";
const MD = "/s/{symbol}/models";
const LB = "/s/{symbol}/lab";
const AN = "/s/{symbol}/analyst";
const BT = "/s/{symbol}/backtest";


export const TOURS: TourDef[] = [
  {
    id: "phase-9", phase: "Phase 9", title: "The backtester, with Indian costs and a luck test", isNew: true,
    blurb: "Replay a trading rule on history with real-world costs, then find out whether the result could just be luck.",
    steps: [
      { title: "Testing a rule against history, honestly", body: "A backtest replays a rule (for example 'buy when the fast average crosses above the slow one') on past prices and reports what it would have earned.\n\nIt is easy to make a backtest look great and mean nothing. This one charges Indian trading costs, never trades on a price it could not have known, keeps the most recent data hidden while choosing parameters, and tests whether the result could be luck." },
      { route: BT, target: "bt-controls", title: "Choose a rule and the rules of the game", body: "Four classic rules: moving-average crossover, RSI mean reversion, channel breakout and momentum. Set their parameters, the cost model, starting capital and an optional stop-loss.\n\n'Held-out' keeps the last 20 to 40% of history out of parameter selection. 'Search parameters' tries every combination on the earlier part and picks the best, which shows how easily a lucky setting looks brilliant." },
      { route: BT, target: "bt-verdict", title: "The verdict comes first", body: "A plain-language answer to 'does this survive the tests?', with reasons: too few trades, no held-out period, Sharpe not distinguishable from luck, or failing to beat simply holding the stock after costs.\n\nMost rules on most stocks will say 'no demonstrated edge'. That is the honest, normal outcome.", note: "Appears after you click Run backtest." },
      { route: BT, target: "bt-equity", title: "Strategy vs buy and hold", body: "Both start at 100. The strategy line is after costs and slippage. If it ends below the dashed buy-and-hold line, the rule would have been worse than doing nothing.", note: "Appears after you click Run backtest." },
      { route: BT, target: "bt-costs", title: "What costs took", body: "STT, stamp duty, exchange and SEBI charges, GST, the depository fee and slippage, itemised. Frequent trading pays these on every round trip, so a rule that looks fine gross can lose money net. Rates are editable defaults: check your broker's current rate card.", note: "Appears after you click Run backtest." },
      { route: BT, target: "bt-luck", title: "Skill or luck?", body: "Two tests. The bootstrap reshuffles the strategy's daily returns in blocks thousands of times to show the range of Sharpe ratios luck could produce, and the chance a zero-skill strategy does as well.\n\nThe random-timing test keeps the same trades and time in the market but randomises when they happen. If real timing only ranks around the 50th percentile, it added nothing.", note: "Appears after you click Run backtest." },
      { route: BT, target: "bt-heldout", title: "In-sample vs held-out", body: "Parameters are chosen on the earlier data only. This table compares that stretch with the held-out stretch the choice never saw. A big drop in Sharpe is overfitting: the rule memorised the past.", note: "Appears after a run with a held-out period." },
      { route: BT, target: "bt-search", title: "The price of searching", body: "Try 12 settings on random data and the best one will look good by luck. So when you search, the p-value is multiplied by the number of combinations tried.", note: "Appears after a run with 'search parameters' ticked." },
      { route: BT, target: "bt-review", title: "AI review (optional)", body: "Send the result to the AI reviewer from Phase 8A. The automatic red flags always show; with an API key it also explains how far to trust the result, citing the numbers.", note: "Appears after you click Run backtest." },
      { title: "That is Phase 9", body: "Takeaway: a backtest is evidence about the past. It becomes evidence about the future only if it survives costs, held-out data and a luck test. Next: the screener, scheduler and the rest of the platform." },
    ],
  },
  {
    id: "phase-8a", phase: "Phase 8A", title: "The AI analyst, with guardrails",
    blurb: "An optional AI that explains the computed facts in plain language, cites its evidence, and is blocked from inventing numbers or giving advice.",
    steps: [
      { title: "AI that narrates, never calculates", body: "Phase 8A adds four AI helpers: an analyst report, a model explainer, a 'why did it move?' tool and a backtest reviewer.\n\nThe rule behind all of them: Python computes every number, the AI only describes them. Each answer must cite the facts it uses, may only quote numbers that exist in those facts, and is thrown away if it gives advice. They are optional: with no API key everything else still works." },
      { route: AN, target: "ai-analyst", title: "The AI analyst", body: "One button writes a report from the stored facts: price, risk, scorecard, fundamentals, news and model verdicts. It lists points in favour, points against, where signals disagree and what data is missing.\n\nThe 'stance' is the weight of evidence in the facts, not a recommendation. Grey chips under each point are citations; hover one to see the value it refers to." },
      { route: AN, target: "ai-facts", title: "See exactly what the AI saw", body: "Open this to see the full list of facts handed to the AI. If something it says is not in this list, the safety check rejects the answer. Think of it as the AI's only input file.", note: "Appears after you click 'Write the report' (works without an API key: it then shows only the facts)." },
      { route: AN, target: "ai-move", title: "Why did it move?", body: "Pick a period (or leave it empty for the last five days). The software computes the stock's move and the index's move, collects stored news, and the AI proposes explanations that cite specific articles.\n\nIt can show association, never proof. If the market moved the same amount, it says the move was probably market-wide. News text is fenced as untrusted data, and articles that contain instruction-like text are flagged." },
      { route: AN, target: "ai-review", title: "Backtest reviewer", body: "A sceptical reviewer for backtest results. Automatic red flags (few trades, no costs, no out-of-sample data, too good to be true) always run, even without an LLM. The AI then explains how far the result can be trusted. Try the deliberately bad example." },
      { route: MD, target: "ai-explain-model", title: "Explain a model in words", body: "On the Models page, under 'Why does the model say that?', this button turns SHAP drivers and the walk-forward verdict into plain language, including the honest 'no demonstrated edge' message when that is the result.", note: "Appears after running an ML model such as lgbm." },
      { title: "That is Phase 8A", body: "Takeaway: treat AI text as a readable summary of facts you can check, never as a source of facts. Next: the backtester with Indian trading costs (Phase 9)." },
    ],
  },
  {
    id: "phase-8", phase: "Phase 8", title: "Machine learning, ensembles and the Model Lab",
    blurb: "Gradient-boosted and deep models, explained with SHAP, blended into an ensemble, and held to the same honest test.",
    steps: [
      { title: "More powerful models, same strict judge", body: "Phase 8 adds machine-learning models (LightGBM, XGBoost, random forest, logistic regression, an experimental GRU/LSTM), an ensemble that blends your picks, and a Model Lab for dissecting results.\n\nMore powerful models overfit more easily. So each one is shrunk toward the plain base rate unless it proves skill on days it never trained on. Expect many to end up at 'no demonstrated edge'." },
      { route: MD, target: "model-groups", title: "Models grouped by family", body: "Statistical, machine learning and deep models. Greyed, struck-through ones are unavailable here (hover to see why, for example PyTorch not installed). 'news' marks models needing stored articles; 'pooled' marks ones that also train on other stocks." },
      { route: MD, target: "interpret", title: "Why does the model say that?", body: "SHAP breaks one prediction into per-feature pushes: green toward up, red toward down. Permutation importance shuffles a feature on held-out days and measures how much worse the model gets. Partial dependence shows how P(up) moves as one feature varies.\n\nThese explain what the model learned, not what moves the market. 'Trust in model' shows how much of its output survived blending with the base rate.", note: "Appears after running an ML model (e.g. lgbm)." },
      { route: MD, target: "ablation", title: "Does news add anything?", body: "Three models differing only in inputs: price only, news only, price plus news. A paired test checks whether adding news improves forecasts beyond chance. News history is usually short, and the panel says so.", note: "Needs lgbm, lgbm_sentiment and lgbm_combined run together with stored news." },
      { route: LB, target: "lab-leaderboard", title: "The Model Lab leaderboard", body: "Every metric in one sortable table. Click headers to sort, hover for definitions, click a model name to add or remove it from the charts below.", note: "Needs a walk-forward run at the chosen horizon." },
      { route: LB, target: "lab-equity", title: "Equity vs always-long", body: "A diagnostic: go long when the model says up, otherwise stay in cash. The dashed line is simply holding. There are no trading costs here; the real backtester arrives in Phase 9." },
      { route: LB, target: "lab-decay", title: "Skill decay", body: "Cumulative advantage over the baseline. Rising then flattening means an edge that faded. Ending near zero means there never was one." },
      { route: LB, target: "lab-calibration", title: "Calibration overlay", body: "Do stated probabilities match reality? Curves on the diagonal are honest." },
      { route: LB, target: "lab-registry", title: "Registry and drift", body: "Every run is stored as a version with its data window and feature hash. A drift check flags models whose skill has fallen versus earlier versions." },
      { title: "That is Phase 8", body: "Takeaway: complexity buys nothing unless it survives the out-of-sample test. Next: an AI analyst layer, then the backtester with Indian trading costs." },
    ],
  },
  {
    id: "phase-7", phase: "Phase 7", title: "Forecast models, tested honestly",
    blurb: "Statistical models, measured against simple baselines out of sample. Most will say: no demonstrated edge.",
    steps: [
      { title: "Forecasting without fooling ourselves", body: "Phase 7 adds forecasting models: ARIMA, volatility (GARCH), Monte Carlo, and a regime detector.\n\nBut the real feature is the test. Every model is judged on forecasts it made BEFORE seeing the outcome, against simple baselines. The honest, expected result for most models on most stocks is 'no demonstrated edge'. This page is built to say that clearly instead of flattering the models." },
      { route: MD, target: "models-controls", title: "Pick models and a horizon", body: "Choose which models to run and how far ahead (the horizon): 1 day up to 3 months.\n\nThree baselines always run alongside: 'base rate' (just the historical share of up and down moves), 'buy and hold' (always up) and a moving-average rule. They are the yardstick: a model that cannot beat them is not adding anything.\n\nOptionally type price levels to find out how likely the simulation says it is to touch them." },
      { route: MD, target: "run-models", title: "Run, with a progress bar", body: "Training and testing can take from seconds to a couple of minutes, so it runs as a background job and you can watch the progress bar.\n\nThe walk-forward test fits each model on the past only, forecasts forward, records what really happened, then rolls forward in time and repeats. Nothing from the future is ever visible when a forecast is made.", note: "Click Run models after choosing a stock with at least ~300 daily bars (run make seed)." },
      { route: MD, target: "consensus", title: "The consensus panel", body: "Every model's vote side by side. When models disagree, the panel says so and labels the result 'low conviction' instead of hiding it.\n\n'Edge' counts only models that beat the baseline with statistical significance after correcting for how many models you tried. If none did, the headline says the evidence is weak.", note: "Appears after your first model run." },
      { route: MD, target: "model-table", title: "Reading a model row", body: "The coloured bar is the model's probability for up (green), flat (grey) and down (red). 'Flat' means a move smaller than a quarter of normal volatility.\n\nThe 90% range is where the model expects the return to land 9 times out of 10. Hit rate vs naive compares the model's up/down calls with simply guessing the commoner direction.\n\nClick a row to see the model's key inputs and what data it trained on.", note: "Appears after your first model run." },
      { route: MD, target: "fan", title: "Fan chart (Monte Carlo)", body: "Thousands of simulated price paths from recent behaviour. The bands show where the middle 50% and 90% of them end up over time.\n\nIt shows uncertainty, not direction. The amber lines are price levels you asked about, with the simulated chance of touching each.", note: "Needs a Monte Carlo model (mc_gbm or mc_bootstrap) in your run." },
      { route: MD, target: "volcone", title: "Volatility cone", body: "Volatility (how violently price moves) is far more predictable than direction, because turbulent periods cluster together.\n\nThe red line is the GARCH model's forecast. The grey bands are the range that real volatility has covered over about three years. A forecast above the band means the model expects unusually rough conditions.", note: "Needs a GARCH-family model in your run." },
      { route: MD, target: "regime", title: "Market regime", body: "A hidden Markov model learns that the market switches between hidden states, each with its own typical return and volatility, and tells you how likely each state is right now.\n\nThe coloured strip shows the most likely state for each past day, computed with a forward pass only, so no day's colour uses information from after that day.", note: "Needs hmm_regime in your run." },
      { route: MD, target: "leaderboard", title: "Walk-forward leaderboard", body: "The scorecard that matters. Brier skill is the improvement over the naive baseline (positive is better). The verdict uses a Diebold-Mariano test, which stays valid when outcomes overlap, with a Bonferroni correction for the number of models tried.\n\n'demonstrated edge' is rare by design. 'insufficient sample' means too few independent forecasts to say anything.", note: "Appears after a run with the walk-forward test enabled." },
      { route: MD, target: "calibration", title: "Calibration", body: "When a model says 70% up, is it up about 70% of the time? Points on the dashed diagonal mean its probabilities can be taken at face value. Points far off mean it is over- or under-confident.\n\nNext to it, the cumulative skill line shows whether the model beat the baseline steadily or only in a lucky stretch, and whether the edge decayed.", note: "Appears in the first leaderboard row after a run." },
      { route: MD, target: "seasonality", title: "Seasonality", body: "Does this stock do better on Mondays, or in March? Calendar effects are easy to find by luck, so each group is tested against the other days, corrected for testing several groups, and a star marks only effects that survive. Expect mostly faded bars." },
      { route: MD, target: "pairs", title: "Pairs and cointegration", body: "Two stocks are cointegrated if the gap between them keeps snapping back to normal. The scan checks same-sector peers, corrects for scanning many, and requires the relationship to hold in both halves of history ('stable'). Many apparent pairs fail that test." },
      { title: "That is Phase 7", body: "The lesson to carry forward: a model is only as good as its out-of-sample record against a simple baseline. Next up: machine-learning models, ensembles and the Model Lab, held to the same standard." },
    ],
  },
  {
    id: "phase-6", phase: "Phase 6", title: "Fundamentals, risk and the scorecard",
    blurb: "Is the company cheap and healthy? How risky is the stock? A transparent scorecard that shows its working.",
    steps: [
      { title: "What Phase 6 adds", body: "Until now QuantLens looked at price, volume and news. Phase 6 asks three different questions:\n\nIs the business healthy and reasonably priced (fundamentals)? How badly can this stock hurt you, and how does it move with the market (risk)? And what do all the signals say together (the scorecard)?\n\nEverything is descriptive. Nothing here predicts a price or tells you to buy or sell." },
      { route: OV, target: "scorecard", title: "The Signal Scorecard", body: "Six sub-scores from -100 to +100: Trend, Momentum, Volume / flow, Volatility, News sentiment, Valuation.\n\nEach one is just the average vote of simple rules (+1, 0 or -1). Click a row to see every rule, the value it looked at, and why it voted that way. If a data source is missing (no news, no fundamentals), that sub-score is left out rather than guessed.\n\nThe headline label is deliberately mild: leaning positive, mixed or leaning negative.", note: "The scorecard needs about 60 days of stored prices. Run make seed, then reload." },
      { route: OV, target: "watchlist", title: "Scorecard badges in the watchlist", body: "Each watchlist row now shows the last price, today's change, a 30-day sparkline (a tiny line chart of recent closes) and a coloured score badge.\n\nGreen means leaning positive, red leaning negative, grey mixed. It is a quick triage view, not a recommendation.", note: "Badges appear once the watchlist symbols have stored prices." },
      { route: FD, target: "fund-refresh", title: "Fetching fundamentals", body: "Fundamentals are the accounting numbers from a company's financial statements: revenue, profit, debt, cash flow.\n\nClick here to download them for this stock (from Yahoo Finance, free but sometimes incomplete). They are stored locally, so ratios and the DCF below recalculate instantly without downloading again.\n\nFor sector comparisons, refresh a few companies in the same sector." },
      { route: FD, target: "ratios", title: "Ratios, with sector context", body: "Each row has a plain-English meaning. P/E is price divided by earnings per share (how many rupees you pay for one rupee of yearly profit). ROE is profit divided by shareholders' equity (how efficiently the company uses owners' money).\n\nThe percentile bar compares the stock with same-sector companies you have loaded: for example '20' on P/E means cheaper than about 80% of peers. It stays blank until at least 3 peers are loaded, instead of faking precision." },
      { route: FD, target: "scores", title: "Three classic health scores", body: "Piotroski F-score: nine yes/no accounting checks (profitable? cash flow positive? less debt? no new shares?). 7-9 is strong, 0-3 weak. Think of it as a unit-test suite for financial health.\n\nAltman Z: a bankruptcy-risk score for non-financial companies (safe, grey or distress). Not valid for banks, and the app says so.\n\nGraham number: a conservative 'fair price' ceiling from Benjamin Graham's rules of thumb." },
      { route: FD, target: "dcf", title: "A DCF you can play with", body: "A discounted cash flow estimates what a business is worth today by projecting its future free cash flow and discounting it back.\n\nDrag the sliders: discount rate (how demanding you are), growth for the next years, and long-run growth. Watch the answer swing. That swing is the lesson: DCF output is only as good as its assumptions, and most of the value usually sits in the far-future 'terminal' term.\n\nThe grid below shows the same estimate under nearby assumptions." },
      { route: FD, target: "risk-cards", title: "Risk and performance numbers", body: "Sharpe: return earned per unit of volatility, above a risk-free rate you can edit. Sortino: like Sharpe but only penalises downside swings. Max drawdown: the worst peak-to-trough fall. Calmar: yearly return divided by that worst fall.\n\nVaR (value at risk): a loss that was exceeded on only 5% (or 1%) of days. CVaR: the average loss on those worst days. Beta: how much the stock moves per 1% move in the Nifty." },
      { route: FD, target: "drawdown", title: "Underwater chart", body: "This shows how far below its previous peak the stock has been on every day. Zero means a fresh high. Deep, long valleys are what really test an investor's patience, which is why drawdown is often more honest than volatility." },
      { route: FD, target: "rolling-beta", title: "Rolling beta and correlation", body: "Beta and correlation are not constants. Here they are recomputed over a sliding 63-day window (about 3 months), using only past data at each point.\n\nWatch for periods where the stock stopped following the market, or started following it much more closely." },
      { route: FD, target: "correlation", title: "Correlation heatmap", body: "How similarly your watchlist stocks move. Dark red means they move together (little diversification between them), blue means they tend to offset.\n\nIf everything you follow is deep red, one bad market day hits all of it." },
      { route: FD, target: "kelly", title: "Kelly: shown, but with a warning", body: "The Kelly fraction is a formula for how much of a bankroll to risk if you knew your edge exactly. In practice the inputs are noisy estimates, so it wildly overstates safe sizing.\n\nIt is display-only here, on purpose. A negative value means the past return did not even beat the risk-free rate." },
      { title: "That is Phase 6", body: "Re-run this tour any time from the Tour menu in the top bar, and read the full explanation in the Guide. Next up: forecasting models, evaluated honestly against simple baselines." },
    ],
  },
  {
    id: "phase-5a", phase: "Phase 5A", title: "The optional AI layer",
    blurb: "AI that classifies news and gives a second sentiment opinion, with a spending cap and safety checks.",
    steps: [
      { title: "AI is optional", body: "With no API key everything still works. With a key (Anthropic, Gemini, OpenAI, Groq, or a local Ollama model) the AI reads news like an analyst and returns structured data.\n\nThe AI never computes prices or indicators and never gives buy/sell advice. It only interprets text." },
      { route: NW, target: "ai-enrich", title: "AI-enrich", body: "Click to have the AI classify stored articles: which companies, what kind of event, how important (materiality), over what time horizon, and a one-line summary.\n\nNo key? You get a calm 'LLM unavailable' message and the page keeps working." },
      { route: NW, target: "agreement", title: "FinBERT vs the AI", body: "The AI also scores each article's sentiment. Both opinions are stored side by side and compared here: how often they agree, and the biggest disagreements.\n\nThe AI score is a second opinion. It never replaces FinBERT as the default series.", note: "This panel always exists; it fills in after you run AI-enrich with a key set." },
      { route: NW, target: "feed", title: "Chips on every headline", body: "Event type, materiality (red = high), time horizon, 'rehash' when it repeats known facts, and an LLM score chip (green outline = agrees with FinBERT, amber = disagrees).\n\nA red 'suspicious text' chip means the article contained text that looks like instructions to an AI. It was treated purely as data.\n\n'Not for backtests' marks AI output on articles older than your AI data collection: the model may already know how those stories ended." },
      { route: NW, target: "materiality-filter", title: "Filter to what matters", body: "Tick this to show only high-materiality articles, the ones the AI believes could move the stock more than a normal day.", note: "Shown when there are headlines." },
      { route: "/settings", target: "llm-budget", title: "Spending cap with a hard stop", body: "Daily token and dollar budgets. Before every call the app reserves the worst case; if that would pass the cap, the call is refused and nothing is sent anywhere, even to a fallback provider.\n\nSpend is an estimate from prices in config/llm.yaml, not your provider's invoice." },
      { route: "/settings", target: "llm-routing", title: "Which model does what", body: "Each task lists providers in order. The first one with a key is used; on a rate limit or error the next is tried. Put a cheap or free model on bulk extraction and a stronger one on reasoning tasks. Edit config/llm.yaml to change it." },
      { title: "Guardrails in one line", body: "Article text is fenced as untrusted data, advice-sounding or number-inventing summaries are rejected and regenerated, outputs must fit a strict schema, and everything is cached so repeats are free." },
    ],
  },
  {
    id: "phase-5", phase: "Phase 5", title: "News and sentiment",
    blurb: "Six news sources, scored for tone, turned into daily features and compared with price.",
    steps: [
      { route: NW, target: "fetch-news", title: "Fetch news", body: "Pulls articles from Google News and GDELT (no key needed) plus Finnhub, Marketaux, Alpha Vantage and NewsAPI if you added keys. Duplicates are merged, articles are tagged to companies, and each is scored once.\n\nThe result line tells you how many were new, and which source failed and why." },
      { route: NW, target: "market-gauge", title: "Market-wide sentiment", body: "The average tone of all stored news over 30 days, from -1 (negative) to +1 (positive).\n\nThe badge near the title tells you which scorer produced the numbers: FinBERT (a language model tuned for finance) or the simpler VADER fallback." },
      { route: NW, target: "sentiment-chart", title: "Sentiment vs price", body: "The purple line is price. Green/red bars are each day's average sentiment. The amber line is a recency-weighted score: yesterday's news counts half as much as news from the last hour, like an exponential moving average.\n\nAmber circles mark unusual news volume, which often matters more than whether the news was good or bad.", note: "Needs stored articles and daily prices." },
      { route: NW, target: "leadlag", title: "Does sentiment lead price?", body: "Each bar is the correlation between sentiment today and the return a few days later (positive lags) or earlier (negative lags). Solid bars are statistically significant after correcting for testing 11 lags at once; faded ones are not.\n\nExpect mostly faded bars. News usually describes moves that already happened, so price leading sentiment is the common finding.", note: "Needs at least 30 days of overlap between news and prices." },
      { route: NW, target: "top-terms", title: "Top terms and spikes", body: "The most common words in recent headlines, and the days when article volume jumped well above normal.", note: "Appears once articles are stored." },
      { route: NW, target: "feed", title: "The scored feed", body: "Every headline with its sentiment chip, source, time in IST, and the companies it was tagged to. Click a headline to open the original article.\n\nTime rule to remember: an article published after the 15:30 IST market close counts on the next day, because at that day's close nobody could have known it yet." },
    ],
  },
  {
    id: "phase-4", phase: "Phase 4", title: "Market structure and patterns",
    blurb: "Swings, breaks of structure, gaps, volume profile, and an honest test of candlestick patterns.",
    steps: [
      { route: ST, target: "layers", title: "Layers", body: "Toggle each concept on and off. Start with fewer layers: on noisy data the chart gets busy fast.\n\nThese are descriptions of what price did in the vocabulary traders use (swing highs and lows, break of structure, gaps), not forecasts." },
      { route: ST, target: "swing-k", title: "Swing sensitivity (k)", body: "A swing high is a bar whose high beats the k bars on each side. Small k finds many small swings (noisy). Large k finds fewer, bigger ones, but each is confirmed k bars late.\n\nThat delay is deliberate: it is why the analysis never uses information from the future." },
      { route: ST, target: "structure-chart", title: "Reading the chart", body: "HH/HL/LH/LL label each swing against the previous one. BOS marks a close beyond the last swing in the trend's direction; CHoCH a close beyond it against the trend. Shaded boxes are unfilled price gaps (FVG) and order blocks; wide bands are support/resistance zones; the histogram on the right edge is the volume profile.", note: "Needs stored daily prices." },
      { route: ST, target: "volume-profile-card", title: "Volume profile", body: "A histogram of traded volume by price, not by time. POC (point of control) is the price where the most volume traded. The value area holds about 70% of the volume. High-volume nodes tend to act like magnets, low-volume nodes are prices the market moved through quickly." },
      { route: ST, target: "patterns-table", title: "Do candlestick patterns work?", body: "For each named pattern (hammer, engulfing, morning star...) the table finds every past occurrence on this stock and checks what happened next, compared with how often the stock rose anyway (the base rate).\n\nA verdict of 'edge' requires statistical significance after correcting for testing many patterns at once. Most will say 'no demonstrated edge' or 'insufficient sample'. That is the honest, expected result." },
      { route: ST, target: "legend", title: "Plain-language legend", body: "Open this any time for a definition of every marking on the chart." },
    ],
  },
  {
    id: "phase-3", phase: "Phase 3", title: "Indicators on the chart",
    blurb: "81 indicators as overlays and panes, with proof they never peek at the future.",
    steps: [
      { route: OV, target: "overlay-chips", title: "Overlays and panes", body: "Overlays draw on the price chart (moving averages, Bollinger bands, Supertrend, Ichimoku, VWAP...). Panes add small synced charts underneath (RSI, MACD, ADX, volume flow, volatility).\n\nEngineer's view: moving averages are low-pass filters on price, Bollinger bands are a control chart (rolling mean plus or minus 2 standard deviations), and RSI is a normalised ratio of recent gains to losses." },
      { route: OV, target: "layout-buttons", title: "Save your layout", body: "Your selection is remembered automatically. Save layout stores a named slot you can restore with Load." },
      { route: OV, target: "chart", title: "Hover for values", body: "Move the crosshair over the chart to see open, high, low, close, volume and the value of every indicator you turned on at that bar.\n\nBehind the scenes every indicator is tested to be causal: its value at any bar uses only data up to that bar.", note: "Needs stored daily prices." },
    ],
  },
  {
    id: "phase-2", phase: "Phase 2", title: "Data reliability",
    blurb: "Broker data, incremental backfill and a report that tells you when stored data looks wrong.",
    steps: [
      { route: "/settings", target: "providers", title: "Provider status", body: "Where the data comes from. Angel One (a broker API) is used first if you configured all four credentials; otherwise Yahoo Finance. You see rate limits, calls made today, and the last success and error for each.\n\nIf one fails, the next is tried automatically and the page names the failing provider instead of going blank." },
      { route: "/settings", target: "data-quality", title: "Data-quality report", body: "Type a symbol and press Check. The report lists missing trading days (using the NSE holiday calendar), impossible prices, stale data, mixed sources, and extreme moves.\n\nA large raw jump that disappears in the adjusted series is flagged as a likely stock split or bonus. Gaps are reported, never silently filled." },
    ],
  },
  {
    id: "phase-1", phase: "Phase 1", title: "Getting around",
    blurb: "Search, watchlist, market status and the candlestick chart.",
    steps: [
      { route: OV, target: "search", title: "Search any symbol", body: "Type a company name or NSE symbol (RELIANCE, TCS, INFY). Press Enter to open it." },
      { route: OV, target: "market-bar", title: "Market status", body: "Whether NSE is open, the IST clock, and the Nifty 50 and India VIX values. Nifty 50 is the index of 50 large companies; India VIX is the market's expected volatility, often called the fear gauge.", note: "Nifty and VIX show n/a if the data source is unreachable from your network." },
      { route: OV, target: "watchlist", title: "Your watchlist", body: "Stocks you follow. Click one to open it." },
      { route: OV, target: "timeframes", title: "Timeframes", body: "Each candle summarises one time bucket: open, high, low, close, plus volume. 1m is one-minute candles, 1d is daily. Free sources limit how far back intraday history goes." },
      { route: OV, target: "adjusted", title: "Adjusted prices", body: "When a company splits its shares (1 becomes 2), the price halves overnight with no real change in value. Adjusted prices rescale history so the chart is continuous, like re-basing a metric after a unit change." },
      { route: OV, target: "chart", title: "The candlestick chart", body: "Green candle: closed above its open. Red: closed below. The thin lines (wicks) show the highs and lows. Bars underneath are volume.", note: "If you see an error banner here, the data provider is unreachable; the banner names it." },
      { target: "disclaimer", title: "Educational tool", body: "Every page carries this note: educational tool, not investment advice. Data can be delayed or wrong, and no model here is a guarantee." },
    ],
  },
];

export const NEWEST_TOUR = TOURS.find((t) => t.isNew);
