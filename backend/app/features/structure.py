"""Market structure / smart-money concepts, volume profile, Fibonacci, pivots, S/R zones.

Point-in-time rule: a swing at bar i needs `k` bars on each side, so it is only *known* at
bar i+k (`confirmed`). Events (BOS/CHoCH/sweeps/FVG/order blocks) are generated bar-by-bar
using swings confirmed up to that bar only. Later-resolved fields (`invalidated`, `filled`)
are annotated in a separate pass and flagged as such.

These are heuristics from a popular trading vocabulary, not validated predictors.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering

from app.features.volatility import atr


@dataclass
class Swing:
    i: int
    kind: str          # "high" | "low"
    price: float
    confirmed: int     # bar index at which this swing became known
    label: str = ""    # HH / LH / HL / LL


def raw_swings(df: pd.DataFrame, k: int = 3) -> list[Swing]:
    """Fractal swings: high[i] above the k bars before and >= the k bars after (mirror for lows)."""
    h, lo = df["high"].to_numpy(), df["low"].to_numpy()
    out: list[Swing] = []
    for i in range(k, len(df) - k):
        if h[i] > h[i - k:i].max() and h[i] >= h[i + 1:i + k + 1].max():
            out.append(Swing(i, "high", float(h[i]), i + k))
        if lo[i] < lo[i - k:i].min() and lo[i] <= lo[i + 1:i + k + 1].min():
            out.append(Swing(i, "low", float(lo[i]), i + k))
    return sorted(out, key=lambda s: (s.confirmed, s.i))


def _push(seq: list[Swing], s: Swing) -> bool:
    """Online zig-zag cleaning: alternate highs/lows; of two consecutive same-kind swings keep the more extreme."""
    if seq and seq[-1].kind == s.kind:
        better = s.price > seq[-1].price if s.kind == "high" else s.price < seq[-1].price
        if better:
            seq[-1] = s
            return True
        return False
    seq.append(s)
    return True


def label_swings(seq: list[Swing]) -> None:
    last: dict[str, Swing] = {}
    for s in seq:
        p = last.get(s.kind)
        if p:
            up = s.price > p.price
            s.label = ("HH" if up else "LH") if s.kind == "high" else ("HL" if up else "LL")
        last[s.kind] = s


def classify_trend(seq: list[Swing]) -> str:
    hi = [s for s in seq if s.kind == "high"][-2:]
    lo = [s for s in seq if s.kind == "low"][-2:]
    if len(hi) < 2 or len(lo) < 2:
        return "undetermined"
    if hi[1].price > hi[0].price and lo[1].price > lo[0].price:
        return "uptrend"
    if hi[1].price < hi[0].price and lo[1].price < lo[0].price:
        return "downtrend"
    return "range"


def structure_events(df: pd.DataFrame, k: int = 3) -> tuple[list[dict], list[Swing], dict]:
    """Walk bars in time order. Returns (events, final cleaned swings, order-block seeds)."""
    c, h, lo = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    raw = raw_swings(df, k)
    seq: list[Swing] = []
    ptr = 0
    events: list[dict] = []
    trend: str | None = None
    hi_lvl: Swing | None = None   # active (unbroken) swing high / low
    lo_lvl: Swing | None = None
    swept_hi = swept_lo = -1
    for t in range(len(df)):
        while ptr < len(raw) and raw[ptr].confirmed <= t:
            s = raw[ptr]
            ptr += 1
            if _push(seq, s):
                if s.kind == "high":
                    hi_lvl = s
                else:
                    lo_lvl = s
        if hi_lvl is not None and c[t] > hi_lvl.price:
            kind = "CHoCH" if trend == "down" else "BOS"
            events.append({"i": t, "kind": kind, "dir": "bull", "level": hi_lvl.price, "swing_i": hi_lvl.i})
            trend, hi_lvl = "up", None
        elif lo_lvl is not None and c[t] < lo_lvl.price:
            kind = "CHoCH" if trend == "up" else "BOS"
            events.append({"i": t, "kind": kind, "dir": "bear", "level": lo_lvl.price, "swing_i": lo_lvl.i})
            trend, lo_lvl = "down", None
        else:
            if hi_lvl is not None and h[t] > hi_lvl.price >= c[t] and hi_lvl.i != swept_hi:
                events.append({"i": t, "kind": "sweep_high", "dir": "bear", "level": hi_lvl.price, "swing_i": hi_lvl.i})
                swept_hi = hi_lvl.i
            if lo_lvl is not None and lo[t] < lo_lvl.price <= c[t] and lo_lvl.i != swept_lo:
                events.append({"i": t, "kind": "sweep_low", "dir": "bull", "level": lo_lvl.price, "swing_i": lo_lvl.i})
                swept_lo = lo_lvl.i
    label_swings(seq)
    return events, seq, {}


def order_blocks(df: pd.DataFrame, events: list[dict], lookback_candles: int = 5) -> list[dict]:
    """OB = last opposite-colour candle before the leg that broke structure (BOS/CHoCH)."""
    o, c, h, lo = (df[x].to_numpy() for x in ("open", "close", "high", "low"))
    out = []
    for e in events:
        if e["kind"] not in ("BOS", "CHoCH"):
            continue
        s, t = e["swing_i"], e["i"]
        if e["dir"] == "bull":
            origin = s + int(np.argmin(lo[s:t + 1]))
            cand = [j for j in range(origin, max(origin - lookback_candles, -1), -1) if c[j] < o[j]]
        else:
            origin = s + int(np.argmax(h[s:t + 1]))
            cand = [j for j in range(origin, max(origin - lookback_candles, -1), -1) if c[j] > o[j]]
        if not cand:
            continue
        j = cand[0]
        out.append({"i": j, "formed": t, "dir": e["dir"], "low": float(lo[j]), "high": float(h[j]), "event": e["kind"]})
    return out


def fair_value_gaps(df: pd.DataFrame, min_gap_atr: float = 0.1) -> list[dict]:
    """3-candle imbalance: bullish if low[i] > high[i-2]; bearish if high[i] < low[i-2]. Known at bar i."""
    h, lo = df["high"].to_numpy(), df["low"].to_numpy()
    a = atr(df).to_numpy()
    out = []
    for i in range(2, len(df)):
        if np.isnan(a[i]):
            continue
        if lo[i] > h[i - 2] and lo[i] - h[i - 2] >= min_gap_atr * a[i]:
            out.append({"i": i - 1, "formed": i, "dir": "bull", "low": float(h[i - 2]), "high": float(lo[i])})
        elif h[i] < lo[i - 2] and lo[i - 2] - h[i] >= min_gap_atr * a[i]:
            out.append({"i": i - 1, "formed": i, "dir": "bear", "low": float(h[i]), "high": float(lo[i - 2])})
    return out


def annotate_resolution(df: pd.DataFrame, zones: list[dict], mode: str) -> None:
    """Add `resolved` (bar index or None). FVG: fully filled by price. OB: close through the far side.
    This uses bars AFTER formation by design (it describes what happened later)."""
    c, h, lo = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    for z in zones:
        z["resolved"] = None
        for u in range(z["formed"] + 1, len(df)):
            if mode == "fvg":
                hit = lo[u] <= z["low"] if z["dir"] == "bull" else h[u] >= z["high"]
            else:
                hit = c[u] < z["low"] if z["dir"] == "bull" else c[u] > z["high"]
            if hit:
                z["resolved"] = u
                break


def dealing_range(seq: list[Swing], close: float) -> dict | None:
    hi = next((s for s in reversed(seq) if s.kind == "high"), None)
    lo = next((s for s in reversed(seq) if s.kind == "low"), None)
    if not hi or not lo or hi.price <= lo.price:
        return None
    eq = (hi.price + lo.price) / 2
    return {"high": hi.price, "low": lo.price, "equilibrium": eq,
            "position_pct": round((close - lo.price) / (hi.price - lo.price) * 100, 1),
            "zone": ("above_range" if close > hi.price else "below_range" if close < lo.price
                     else "premium" if close > eq else "discount" if close < eq else "equilibrium")}


def fibonacci(seq: list[Swing]) -> dict | None:
    """Retracements/extensions from the latest confirmed leg (last two opposite swings)."""
    if len(seq) < 2:
        return None
    b, a = seq[-1], seq[-2]
    hi, lo = max(a.price, b.price), min(a.price, b.price)
    rng = hi - lo
    up = b.kind == "high"  # last leg went up: retrace downward from the high
    ratios = (0.236, 0.382, 0.5, 0.618, 0.786)
    retr = {str(r): (hi - r * rng) if up else (lo + r * rng) for r in ratios}
    ext = {str(r): (hi + (r - 1) * rng) if up else (lo - (r - 1) * rng) for r in (1.272, 1.618)}
    return {"leg": "up" if up else "down", "start": a.price, "end": b.price,
            "start_i": a.i, "end_i": b.i, "retracements": retr, "extensions": ext}


def pivot_set(h: float, l: float, c: float) -> dict:
    """Classic, Fibonacci and Camarilla pivots from one completed period's H/L/C."""
    p, r = (h + l + c) / 3, h - l
    return {
        "classic": {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + r, "S2": p - r,
                    "R3": h + 2 * (p - l), "S3": l - 2 * (h - p)},
        "fibonacci": {"P": p, "R1": p + .382 * r, "R2": p + .618 * r, "R3": p + r,
                      "S1": p - .382 * r, "S2": p - .618 * r, "S3": p - r},
        "camarilla": {f"{s}{n}": c + sign * r * 1.1 / d for n, d in ((1, 12), (2, 6), (3, 4), (4, 2))
                      for s, sign in (("R", 1), ("S", -1))},
    }


def pivots(df: pd.DataFrame) -> dict:
    """Levels for the NEXT session/week/month from the last completed period (no look-ahead)."""
    ist = df.index.tz_convert("Asia/Kolkata")
    out: dict = {}
    daily = (df.index[-1] - df.index[0]) > pd.Timedelta(days=2) and (len(df) < 2 or df.index.to_series().diff().median() >= pd.Timedelta(hours=20))
    if daily:
        last = df.iloc[-1]
        out["daily"] = {"period": ist[-1].date().isoformat(), **pivot_set(last.high, last.low, last.close)}
    else:
        day = pd.Series(ist.date, index=df.index)
        days = sorted(set(day))
        prev = df[day == (days[-2] if len(days) > 1 else days[-1])]
        out["daily"] = {"period": str(days[-2] if len(days) > 1 else days[-1]),
                        **pivot_set(prev.high.max(), prev.low.min(), prev.close.iloc[-1])}
    for name, rule in (("weekly", "W-FRI"), ("monthly", "ME")):
        g = df.tz_convert("Asia/Kolkata").resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
        if len(g) >= 2:  # last row is the in-progress period -> use the one before it
            r = g.iloc[-2]
            out[name] = {"period": g.index[-2].date().isoformat(), **pivot_set(r.high, r.low, r.close)}
    return out


def sr_zones(seq: list[Swing], df: pd.DataFrame, max_swings: int = 40, width_atr: float = 1.0,
             max_zones: int = 8) -> list[dict]:
    """Cluster recent swing prices (complete-linkage, so no zone is wider than width_atr * ATR; plain
    DBSCAN chains neighbouring swings into one huge zone). Zone = [min, max] of the cluster."""
    sw = seq[-max_swings:]
    a = atr(df).dropna()
    if len(sw) < 3 or a.empty:
        return []
    prices = np.array([s.price for s in sw]).reshape(-1, 1)
    labels = AgglomerativeClustering(n_clusters=None, distance_threshold=float(width_atr * a.iloc[-1]),
                                     linkage="complete").fit_predict(prices)
    last = float(df["close"].iloc[-1])
    zones = []
    for lab in sorted(set(labels)):
        p = prices[labels == lab, 0]
        if len(p) < 2:
            continue
        lo, hi = float(p.min()), float(p.max())
        zones.append({"low": lo, "high": hi, "touches": int(len(p)),
                      "type": "support" if hi < last else "resistance" if lo > last else "inside"})
    return sorted(zones, key=lambda z: -z["touches"])[:max_zones]


def volume_profile(df: pd.DataFrame, bins: int = 48, window: int = 120, value_area: float = 0.7) -> dict | None:
    """Volume at price over the last `window` bars. Each bar's volume is spread uniformly over its range."""
    d = df.iloc[-window:]
    if d.empty or d["volume"].sum() <= 0:
        return None
    lo, hi = float(d["low"].min()), float(d["high"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    vol = np.zeros(bins)
    for h_, l_, v in zip(d["high"], d["low"], d["volume"], strict=True):
        if h_ == l_:
            vol[min(int((h_ - lo) / (hi - lo) * bins), bins - 1)] += v
            continue
        ov = np.clip(edges[1:], l_, h_) - np.clip(edges[:-1], l_, h_)
        vol += v * ov / (h_ - l_)
    poc = int(np.argmax(vol))
    a = b = poc
    acc, target = vol[poc], value_area * vol.sum()
    while acc < target and (a > 0 or b < bins - 1):
        up = vol[b + 1] if b < bins - 1 else -1
        dn = vol[a - 1] if a > 0 else -1
        if up >= dn:
            b += 1
            acc += vol[b]
        else:
            a -= 1
            acc += vol[a]
    sm = np.convolve(vol, np.ones(3) / 3, mode="same")
    mean = vol.mean()
    center = (edges[:-1] + edges[1:]) / 2
    hvn = [float(center[i]) for i in range(1, bins - 1) if sm[i] >= sm[i - 1] and sm[i] > sm[i + 1] and sm[i] >= 1.2 * mean]
    lvn = [float(center[i]) for i in range(1, bins - 1) if sm[i] <= sm[i - 1] and sm[i] < sm[i + 1] and sm[i] <= 0.6 * mean]
    return {"window": len(d), "poc": float(center[poc]), "vah": float(edges[b + 1]), "val": float(edges[a]),
            "hvn": hvn, "lvn": lvn,
            "bins": [{"low": float(edges[i]), "high": float(edges[i + 1]), "volume": float(vol[i])} for i in range(bins)]}


def wyckoff_heuristic(df: pd.DataFrame, window: int = 60) -> dict:
    """HEURISTIC ONLY. Flags accumulation-like / distribution-like behaviour inside a trading range:
    narrow net drift, plus up-volume vs down-volume imbalance and close position in the range."""
    d = df.iloc[-window:]
    if len(d) < window:
        return {"label": "insufficient_data", "evidence": [], "heuristic": True}
    a = atr(df).iloc[-1]
    rng = d["high"].max() - d["low"].min()
    drift = abs(d["close"].iloc[-1] - d["close"].iloc[0])
    in_range = bool(rng > 0 and drift < 0.35 * rng and (rng / a) < 12 if a == a and a > 0 else False)
    up = d["volume"].where(d["close"] > d["close"].shift(1), 0).sum()
    dn = d["volume"].where(d["close"] < d["close"].shift(1), 0).sum()
    ratio = float(up / dn) if dn > 0 else float("inf")
    pos = float((d["close"].iloc[-1] - d["low"].min()) / rng) if rng > 0 else 0.5
    ev = [f"range-bound: {in_range}", f"up/down volume ratio {ratio:.2f}", f"close at {pos:.0%} of range"]
    label = "none"
    if in_range and ratio > 1.2 and pos < 0.6:
        label = "accumulation_like"
    elif in_range and ratio < 0.83 and pos > 0.4:
        label = "distribution_like"
    return {"label": label, "evidence": ev, "heuristic": True}


def analyze(df: pd.DataFrame, k: int = 3, profile_window: int = 120) -> dict:
    """Full structure analysis of a UTC-indexed OHLCV frame. Indices are converted to epoch seconds."""
    ts = [int(x.timestamp()) for x in df.index]
    events, seq, _ = structure_events(df, k)
    obs, fvgs = order_blocks(df, events), fair_value_gaps(df)
    annotate_resolution(df, obs, "ob")
    annotate_resolution(df, fvgs, "fvg")

    def tt(i: int | None) -> int | None:
        return None if i is None else ts[i]

    def conv(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
        return [{**x, **{f"{kk}_t": tt(x[kk]) for kk in keys if kk in x}} for x in items]

    close = float(df["close"].iloc[-1])
    return {
        "k": k, "trend": classify_trend(seq),
        "swings": [{**asdict(s), "t": ts[s.i], "confirmed_t": ts[s.confirmed]} for s in seq],
        "events": conv(events, ("i", "swing_i")),
        "order_blocks": conv(obs, ("i", "formed", "resolved")),
        "fvg": conv(fvgs, ("i", "formed", "resolved")),
        "dealing_range": dealing_range(seq, close),
        "fibonacci": fibonacci(seq),
        "pivots": pivots(df),
        "sr_zones": sr_zones(seq, df),
        "volume_profile": volume_profile(df, window=profile_window),
        "wyckoff": wyckoff_heuristic(df),
    }
