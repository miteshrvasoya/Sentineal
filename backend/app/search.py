"""Stock search over the whole NSE equity list (about 2,200 companies), plus a live Yahoo Finance lookup for the rest.

Typing a company name ("tata motors"), a short name ("sbi"), a symbol ("INFY") or a typo ("relience") should all find the stock.
"""
from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

import httpx

from app.config import ROOT

SUFFIXES = re.compile(r"\b(limited|ltd|corporation|corp|company|co|india|industries|inc|the|of)\b\.?", re.I)
YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
_live_cache: dict[str, tuple[float, list[dict]]] = {}
LIVE_TTL = 600.0
STRONG = 55


@dataclass(frozen=True)
class Entry:
    symbol: str
    name: str
    sector: str
    exchange: str
    isin: str
    aliases: tuple[str, ...]
    core: str                 # lower-cased name without "Limited", "Industries", ...
    featured: bool            # in the curated symbol list (large, well-known companies)


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = SUFFIXES.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@lru_cache
def universe() -> tuple[Entry, ...]:
    curated: dict[str, tuple[str, str]] = {}
    with open(ROOT / "data" / "symbols.csv", newline="") as f:
        for r in csv.DictReader(f):
            curated[r["symbol"]] = (r["name"], r["sector"])
    popular: dict[str, str] = {}
    pp = ROOT / "data" / "popular.csv"
    if pp.exists():
        with open(pp, newline="") as f:
            popular = {r["symbol"]: r["sector"] for r in csv.DictReader(f)}
    aliases: dict[str, tuple[str, ...]] = {}
    for fn in ("aliases.csv", "search_aliases.csv"):                   # news aliases + informal / former names people actually type
        p = ROOT / "data" / fn
        if p.exists():
            with open(p, newline="") as f:
                for r in csv.DictReader(f):
                    aliases[r["symbol"]] = aliases.get(r["symbol"], ()) + tuple(a.strip() for a in r["aliases"].split("|") if a.strip())
    out: dict[str, Entry] = {}
    p = ROOT / "data" / "nse_equities.csv"
    if p.exists():
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                sym = r["symbol"].upper()
                nm, sec = curated.get(sym, (r["name"], popular.get(sym, "")))
                out[sym] = Entry(sym, nm, sec, "NSE", r.get("isin", ""), aliases.get(sym, ()), _norm(nm), sym in curated or sym in popular)
    for sym, (nm, sec) in curated.items():
        if sym not in out:
            out[sym] = Entry(sym, nm, sec, "NSE", "", aliases.get(sym, ()), _norm(nm), True)
    return tuple(out.values())


def score(e: Entry, q: str, qn: str, toks: list[str]) -> float:
    """0 = no match. Higher is better."""
    sym = e.symbol.lower()
    if sym == q:
        return 100
    best = 0.0
    if sym.startswith(q):
        best = max(best, 92 - min(len(sym) - len(q), 10) * 0.5)
    alias_n = [_norm(a) for a in e.aliases]
    if qn and any(a == qn for a in alias_n):
        best = max(best, 96)
    if qn and (e.core.startswith(qn) or any(a.startswith(qn) for a in alias_n)):
        best = max(best, 88)
    words = e.core.split()
    if toks and all(any(w.startswith(t) for w in words) for t in toks):
        best = max(best, 82 - min(len(words) - len(toks), 5))
    if len(q) >= 3 and q in sym:
        best = max(best, 62)
    if qn and len(qn) >= 3 and qn in e.core:
        best = max(best, 58)
    if best == 0 and len(q) >= 4:                                  # typo tolerance: compare with the symbol and each name word
        cands = [sym, *words, e.core, *alias_n]
        r = max(SequenceMatcher(None, qn or q, c).ratio() for c in cands if c)
        if r >= 0.78:
            best = 30 + (r - 0.78) * 100
    if best and e.featured:
        best += 4                                                   # well-known companies first among equals
    return best


def search_local(q: str, limit: int = 10) -> list[dict]:
    q = q.strip().lower()
    if not q:
        return [_dict(e, "local") for e in universe() if e.featured][:limit]
    qn = _norm(q)
    toks = qn.split()
    scored = [(s, e) for e in universe() if (s := score(e, q, qn, toks)) > 0]
    scored.sort(key=lambda x: (-x[0], len(x[1].symbol), x[1].symbol))
    if scored and scored[0][0] >= STRONG:                              # typo-tolerant guesses only appear when nothing matches properly
        scored = [x for x in scored if x[0] >= STRONG]
    return [_dict(e, "local") for _, e in scored[:limit]]


def _dict(e: Entry, source: str) -> dict:
    return {"symbol": e.symbol, "name": e.name, "sector": e.sector, "exchange": e.exchange, "source": source}


async def search_live(q: str, limit: int = 8, timeout: float = 2.5) -> list[dict]:
    """Yahoo Finance's public search: finds BSE stocks and companies newer than the bundled list. Fails quietly when offline."""
    key = q.strip().lower()
    hit = _live_cache.get(key)
    if hit and time.time() - hit[0] < LIVE_TTL:
        return hit[1]
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = await c.get(YAHOO_SEARCH, params={"q": q, "quotesCount": 12, "newsCount": 0, "listsCount": 0})
            r.raise_for_status()
            quotes = r.json().get("quotes", [])
        for x in quotes:
            sym, exch, kind = str(x.get("symbol", "")), x.get("exchange", ""), x.get("quoteType", "")
            if kind not in ("EQUITY", "ETF") or not sym:
                continue
            name = x.get("longname") or x.get("shortname") or sym
            if sym.endswith(".NS") and exch in ("NSI", "NSE"):
                out.append({"symbol": sym[:-3].upper(), "name": name, "sector": x.get("sectorDisp") or x.get("sector") or "", "exchange": "NSE", "source": "live"})
            elif sym.endswith(".BO") and exch in ("BSE", "BOM"):
                out.append({"symbol": sym.upper(), "name": name, "sector": x.get("sectorDisp") or x.get("sector") or "", "exchange": "BSE", "source": "live"})
    except Exception:  # noqa: BLE001  offline, blocked or rate limited: local results still work
        out = []
    out = out[:limit]
    if out:
        _live_cache[key] = (time.time(), out)
    return out


async def search(q: str, limit: int = 10, live: bool = True) -> list[dict]:
    local = search_local(q, limit)
    qn = q.strip()
    weak = len(local) < min(limit, 5) or (local and score_of(local[0], qn) < 80)
    if live and len(qn) >= 2 and weak:
        seen = {r["symbol"] for r in local}
        local = local + [r for r in await search_live(qn) if r["symbol"] not in seen]
    return local[:limit]


def score_of(row: dict, q: str) -> float:
    e = next((x for x in universe() if x.symbol == row["symbol"]), None)
    ql = q.lower()
    return score(e, ql, _norm(ql), _norm(ql).split()) if e else 0
