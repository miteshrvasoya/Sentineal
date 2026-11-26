export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Bar = { t: number; o: number; h: number; l: number; c: number; v: number };
export type PricesResponse = {
  symbol: string; interval: string; adjusted: boolean; source: string | null;
  count: number; downsampled: boolean; warnings: string[]; bars: Bar[];
};
export type SymbolOut = { symbol: string; name: string; sector: string; exchange?: string; source?: string };
export type Quote = { symbol: string; last: number; prev_close: number; change: number; change_pct: number; source: string };
export type Health = {
  status: string;
  market: { state: "open" | "closed" | "pre-open"; now_ist: string; next_change_ist: string; holidays_known: boolean };
};

export type ProviderStatus = {
  name: string; configured: boolean; rate_limit: string; last_success: number | null;
  last_error: number | null; last_error_msg: string; calls_today: number;
};
export type QualityIssue = { severity: "error" | "warn" | "info"; kind: string; detail: string; dates?: string[] };
export type Quality = { symbol: string; interval: string; bars: number; first?: string; last?: string; sources?: string[];
  checks: Record<string, number>; issues: QualityIssue[]; ok?: boolean };

export type Indicators = {
  symbol: string; interval: string; version: string; feature_hash: string;
  t: number[]; latest: Record<string, number | null>; series: Record<string, (number | null)[]>;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try { res = await fetch(`${API}${path}`); }
  catch { throw new ApiError(0, `Cannot reach the QuantLens backend at ${API}. Is it running (make dev)?`); }
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail ?? j.error ?? detail; } catch { /* ignore */ }
    throw new ApiError(res.status, String(detail));
  }
  return res.json() as Promise<T>;
}

async function del<T>(path: string): Promise<T> {
  let res: Response;
  try { res = await fetch(`${API}${path}`, { method: "DELETE" }); }
  catch { throw new ApiError(0, `Cannot reach the QuantLens backend at ${API}. Is it running (make dev)?`); }
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : j.error ?? detail; } catch { /* ignore */ }
    throw new ApiError(res.status, String(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<Health>("/health"),
  prices: (symbol: string, interval: string, adjusted: boolean) =>
    get<PricesResponse>(`/prices/${encodeURIComponent(symbol)}?interval=${interval}&adjusted=${adjusted}`),
  quote: (symbol: string) => get<Quote>(`/quote/${encodeURIComponent(symbol)}`),
  search: (q: string) => get<SymbolOut[]>(`/symbols/search?q=${encodeURIComponent(q)}&limit=12`),
  watchlist: () => get<string[]>("/watchlist"),
  providers: () => get<ProviderStatus[]>("/providers/health"),
  quality: (symbol: string, interval = "1d") => get<Quality>(`/data-quality/${encodeURIComponent(symbol)}?interval=${interval}`),
  indicators: (symbol: string, interval: string, adjusted: boolean, sets: string[], limit: number) =>
    get<Indicators>(`/indicators/${encodeURIComponent(symbol)}?set=${sets.join(",")}&interval=${interval}&adjusted=${adjusted}&limit=${limit}`),
  structure: (symbol: string, interval: string, adjusted: boolean, k: number) =>
    get<Structure>(`/structure/${encodeURIComponent(symbol)}?interval=${interval}&adjusted=${adjusted}&k=${k}`),
  patterns: (symbol: string, interval: string, adjusted: boolean) =>
    get<Patterns>(`/patterns/${encodeURIComponent(symbol)}?interval=${interval}&adjusted=${adjusted}`),
  news: (symbol: string, days: number) => get<NewsResponse>(`/news/${encodeURIComponent(symbol)}?days=${days}&limit=200`),
  sentiment: (symbol: string, days: number) => get<SentimentResponse>(`/sentiment/${encodeURIComponent(symbol)}?days=${days}`),
  marketSentiment: (days: number) => get<MarketSentiment>(`/sentiment/market?days=${days}`),
  refreshNews: (symbol: string, days: number) => post<RefreshResult>(`/news/${encodeURIComponent(symbol)}/refresh?days=${days}`),
  newsEnriched: (symbol: string, days: number, minMateriality = "low") =>
    get<EnrichedResponse>(`/news/${encodeURIComponent(symbol)}/enriched?days=${days}&limit=200&min_materiality=${minMateriality}`),
  llmStatus: () => get<LlmStatus>("/llm/status"),
  llmUsage: () => get<LlmUsage>("/llm/usage?days=14"),
  enrich: (symbol: string) => post<EnrichResult>(`/llm/enrich/${encodeURIComponent(symbol)}?limit=40`),
  scorecard: (symbol: string) => get<Scorecard>(`/scorecard/${encodeURIComponent(symbol)}`),
  fundamentals: (symbol: string, q = "") => get<Fundamentals>(`/fundamentals/${encodeURIComponent(symbol)}${q}`),
  refreshFundamentals: (symbol: string) => post<{ fields_found: number; fields_total: number; has_prior_year: boolean; sector: string }>(`/fundamentals/${encodeURIComponent(symbol)}/refresh`),
  risk: (symbol: string, rf: number) => get<Risk>(`/risk/${encodeURIComponent(symbol)}?rf=${rf}`),
  correlation: () => get<Corr>("/risk/correlation"),
  watchSummary: () => get<WatchRow[]>("/watchlist/summary"),
  modelCatalog: () => get<{ models: ModelInfo[]; horizons: number[]; note: string }>("/models"),
  runModels: (symbol: string, body: { models: string[]; horizon: number; evaluate: boolean; mode: string; fast: boolean; levels: number[]; ensemble: boolean }) =>
    postJson<Job>(`/models/${encodeURIComponent(symbol)}/run`, body),
  job: (id: string) => get<Job>(`/jobs/${id}`),
  analysis: (symbol: string, horizon: number) => get<AnalysisResp>(`/analysis/${encodeURIComponent(symbol)}?horizon=${horizon}`),
  evaluation: (symbol: string, horizon: number) => get<EvalResp>(`/models/${encodeURIComponent(symbol)}/evaluation?horizon=${horizon}`),
  seasonality: (symbol: string) => get<Seasonality>(`/analysis/seasonality/${encodeURIComponent(symbol)}`),
  pairs: (symbol: string) => get<Pairs>(`/analysis/pairs/${encodeURIComponent(symbol)}`),
  ablation: (symbol: string, horizon: number) => get<Ablation>(`/models/${encodeURIComponent(symbol)}/ablation?horizon=${horizon}`),
  registry: (symbol: string) => get<RegistryRow[]>(`/models/${encodeURIComponent(symbol)}/registry`),
  aiAnalyst: (symbol: string, horizon = 5) => post<AnalystReport>(`/ai/analyst/${encodeURIComponent(symbol)}?horizon=${horizon}`),
  aiExplainModel: (symbol: string, model: string, horizon: number) => postJson<ModelExplanation>(`/ai/explain-model/${encodeURIComponent(symbol)}`, { model, horizon }),
  aiExplainMove: (symbol: string, start?: string, end?: string) => postJson<MoveExplanation>(`/ai/explain-move/${encodeURIComponent(symbol)}`, { start, end }),
  aiBacktestReview: (strategy: string, metrics: Record<string, unknown>) => postJson<BacktestReviewOut>("/ai/backtest-review", { strategy, metrics }),
  btStrategies: () => get<{ strategies: StrategyInfo[]; cost_presets: Record<string, Record<string, number>>; cost_note: string }>("/backtest/strategies"),
  backtest: (symbol: string, body: BtRequest) => postJson<BacktestOut>(`/backtest/${encodeURIComponent(symbol)}`, body),
  screenFields: () => get<{ fields: ScreenField[]; ops: string[]; presets: ScreenPreset[] }>("/screener/fields"),
  screenRun: (conditions: ScreenCond[], sort: string, desc: boolean) => postJson<ScreenResult>("/screener/run", { conditions, sort, desc, limit: 100 }),
  breadth: () => get<Breadth>("/market/breadth"),
  sectors: () => get<{ rows: SectorRow[]; note: string }>("/market/sectors"),
  schedStatus: () => get<SchedStatus>("/scheduler/status"),
  schedRun: (job: string) => post<{ started: string }>(`/scheduler/run/${encodeURIComponent(job)}`),
  chat: (message: string, history: { role: string; content: string }[]) => postJson<ChatOut>("/ai/chat", { message, history }),
  nlScreen: (request: string) => postJson<NLScreenOut>("/ai/nl-screen", { request }),
  briefing: () => post<BriefingOut>("/ai/briefing"),
  briefingLatest: () => get<BriefingOut>("/ai/briefing/latest"),
  redFlags: (symbol: string) => get<RedFlags>(`/redflags/${encodeURIComponent(symbol)}`),
  redFlagsAll: () => get<RedFlagRow[]>("/redflags"),
  safetyEval: () => get<SafetyEval>("/llm/eval/safety"),
  portfolio: () => get<Portfolio>("/portfolio"),
  pfHistory: () => get<PfHistory>("/portfolio/history"),
  pfTxns: () => get<PfTxn[]>("/portfolio/transactions"),
  pfAdd: (t: PfTxnIn | { transactions: PfTxnIn[] }) => postJson<{ added: number; message: string; price_problems: string[] }>("/portfolio/transactions", t),
  pfDelete: (id: number) => del<{ deleted: number }>(`/portfolio/transactions/${id}`),
  pfRefresh: () => post<{ refreshed: number; problems: { symbol: string; error: string }[] }>("/portfolio/refresh"),
  discoverStatus: () => get<DiscoverStatus>("/discover/status"),
  discoverLoad: () => post<JobOut>("/discover/load"),
  ideas: (horizon: string, risk: string, sector: string) => get<IdeasOut>(`/discover/ideas?horizon=${horizon}&risk=${risk}&limit=10${sector ? `&sector=${encodeURIComponent(sector)}` : ""}`),
  stockView: (symbol: string) => get<StockView>(`/discover/stock/${encodeURIComponent(symbol)}`),
  watchAdd: (symbol: string) => postJson<string[]>("/watchlist", { symbol }),
  watchRemove: (symbol: string) => del<string[]>(`/watchlist/${encodeURIComponent(symbol)}`),
  orModels: () => get<ORModels>("/llm/openrouter/models"),
  indices: async () => ({
    nifty: await get<Quote>("/quote/NIFTY%2050").catch(() => null),
    vix: await get<Quote>("/quote/INDIA%20VIX").catch(() => null),
  }),
};

export type StructureEvent = { i_t: number; kind: "BOS" | "CHoCH" | "sweep_high" | "sweep_low"; dir: "bull" | "bear"; level: number };
export type Zone = { i_t: number; formed_t: number; resolved_t: number | null; dir: "bull" | "bear"; low: number; high: number };
export type Structure = {
  symbol: string; interval: string; bars: number; trend: string; k: number;
  swings: { t: number; confirmed_t: number; kind: "high" | "low"; price: number; label: string }[];
  events: StructureEvent[]; order_blocks: (Zone & { event: string })[]; fvg: Zone[];
  dealing_range: { high: number; low: number; equilibrium: number; position_pct: number; zone: string } | null;
  fibonacci: { leg: string; start: number; end: number; retracements: Record<string, number>; extensions: Record<string, number> } | null;
  pivots: Record<string, { period: string; classic: Record<string, number> }>;
  sr_zones: { low: number; high: number; touches: number; type: string }[];
  volume_profile: { window: number; poc: number; vah: number; val: number; hvn: number[]; lvn: number[]; bins: { low: number; high: number; volume: number }[] } | null;
  wyckoff: { label: string; evidence: string[]; heuristic: boolean };
};
export type PatternStat = {
  pattern: string; direction: "bull" | "bear" | "neutral"; occurrences: number;
  horizons: Record<string, { n: number; avg_return_pct?: number; hit_rate?: number; baseline_hit_rate?: number;
    avg_dir_return_pct?: number; p_value?: number; p_value_bonferroni?: number; verdict?: string }>;
};
export type Patterns = { symbol: string; bars: number; recent: { t: number; pattern: string; direction: string }[]; stats: PatternStat[]; notes: string[] };

export type Article = {
  id: string; title: string; url: string; source: string; provider: string; published: number; summary: string;
  tickers: string[]; score: number; label: "positive" | "negative" | "neutral"; pos: number; neg: number; neu: number;
  provider_score: number | null;
};
export type NewsResponse = { symbol: string; model: string | null; count: number; articles: Article[]; note?: string };
export type SentDay = {
  date: string; mean_sent: number | null; sent_std: number | null; n_articles: number; volume_z: number | null;
  volume_spike: number; pos_ratio: number | null; recency_weighted: number | null; sent_mom: number | null; divergence?: number;
};
export type LeadLag = { lag: number; n: number; corr: number | null; p: number | null; p_bonferroni: number | null };
export type SentimentResponse = {
  symbol: string; days: number; model: string; n_articles: number; latest: SentDay | null; daily: SentDay[];
  lead_lag: LeadLag[]; spikes: SentDay[]; top_terms: [string, number][]; notes: string[];
};
export type MarketSentiment = { model: string | null; latest: number | null; n_articles?: number; series: { date: string; value: number }[]; note?: string };
export type RefreshResult = { symbol: string; fetched: number; new: number; duplicates: number; scored: number; model: string; errors: Record<string, string> };

async function post<T>(path: string): Promise<T> {
  let res: Response;
  try { res = await fetch(`${API}${path}`, { method: "POST" }); }
  catch { throw new ApiError(0, `Cannot reach the QuantLens backend at ${API}.`); }
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.json() as Promise<T>;
}

export type Enriched = {
  id: string; title: string; url: string; source: string; published: number;
  ref_score: number | null; ref_label: string | null; llm_score: number | null; llm_label: string | null; llm_model: string | null;
  event_type: string | null; direction: string | null; materiality: "low" | "medium" | "high" | null; horizon: string | null;
  is_new_information: boolean | null; summary: string | null; flags: string[]; llm_generated_at: number | null; valid_for_backtest: boolean;
};
export type Agreement = { n: number; label_agreement: number | null; sign_agreement: number | null;
  disagreements: { article_id: string; reference: number; llm: number; title: string }[] };
export type EnrichedResponse = { symbol: string; reference_model: string | null; badge: string; llm_available: boolean;
  forward_start: number | null; count: number; articles: Enriched[]; agreement: Agreement };
export type LlmStatus = {
  available: boolean; badge: string; forward_only: boolean; forward_start: number | null;
  providers: Record<string, boolean>;
  tasks: Record<string, { temperature: number; max_tokens: number; chain: { provider: string; model: string; configured: boolean }[] }>;
  budget: { tokens: number; usd: number; token_budget: number; usd_budget: number; exhausted: boolean };
};
export type LlmUsage = { today: LlmStatus["budget"];
  rows: { day: string; task: string; tokens_in: number; tokens_out: number; usd: number; calls: number; cache_hits: number; failures: number }[] };
export type EnrichResult = { available: boolean; reason?: string; badge: string;
  enrichment?: { processed: number; flagged: number; summaries_removed: number; failed_batches: number; stopped: string | null; model: string | null };
  sentiment?: { scored: number; failed_batches: number; stopped: string | null; model: string | null } };


export type Rule = { id: string; rule: string; value: number | string | null; vote: -1 | 0 | 1; why: string };
export type SubScore = { label: string; weight: number; available: boolean; score: number | null; rules: Rule[]; fired: string[] };
export type Scorecard = {
  symbol: string; as_of: string; bars: number; composite: number | null; label: string | null;
  subscores: Record<string, SubScore>; missing: string[]; disclaimer: string;
};
export type Pct = { percentile: number | null; peers: number; higher_is_better?: boolean };
export type Fundamentals = {
  symbol: string; sector: string; currency: string; price: number | null; fetched_at: number; stale_days: number; notes: string[];
  ratios: Record<string, number | null>; percentiles: Record<string, Pct>; peers_used: number;
  piotroski: { score: number; evaluated: number; out_of: number; reading: string; criteria: { id: string; label: string; result: "pass" | "fail" | "na" }[] };
  altman: { z: number | null; zone: string | null; applicable: boolean; note?: string; components?: Record<string, number> };
  graham: { value: number | null; price?: number; price_vs_graham?: number | null; note?: string };
  dcf: { assumptions: { r: number; g1: number; g2: number; years: number }; intrinsic_per_share: number | null; upside_pct?: number | null;
    reason?: string; terminal_share_pct?: number; note?: string; fcf0: number | null; pv_stage1?: number; pv_terminal?: number;
    projection?: { year: number; fcf: number; pv: number }[] };
  dcf_defaults: { r: number; g1: number; g2: number; years: number };
  dcf_sensitivity: { r: number; g1: number; intrinsic: number | null }[];
};
export type VarBlock = { historical_var: number | null; historical_cvar: number | null; parametric_var: number | null; parametric_cvar: number | null };
export type Risk = {
  symbol: string; benchmark: string | null; window: number; notes: string[]; disclaimer: string;
  summary: {
    rf: number; first: string; last: string; n_returns: number; cagr: number | null; volatility_annual: number | null;
    sharpe: number | null; sortino: number | null; calmar: number | null; max_drawdown: number | null;
    max_drawdown_peak: string | null; max_drawdown_trough: string | null; longest_drawdown_bars: number;
    current_drawdown: number | null; current_drawdown_bars: number; best_day: number | null; worst_day: number | null;
    var_95: VarBlock; var_99: VarBlock; kelly: { full: number | null; half: number | null; warning: string } | null;
    vs_benchmark?: { beta: number | null; alpha_annual: number | null; correlation: number | null; r_squared: number | null; n: number };
  };
  series: { dates: string[]; equity: (number | null)[]; drawdown: (number | null)[]; volatility: (number | null)[]; sharpe: (number | null)[];
    beta: (number | null)[] | null; correlation: (number | null)[] | null };
};
export type Corr = { symbols: string[]; matrix: (number | null)[][]; days: number };
export type WatchRow = { symbol: string; last: number | null; change_pct: number | null; spark: number[]; score: number | null; label: string | null };


async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try { res = await fetch(`${API}${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }); }
  catch { throw new ApiError(0, `Cannot reach the QuantLens backend at ${API}.`); }
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : j.error ?? detail; } catch { /* ignore */ }
    throw new ApiError(res.status, String(detail));
  }
  return res.json() as Promise<T>;
}

export type ModelInfo = { name: string; kind: string; group: string; description: string; experimental: boolean; baseline: boolean;
  available: boolean; unavailable_reason: string | null; needs: string | null };
export type Job = {
  id: string; kind: string; symbol: string; status: "queued" | "running" | "done" | "failed"; progress: number; duration_s: number | null;
  error: string | null; result: null | { evaluated: boolean; warnings: string[]; elapsed_s: number; models: string[];
    walk_forward: null | { mode: string; forecasts: number; min_train: number; refit_every: number; stride: number } };
};
export type FanData = { days: number[]; last: number; fan: Record<"p5" | "p25" | "p50" | "p75" | "p95", number[]>;
  touch: Record<string, { level: number; direction: "above" | "below"; probability: number }> };
export type VolCone = { horizons: number[]; forecast: number[]; hist_min: number[]; hist_p25: number[]; hist_p50: number[]; hist_p75: number[]; hist_max: number[]; current: number[] };
export type RegimeRow = { regime: string; mean_return_annual: number; volatility_annual: number; share_of_days: number; expected_duration_days: number; stay_probability: number };
export type ModelViewT = {
  name: string; horizon: number; p_up: number; p_flat: number; p_down: number; quantiles: Record<string, number>; flat_band: number; asof: string;
  version: string; kind: string; vote: "up" | "flat" | "down"; conviction: number; drivers: { name: string; value: string | number }[]; notes: string[];
  training_window: { start: string; end: string; n: number };
  extras: { fan?: FanData; vol_cone?: VolCone; vol_forecast_annualised?: number; regime_probs?: Record<string, number>; current_regime?: string;
    regime_table?: RegimeRow[]; timeline?: { dates: string[]; regime: number[]; prob: number[]; labels: string[] };
    weights?: Record<string, number>; calibration?: { raw: number; calibrated: number; trust_in_model: number; base_rate_loss: number };
    shap_global?: { feature: string; mean_abs_shap: number }[]; shap_now?: { feature: string; value: number | null; toward_up: number; toward_down: number }[];
    shap_note?: string; permutation_importance?: { feature: string; importance: number; std: number }[];
    partial_dependence?: { feature: string; grid: number[]; p_up: number[] }[] };
};
export type ConsensusRow = { name: string; kind: string; vote: string; p_up: number; p_flat: number; p_down: number; conviction: number; net: number;
  verdict: string | null; verdict_reason: string | null; hit_rate: number | null; naive_rate: number | null; brier_skill: number | null;
  n_effective: number | null; edge: boolean; median_return: number | null };
export type Consensus = { models: ConsensusRow[]; baselines: ConsensusRow[]; ensemble: ConsensusRow | null; votes: Record<string, number>; n_models: number; n_edge: number;
  majority: string | null; majority_share: number | null; spread: number | null; disagreement: "low" | "medium" | "high" | null;
  conviction: "low" | "moderate" | null; headline: string; how_to_read?: string };
export type AnalysisResp = { symbol: string; horizon: number; asof: string; consensus: Consensus; views: Record<string, ModelViewT>;
  scorecard: Scorecard | null; versions: Record<string, number>; trained_at: number };
export type EvalDetail = {
  n_forecasts: number; n_effective: number; failures?: number; failure_rate?: number; verdict: string; verdict_reason: string; brier: number; brier_skill?: number; dm_p?: number; p_adjusted?: number;
  directional: { n: number; hits?: number; hit_rate: number | null; naive_rate: number | null; p_vs_half: number | null; p_vs_naive: number | null };
  confusion: { classes: string[]; matrix: number[][]; precision: Record<string, number | null>; recall: Record<string, number | null>; accuracy3: number };
  calibration_up: { rows: { bin: string; mean_pred: number; observed: number; n: number }[]; ece: number | null };
  pinball: { mean: number; coverage_90: number; coverage_50: number; coverage_note: string };
  point: { mase: number | null; mae: number; mae_naive: number; note: string };
  rank_ic: { ic: number | null; p: number | null; rolling: { date: string; ic: number | null }[] };
  cum_skill?: { date: string; v: number }[]; rolling_accuracy: { date: string; v: number }[];
  equity?: { series: { date: string; v: number }[]; buy_hold: { date: string; v: number }[]; exposure: number; total_return: number; buy_hold_return: number; note: string };
};
export type EvalResp = {
  symbol: string; horizon: number; notes: string[]; period: { first: string; last: string; forecasts: number; mode: string; stride: number };
  leaderboard: { model: string; baseline: boolean; verdict: string; brier: number; brier_skill: number | null; hit_rate: number | null; naive_rate: number | null;
    p_vs_naive: number | null; accuracy3: number; ece: number | null; mase: number | null; pinball: number; coverage_90: number; rank_ic: number | null;
    dm_p: number | null; p_adjusted: number | null; n_effective: number; version: number }[];
  details: Record<string, EvalDetail>;
};
export type SeasonRow = { group: string; n: number; mean_pct: number | null; up_share: number | null; p: number | null; p_bonferroni: number | null; significant: boolean };
export type Seasonality = {
  n_returns: number; first: string; last: string; notes: string[];
  day_of_week: { rows: SeasonRow[]; kruskal_p: number | null; any_significant: boolean };
  month: { rows: SeasonRow[]; kruskal_p: number | null; any_significant: boolean };
  stl: null | { period: number; seasonal_strength: number; trend_strength: number; reading: string };
};
export type PairRow = { peer: string; n: number; p?: number; p_bonferroni?: number; hedge_ratio?: number; half_life_days?: number | null; zscore_now?: number | null;
  p_first_half?: number | null; p_second_half?: number | null; stable?: boolean; candidate?: boolean; skipped?: string };
export type Pairs = { target: string; tested: number; peers: PairRow[]; best: string | null; notes: string[];
  best_spread: null | { dates: string[]; spread: number[]; mean: number; std: number } };


export type Ablation = {
  symbol: string; horizon: number; reading: string; notes: string[];
  rows: { model: string; label: string; brier: number; brier_skill: number | null; verdict: string | null; hit_rate: number | null; n_effective: number; failures: number }[];
  paired: { n: number; brier_gain: number | null; dm_p: number | null; adds_value: boolean };
  news_coverage: { days_span: number; days_with_news: number };
};
export type RegistryRow = { model: string; horizon: number; version: number; trained_at: number; train_start: string; train_end: string; n_train: number;
  feature_hash: string; verdict: string | null; brier_skill: number | null; hit_rate: number | null; params: Record<string, unknown> };

export type Claim = { text: string; evidence: string[] };
export type AiBase = { available: boolean; badge: string; reason?: string; facts: Record<string, string | number | boolean>; missing: string[];
  withheld?: boolean; problems?: string[]; error?: string; provider?: string; model?: string; cached?: boolean; repaired?: boolean; prompt?: string };
export type AnalystReport = AiBase & { report: null | { stance: string; headline: string; plain_summary: string; in_favour: Claim[]; against: Claim[]; conflicts: Claim[]; data_gaps: string[] } };
export type ModelExplanation = AiBase & { report: null | { verdict_in_words: string; plain_summary: string; drivers: Claim[]; cautions: Claim[] } };
export type MoveArticle = { id: string; title: string; source: string; url: string; published?: string; injection_flags?: string[] };
export type MoveExplanation = AiBase & { start: string; end: string; articles: MoveArticle[];
  report: null | { plain_summary: string; market_context: Claim; candidates: { text: string; article_ids: string[]; evidence: string[]; strength: string }[]; unexplained: string } };
export type RedFlag = { id: string; message: string };
export type BacktestReviewOut = AiBase & { red_flags: RedFlag[];
  report: null | { verdict: string; plain_summary: string; concerns: Claim[]; strengths: Claim[]; what_to_check_next: string[] } };

export type BtMetrics = { n_days?: number; years?: number; total_return?: number; cagr?: number | null; volatility_annual?: number; sharpe?: number; sortino?: number | null;
  max_drawdown?: number; calmar?: number | null; n_trades?: number; win_rate?: number | null; profit_factor?: number | null; avg_trade_return?: number | null;
  avg_bars_held?: number | null; top5_trade_share?: number | null };
export type BtBoot = { available: boolean; reason?: string; reps?: number; sharpe?: number; sharpe_ci90?: number[]; total_return_ci90?: number[]; p_value?: number;
  trials?: number; p_adjusted?: number; block_length?: number; hist?: { counts: number[]; edges: number[] } };
export type BtTrade = { entry_date: string; exit_date: string; entry_price: number; exit_price: number; qty: number; gross_pnl: number; costs: number; net_pnl: number;
  return_pct: number; bars: number; exit_reason: string };
export type StrategyInfo = { name: string; title: string; description: string; defaults: Record<string, number>; grid: Record<string, number[]>; grid_size: number };
export type BacktestOut = {
  symbol: string; strategy: string; params: Record<string, number>; bars: number; warmup_bars: number; first_trade_allowed: string; last_bar: string; capital: number;
  metrics: BtMetrics; buy_hold: BtMetrics; no_cost: { total_return: number | null; sharpe: number | null };
  costs: { paid: Record<string, number>; total_charges: number; slippage: number; total_drag: number; drag_pct_of_capital: number; exposure: number; return_lost_to_costs: number };
  series: { equity: { date: string; v: number }[]; buy_hold: { date: string; v: number }[]; drawdown: { date: string; v: number }[]; split_date?: string };
  trades: BtTrade[]; bootstrap: BtBoot;
  luck_test: { available: boolean; reason?: string; percentile?: number; p_value?: number; random_median?: number; random_p5?: number; random_p95?: number; real_log_return?: number; note?: string };
  held_out: null | { split_date: string; in_sample: BtMetrics; out_of_sample: BtMetrics; buy_hold_oos: BtMetrics; bootstrap_oos: BtBoot; sharpe_drop: number };
  search: null | { trials: number; criterion: string; chosen: Record<string, number>; top: { params: Record<string, number>; in_sample_sharpe: number }[]; worst: { params: Record<string, number>; in_sample_sharpe: number }[] };
  reviewer_input: Record<string, unknown>; verdict: { label: string; reasons: string[]; beats_buy_hold: boolean; caveat: string }; notes: string[];
};
export type BtRequest = { strategy: string; params: Record<string, number>; cost_preset: string; capital: number; stop_loss: number | null; oos_fraction: number; optimize: boolean };

export type ScreenField = { key: string; label: string; group: string; kind: "number" | "text" | "bool"; unit: string; desc: string };
export type ScreenCond = { field: string; op: string; value: unknown };
export type ScreenPreset = { id: string; title: string; idea: string; conditions: ScreenCond[] };
export type ScreenRow = { symbol: string; sector: string; as_of: string; [k: string]: string | number | boolean | null };
export type ScreenResult = { universe: number; matches: number; rows: ScreenRow[]; missing_data: Record<string, number>; disclaimer: string };
export type Breadth = { n: number; above_sma50: number | null; above_sma200: number | null; positive_5d: number | null; positive_21d: number | null;
  near_52w_high: number | null; near_52w_low: number | null; median_5d_return: number | null; reading: string };
export type SectorRow = { sector: string; n: number; ret_5d: number | null; ret_21d: number | null; ret_63d: number | null; ret_126d: number | null;
  rank_5d: number | null; rank_21d: number | null; rank_63d: number | null; rank_126d: number | null; rotation: number | null; rs_rank_126: number | null };
export type SchedRun = { id: number; job: string; trigger: string; started: number; finished: number | null; duration_s: number | null; status: string; error: string | null; result: unknown };
export type SchedJob = { name: string; title: string; description: string; schedule: string; when: string; enabled: boolean; running: boolean; due_now: boolean; last_run: SchedRun | null };
export type SchedStatus = { enabled: boolean; tick_seconds: number; jobs: SchedJob[]; recent: SchedRun[]; note: string };

export type ChatStep = { id: string; tool: string; args: Record<string, unknown>; reason: string; error: string | null; result: string | null };
export type ChatOut = { available: boolean; badge: string; reason?: string; answer: string | null; citations: string[]; follow_ups: string[]; steps: ChatStep[];
  withheld: boolean; problems: string[]; error: string | null; meta?: { provider?: string; model?: string; cached?: boolean }; prompt?: string };
export type NLScreenOut = { available: boolean; reason?: string; error?: string; withheld?: boolean; problems?: string[]; model?: string; provider?: string;
  screen: null | { conditions: ScreenCond[]; sort: string; desc: boolean; explanation: string; unsupported: string[] }; result: ScreenResult | null };
export type BriefingOut = AiBase & { asof?: string; generated_at?: number;
  report: null | { headline: string; market_summary: string; movers: Claim[]; watch_items: Claim[]; red_flags: Claim[]; data_notes: string[] } };
export type RedFlag2 = { id: string; severity: "high" | "medium" | "low"; message: string; evidence: Record<string, unknown> };
export type RedFlags = { symbol: string; flags: RedFlag2[]; count: number; checked: string[]; note: string };
export type RedFlagRow = { symbol: string; count: number; high: number; medium: number; top: string | null };
export type SafetyEval = {
  injection: { n: number; safe: number; violations: number; blocked_by_guardrail: number; resisted_by_model: number; safe_rate: number | null; rows: { id: string; kind: string; result: string; violations?: string[] }[]; stopped: string | null; note: string };
  agent: { n: number; tool_choice_accuracy: number | null; answer_rate: number | null; withheld_rate: number | null; cited_rate: number | null; stopped: string | null };
};

export type PfPosition = { symbol: string; name: string; sector: string; qty: number; avg_cost: number; invested: number; price: number | null; price_as_of: string | null;
  value: number | null; first_buy: string | null; realised: number; pl?: number; pl_pct?: number | null; day_change?: number; day_change_pct?: number | null; stale_days: number | null; weight: number | null };
export type PfCheck = { level: "high" | "medium" | "info" | "good"; title: string; text: string; symbols: string[] };
export type Portfolio = {
  empty: boolean;
  summary: { value: number; invested: number; pl: number; pl_pct: number | null; realised: number; total_pl: number; day_change: number; day_change_pct: number | null;
    annual_return: number | null; annual_return_note: string | null; holdings: number; unpriced: string[] };
  positions: PfPosition[]; allocation: { by_sector: { sector: string; weight: number; value: number }[] };
  closed: { symbol: string; name: string; realised: number; bought: number; sold: number }[]; checkup: PfCheck[];
};
export type PfTxn = { id: number; symbol: string; side: "buy" | "sell"; qty: number; price: number; fees: number; date: string; note: string; amount: number };
export type PfTxnIn = { symbol: string; side: "buy" | "sell"; qty: number; price: number; date: string; fees?: number; note?: string };
export type PfHistory = { points: { date: string; value: number; put_in: number }[]; note?: string };
export type Idea = { symbol: string; sector: string; horizon: "short" | "long"; score: number | null; label: string; ranked: boolean; confidence: number; checks: string; risk: string;
  why: string[]; watch_out: string[]; change_my_mind: string[]; numbers: Record<string, number | null> };
export type IdeasOut = { horizon: "short" | "long"; horizon_text: string; ideas: Idea[]; considered: number; universe: number; unranked: number; disclaimer: string; sectors: string[] };
export type DiscoverStatus = { popular: number; loaded: number; with_company_numbers: number; stored_total: number; enough_to_compare: boolean; hint: string };
export type StockView = { symbol: string; short: Idea; long: Idea; compared_with: number; disclaimer: string };
export type JobOut = { id: string; kind: string; status: "queued" | "running" | "done" | "failed"; progress: number; error: string | null; result: Record<string, unknown> | null };
export type ORModels = { ok: boolean; error?: string; ranked: { id: string; name: string; score: number; context: number | null; reasons: string[]; structured: boolean }[]; defaults?: string[];
  current: string | null; key_set: boolean; recommended?: string | null; note?: string };
