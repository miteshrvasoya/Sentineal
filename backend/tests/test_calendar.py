from datetime import date, datetime

from app.data import calendar as cal


def test_weekend_and_holiday():
    assert not cal.is_trading_day(date(2026, 1, 3))      # Saturday
    assert not cal.is_trading_day(date(2026, 1, 26))     # Republic Day
    assert cal.is_trading_day(date(2026, 1, 27))


def test_previous_next_skip_holidays():
    assert cal.previous_trading_day(date(2026, 1, 27)) == date(2026, 1, 23)  # Fri before weekend+hol
    assert cal.next_trading_day(date(2026, 1, 23)) == date(2026, 1, 27)


def test_market_status_states():
    ist = cal.IST
    assert cal.market_status(datetime(2026, 1, 27, 9, 0, tzinfo=ist))["state"] == "pre-open"
    assert cal.market_status(datetime(2026, 1, 27, 10, 0, tzinfo=ist))["state"] == "open"
    assert cal.market_status(datetime(2026, 1, 27, 15, 30, tzinfo=ist))["state"] == "closed"
    assert cal.market_status(datetime(2026, 1, 24, 11, 0, tzinfo=ist))["state"] == "closed"


def test_last_completed_session():
    ist = cal.IST
    assert cal.last_completed_session(datetime(2026, 1, 27, 12, 0, tzinfo=ist)) == date(2026, 1, 23)
    assert cal.last_completed_session(datetime(2026, 1, 27, 16, 0, tzinfo=ist)) == date(2026, 1, 27)


def test_unknown_year_flagged():
    assert cal.holidays_known(2026) and not cal.holidays_known(2031)
