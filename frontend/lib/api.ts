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
  indices: async () => ({
    nifty: await get<Quote>("/quote/NIFTY%2050").catch(() => null),
    vix: await get<Quote>("/quote/INDIA%20VIX").catch(() => null),
  }),
};
