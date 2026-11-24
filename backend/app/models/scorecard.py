"""Rules-based Signal Scorecard: transparent sub-scores, every one explained by the rules that fired.

Each rule votes +1 / 0 / -1 with a plain-English reason and the value it looked at. A sub-score is the average vote
of the rules that had data (shown on a -100..+100 scale). Missing data means the rule (or whole sub-score) is left
out and the weights of the rest are renormalised. This is a DESCRIPTION of the current state, not a forecast and
not advice; thresholds are conventional rules of thumb, not tuned or validated.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

WEIGHTS = {"trend": 0.25, "momentum": 0.20, "volume_flow": 0.15, "volatility": 0.10, "sentiment": 0.15, "valuation": 0.15}
LABELS = {"trend": "Trend", "momentum": "Momentum", "volume_flow": "Volume / flow", "volatility": "Volatility (stability)",
          "sentiment": "News sentiment", "valuation": "Valuation & quality"}


def _r(rid: str, text: str, value: Any, vote: int, why: str) -> dict[str, Any]:
    v = None if value is None else (round(float(value), 4) if isinstance(value, int | float) else value)
    return {"id": rid, "rule": text, "value": v, "vote": vote, "why": why}


def _num(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def trend_rules(last: pd.Series, close: float, structure_trend: str | None) -> list[dict]:
    out = []
    e50, e20, s200 = _num(last.get("ema_50")), _num(last.get("ema_20")), _num(last.get("sma_200"))
    if e50 is not None:
        out.append(_r("close_vs_ema50", "Price above its 50-day EMA", close - e50, 1 if close > e50 else -1,
                      "Price above the medium-term average suggests an uptrend; below suggests a downtrend."))
    if e20 is not None and e50 is not None:
        out.append(_r("ema20_vs_ema50", "20-day EMA above 50-day EMA", e20 - e50, 1 if e20 > e50 else -1,
                      "Short-term average above the longer one means recent prices are higher than the trend."))
    if s200 is not None:
        out.append(_r("close_vs_sma200", "Price above its 200-day average", close - s200, 1 if close > s200 else -1,
                      "The 200-day average is the classic long-term trend line."))
    adx, pdi, mdi = _num(last.get("adx")), _num(last.get("plus_di")), _num(last.get("minus_di"))
    if adx is not None and pdi is not None and mdi is not None:
        vote = 0 if adx < 25 else (1 if pdi > mdi else -1)
        out.append(_r("adx_direction", "ADX above 25 with +DI vs -DI giving direction", adx, vote,
                      "ADX measures trend strength; below 25 the trend is weak so this rule abstains."))
    d = _num(last.get("supertrend_dir"))
    if d is not None:
        out.append(_r("supertrend", "Supertrend direction", d, 1 if d > 0 else -1, "Supertrend flips when price closes beyond its ATR band."))
    if structure_trend in ("uptrend", "downtrend", "range"):
        out.append(_r("structure", "Swing structure (higher highs/lows or lower highs/lows)", structure_trend,
                      {"uptrend": 1, "downtrend": -1, "range": 0}[structure_trend], "Based on the last two confirmed swing highs and lows."))
    return out


def momentum_rules(last: pd.Series) -> list[dict]:
    out = []
    h = _num(last.get("macd_hist"))
    if h is not None:
        out.append(_r("macd_hist", "MACD histogram positive", h, 1 if h > 0 else -1, "Positive means the fast average is above the slow one."))
    rsi = _num(last.get("rsi"))
    if rsi is not None:
        vote = 0 if (rsi > 75 or rsi < 25) else (1 if rsi >= 50 else -1)
        out.append(_r("rsi", "RSI above 50 (but abstain when stretched beyond 75 or 25)", rsi, vote,
                      "RSI above 50 means gains have outweighed losses recently; extremes are stretched, so the rule abstains."))
    roc = _num(last.get("roc"))
    if roc is not None:
        out.append(_r("roc", "12-bar rate of change positive", roc, 1 if roc > 0 else -1, "Plain price change over 12 bars."))
    k, dd = _num(last.get("stoch_k")), _num(last.get("stoch_d"))
    if k is not None and dd is not None:
        out.append(_r("stoch", "Stochastic %K above %D", k - dd, 1 if k > dd else -1, "%K crossing above %D is a short-term momentum turn up."))
    return out


def volume_rules(last: pd.Series, obv_series: pd.Series | None, up_day: bool | None) -> list[dict]:
    out = []
    cmf = _num(last.get("cmf"))
    if cmf is not None:
        out.append(_r("cmf", "Chaikin money flow beyond +/-0.05", cmf, 1 if cmf > 0.05 else -1 if cmf < -0.05 else 0,
                      "CMF measures whether closes sit near the high of the bar on heavy volume (demand) or near the low (supply)."))
    if obv_series is not None and len(obv_series.dropna()) >= 20:
        o, m = float(obv_series.iloc[-1]), float(obv_series.iloc[-20:].mean())
        out.append(_r("obv", "On-balance volume above its 20-bar average", o - m, 1 if o > m else -1, "OBV rising means volume is accumulating on up-days."))
    rv = _num(last.get("rvol"))
    if rv is not None:
        vote = 0 if rv < 1.5 or up_day is None else (1 if up_day else -1)
        out.append(_r("rvol", "Heavy volume (RVOL >= 1.5) on an up or down day", rv, vote, "Unusually heavy volume gives the day's direction more weight."))
    mfi = _num(last.get("mfi"))
    if mfi is not None:
        out.append(_r("mfi", "Money flow index above 55 / below 45", mfi, 1 if mfi > 55 else -1 if mfi < 45 else 0, "Volume-weighted RSI."))
    return out


def volatility_rules(last: pd.Series) -> list[dict]:
    out = []
    p = _num(last.get("rv_percentile"))
    if p is not None:
        out.append(_r("rv_percentile", "Realised volatility versus its own 1-year history", p, -1 if p > 80 else 1 if p < 30 else 0,
                      "Higher than usual volatility means a wider range of outcomes (more risk); this is a risk gauge, not a direction."))
    a = _num(last.get("atr_pct"))
    if a is not None:
        out.append(_r("atr_pct", "Average daily range as % of price", a, -1 if a > 4 else 1 if a < 1.5 else 0, "Typical daily movement; thresholds suit large-cap daily bars."))
    sq = _num(last.get("ttm_squeeze"))
    if sq == 1.0:
        out.append(_r("squeeze", "Volatility squeeze active", sq, 0, "Compressed volatility often precedes a larger move, but the direction is unknown, so it abstains."))
    return out


def sentiment_rules(s: dict | None) -> list[dict]:
    if not s:
        return []
    out = []
    rw = _num(s.get("recency_weighted"))
    if rw is not None:
        out.append(_r("recency_weighted", "Recency-weighted news sentiment beyond +/-0.15", rw, 1 if rw > 0.15 else -1 if rw < -0.15 else 0,
                      "Recent articles count more (24h half-life)."))
    m = _num(s.get("sent_mom"))
    if m is not None:
        out.append(_r("sent_mom", "Sentiment momentum (short vs long average) positive", m, 1 if m > 0 else -1, "Is sentiment improving or worsening?"))
    return out


def valuation_rules(f: dict | None) -> list[dict]:
    if not f:
        return []
    out = []
    pct = f.get("percentiles", {})
    for key, name in (("pe", "P/E"), ("pb", "P/B")):
        p = (pct.get(key) or {}).get("percentile")
        if p is not None:
            out.append(_r(f"{key}_sector_pct", f"{name} versus sector peers (lower is cheaper)", p, 1 if p <= 33 else -1 if p >= 67 else 0,
                          "Percentile rank among same-sector companies you have loaded."))
    pio = f.get("piotroski") or {}
    if pio.get("evaluated", 0) >= 6:
        s = pio["score"]
        out.append(_r("piotroski", "Piotroski F-score (7+ strong, 3 or less weak)", s, 1 if s >= 7 else -1 if s <= 3 else 0, "Nine accounting health checks."))
    alt = f.get("altman") or {}
    if alt.get("applicable") and alt.get("zone"):
        out.append(_r("altman", "Altman Z zone (safe / grey / distress)", alt.get("z"), {"safe": 1, "grey": 0, "distress": -1}[alt["zone"]],
                      "Bankruptcy-risk score for non-financial companies."))
    g = (f.get("graham") or {}).get("price_vs_graham")
    if g is not None:
        out.append(_r("graham", "Price versus Graham number", g, 1 if g < 0 else -1 if g > 0.5 else 0, "Below the Graham number is conservative-value territory."))
    up = (f.get("dcf") or {}).get("upside_pct")
    if up is not None:
        out.append(_r("dcf", "DCF upside beyond +/-20% (default assumptions)", up, 1 if up > 20 else -1 if up < -20 else 0,
                      "Very assumption-sensitive; treat as a rough cross-check only."))
    return out


def build(feats_last: pd.Series, close: float, *, structure_trend: str | None = None, obv_series: pd.Series | None = None,
          up_day: bool | None = None, sentiment: dict | None = None, fundamentals: dict | None = None) -> dict[str, Any]:
    groups = {
        "trend": trend_rules(feats_last, close, structure_trend), "momentum": momentum_rules(feats_last),
        "volume_flow": volume_rules(feats_last, obv_series, up_day), "volatility": volatility_rules(feats_last),
        "sentiment": sentiment_rules(sentiment), "valuation": valuation_rules(fundamentals),
    }
    subs: dict[str, Any] = {}
    for k, rules in groups.items():
        votes = [r["vote"] for r in rules]
        subs[k] = {"label": LABELS[k], "weight": WEIGHTS[k], "available": bool(rules),
                   "score": round(100 * sum(votes) / len(votes)) if votes else None, "rules": rules,
                   "fired": [r["id"] for r in rules if r["vote"] != 0]}
    avail = {k: v for k, v in subs.items() if v["score"] is not None}
    tw = sum(v["weight"] for v in avail.values())
    comp = round(sum(v["score"] * v["weight"] for v in avail.values()) / tw) if tw else None
    label = None if comp is None else "leaning positive" if comp >= 25 else "leaning negative" if comp <= -25 else "mixed"
    return {"composite": comp, "label": label, "subscores": subs,
            "missing": [LABELS[k] for k, v in subs.items() if v["score"] is None],
            "disclaimer": "Descriptive summary of current conditions from rule-of-thumb thresholds. Not a forecast, not advice."}
