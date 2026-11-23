"""NSE trading calendar (Asia/Kolkata).

Holidays are a curated static table (equity segment trading holidays, weekdays only).
It MUST be refreshed each year from the NSE circular. For years not in the table the
calendar falls back to weekday-only and `holidays_known(year)` returns False so the
UI/data-quality report can say so instead of silently guessing.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OPEN_T = time(9, 15)
CLOSE_T = time(15, 30)

NSE_HOLIDAYS: dict[int, set[date]] = {
    2025: {
        date(2025, 2, 26), date(2025, 3, 14), date(2025, 3, 31), date(2025, 4, 10),
        date(2025, 4, 14), date(2025, 4, 18), date(2025, 5, 1), date(2025, 8, 15),
        date(2025, 8, 27), date(2025, 10, 2), date(2025, 10, 21), date(2025, 10, 22),
        date(2025, 11, 5), date(2025, 12, 25),
    },
    2026: {
        date(2026, 1, 26), date(2026, 3, 3), date(2026, 3, 26), date(2026, 3, 31),
        date(2026, 4, 3), date(2026, 4, 14), date(2026, 5, 1), date(2026, 5, 28),
        date(2026, 6, 26), date(2026, 9, 14), date(2026, 10, 2), date(2026, 10, 20),
        date(2026, 11, 10), date(2026, 11, 24), date(2026, 12, 25),
    },
}


def holidays_known(year: int) -> bool:
    return year in NSE_HOLIDAYS


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in NSE_HOLIDAYS.get(d.year, set())


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def last_completed_session(now: datetime | None = None) -> date:
    """Most recent trading day whose session has closed (as of `now`)."""
    now = (now or datetime.now(IST)).astimezone(IST)
    d = now.date()
    if is_trading_day(d) and now.time() >= CLOSE_T:
        return d
    return previous_trading_day(d)


def market_status(now: datetime | None = None) -> dict:
    now = (now or datetime.now(IST)).astimezone(IST)
    d = now.date()
    if not is_trading_day(d):
        state, nxt = "closed", datetime.combine(next_trading_day(d), OPEN_T, IST)
    elif now.time() < OPEN_T:
        state, nxt = "pre-open", datetime.combine(d, OPEN_T, IST)
    elif now.time() < CLOSE_T:
        state, nxt = "open", datetime.combine(d, CLOSE_T, IST)
    else:
        state, nxt = "closed", datetime.combine(next_trading_day(d), OPEN_T, IST)
    return {
        "state": state,
        "now_ist": now.isoformat(),
        "next_change_ist": nxt.isoformat(),
        "holidays_known": holidays_known(d.year),
    }


def trading_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out
