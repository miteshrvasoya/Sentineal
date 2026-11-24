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
