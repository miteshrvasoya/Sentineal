"""Data-quality report for stored bars. Never silently fills gaps: it reports them."""
from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from app.data import calendar as cal


def quality_report(df: pd.DataFrame, interval: str, now: datetime | None = None) -> dict:
    """`df` is indexed by UTC epoch seconds with OHLCV + adj_close + source columns."""
    now = now or datetime.now(UTC)
    rep: dict = {"interval": interval, "bars": len(df), "issues": [], "checks": {}}
    if df.empty:
        rep["issues"].append({"severity": "error", "kind": "no_data", "detail": "no stored bars"})
        return rep
    idx = pd.to_datetime(df.index, unit="s", utc=True)
    first, last = idx.min(), idx.max()
    rep.update(first=first.isoformat(), last=last.isoformat(), sources=sorted(set(df["source"])) if "source" in df else [])

    bad = ((df["high"] < df[["open", "close", "low"]].max(axis=1) - 1e-9)
           | (df["low"] > df[["open", "close", "high"]].min(axis=1) + 1e-9) | (df[["open", "high", "low", "close"]] <= 0).any(axis=1))
    rep["checks"]["ohlc_violations"] = int(bad.sum())
    rep["checks"]["zero_volume_bars"] = int((df["volume"] == 0).sum())
    if bad.any():
        rep["issues"].append({"severity": "error", "kind": "ohlc_violation", "detail": f"{int(bad.sum())} bars"})
    if len(rep.get("sources", [])) > 1:
        rep["issues"].append({"severity": "warn", "kind": "mixed_sources",
                              "detail": f"bars from {rep['sources']}: adjustment conventions may differ"})

    if interval == "1d":
        days = pd.Series(idx.tz_convert(cal.IST).date)
        have = set(days)
        expected = cal.trading_days(days.min(), days.max())
        missing = [d for d in expected if d not in have]
        extra = sorted(d for d in have if not cal.is_trading_day(d))
        rep["checks"].update(expected_days=len(expected), missing_days=len(missing), non_trading_days=len(extra))
        if missing:
            rep["issues"].append({"severity": "warn", "kind": "missing_days",
                                  "detail": f"{len(missing)} trading days missing", "dates": [d.isoformat() for d in missing[:50]]})
        if extra:
            rep["issues"].append({"severity": "info", "kind": "non_trading_day_bars",
                                  "detail": "bars on weekends/holidays (special sessions or calendar error)",
                                  "dates": [d.isoformat() for d in extra[:20]]})
        if not cal.holidays_known(days.max().year):
            rep["issues"].append({"severity": "warn", "kind": "calendar_unknown_year",
                                  "detail": f"holiday table missing for {days.max().year}; missing-day check is weekday-only"})
        stale_ref: date = cal.last_completed_session(now)
        rep["checks"]["stale_days"] = len(cal.trading_days(days.max(), stale_ref)) - 1 if days.max() < stale_ref else 0
        if rep["checks"]["stale_days"] > 0:
            rep["issues"].append({"severity": "warn", "kind": "stale", "detail": f"latest bar {days.max()} is behind {stale_ref}"})

    # Outliers: large close-to-close moves. A raw jump that adj_close smooths = unadjusted corporate action.
    ret = np.log(df["close"]).diff()
    adj_ret = np.log(df["adj_close"]).diff()
    # Robust threshold (MAD): a plain std would be inflated by the very outlier we look for.
    mad = 1.4826 * (ret - ret.median()).abs().median()
    big = ret.abs() > max(0.12, 8 * mad) if len(df) > 20 else ret.abs() > 0.2
    outliers = []
    for ts in df.index[big.fillna(False)]:
        kind = "possible_corporate_action" if abs(adj_ret.loc[ts]) < abs(ret.loc[ts]) / 2 else "price_jump"
        outliers.append({"date": pd.Timestamp(ts, unit="s", tz="UTC").tz_convert(cal.IST).date().isoformat(),
                         "log_return": round(float(ret.loc[ts]), 4), "kind": kind})
    rep["checks"]["outliers"] = len(outliers)
    if outliers:
        rep["issues"].append({"severity": "warn", "kind": "outliers", "detail": f"{len(outliers)} extreme moves", "items": outliers[:20]})
    rep["ok"] = not any(i["severity"] == "error" for i in rep["issues"])
    return rep
