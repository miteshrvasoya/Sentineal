export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Bar = { t: number; o: number; h: number; l: number; c: number; v: number };
export type PricesResponse = {
  symbol: string; interval: string; adjusted: boolean; source: string | null;
  count: number; downsampled: boolean; warnings: string[]; bars: Bar[];
};
export type SymbolOut = { symbol: string; name: string; sector: string };
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

export const api = {
  health: () => get<Health>("/health"),
  prices: (symbol: string, interval: string, adjusted: boolean) =>
    get<PricesResponse>(`/prices/${encodeURIComponent(symbol)}?interval=${interval}&adjusted=${adjusted}`),
  quote: (symbol: string) => get<Quote>(`/quote/${encodeURIComponent(symbol)}`),
  search: (q: string) => get<SymbolOut[]>(`/symbols/search?q=${encodeURIComponent(q)}`),
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
