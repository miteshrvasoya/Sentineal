"""Fundamentals math checked against hand-computed numbers."""
import math

import pandas as pd
import pytest

from app.features import fundamentals as fd
from app.features.fundamentals import Inputs, Year


def frames(cur: dict, prev: dict):
    """yfinance-shaped statements: rows = line items, columns = period ends (any order)."""
    cols = [pd.Timestamp("2024-03-31"), pd.Timestamp("2025-03-31")]            # deliberately oldest first
    def df(keys):
        rows = {k: [prev.get(k), cur.get(k)] for k in keys if k in cur or k in prev}
        return pd.DataFrame(rows, index=cols).T
    income = df(["Total Revenue", "Gross Profit", "Operating Income", "EBIT", "EBITDA", "Net Income", "Interest Expense"])
    balance = df(["Total Assets", "Current Assets", "Current Liabilities", "Total Liabilities Net Minority Interest", "Total Debt",
                  "Cash And Cash Equivalents", "Stockholders Equity", "Retained Earnings", "Ordinary Shares Number"])
    cash = df(["Operating Cash Flow", "Capital Expenditure"])
    return income, balance, cash


def test_extract_inputs_handles_order_aliases_missing_and_capex_sign():
    cur = {"Total Revenue": 1000.0, "Net Income": 100.0, "Total Assets": 1000.0, "Operating Cash Flow": 150.0,
           "Capital Expenditure": -40.0, "Total Debt": 300.0, "EBITDA": float("nan")}
    prev = {"Total Revenue": 800.0, "Net Income": 80.0, "Total Assets": 900.0}
    i = fd.extract_inputs("TST", {"currentPrice": 100, "marketCap": 1000, "sector": "Energy", "trailingEps": 5, "bookValue": 50, "dividendRate": 2},
                          *frames(cur, prev), fetched_at=7)
    assert i.cur.revenue == 1000.0 and i.prev.revenue == 800.0                  # newest column used as current
    assert i.cur.capex == 40.0 and i.cur.fcf == 110.0                           # sign normalised, FCF = CFO - capex
    assert i.cur.ebitda is None and i.cur.gross_profit is None                  # NaN / missing -> None, never 0
    assert (i.price, i.sector, i.eps, i.bvps, i.dividend_rate) == (100.0, "Energy", 5.0, 50.0, 2.0)
    j = Inputs.from_dict(i.to_dict())
    assert j.cur.fcf == 110.0 and j.prev.net_income == 80.0 and j.symbol == "TST"


def test_extract_with_no_statements_still_returns_inputs():
    i = fd.extract_inputs("X", {"previousClose": 10.0}, None, None, None)
    assert i.price == 10.0 and i.prev is None and i.cur.revenue is None


def base_inputs():
    cur = Year(revenue=1000, gross_profit=400, operating_income=150, ebit=150, ebitda=200, net_income=100, total_assets=1000,
               current_assets=400, current_liabilities=200, total_liabilities=600, total_debt=300, cash=100, equity=500,
               retained_earnings=300, shares=100, cfo=150, capex=40)
    prev = Year(revenue=800, net_income=80)
    return Inputs("T", sector="Industrials", price=100, market_cap=1000, shares=100, eps=5, bvps=50, dividend_rate=2, cur=cur, prev=prev)


def test_ratios_hand_computed():
    r = fd.ratios(base_inputs())
    assert r["pe"] == 20 and r["pb"] == 2
    assert r["ev"] == 1200 and r["ev_ebitda"] == 6                             # 1000 + 300 debt - 100 cash
    assert r["roe"] == pytest.approx(0.2) and r["roce"] == pytest.approx(150 / 800)
    assert r["debt_equity"] == pytest.approx(0.6)
    assert (r["gross_margin"], r["operating_margin"], r["net_margin"]) == (pytest.approx(0.4), pytest.approx(0.15), pytest.approx(0.1))
    assert r["revenue_growth"] == pytest.approx(0.25) and r["earnings_growth"] == pytest.approx(0.25)
    assert r["dividend_yield"] == pytest.approx(0.02) and r["peg"] == pytest.approx(20 / 25)
    assert r["fcf_margin"] == pytest.approx(0.11)


def test_ratios_return_none_instead_of_nonsense():
    i = base_inputs()
    i.eps, i.cur.equity, i.cur.ebitda = -2.0, -50.0, 0.0                          # loss-making, negative equity
    r = fd.ratios(i)
    assert r["pe"] is None and r["roe"] is None and r["debt_equity"] is None and r["ev_ebitda"] is None and r["peg"] is None


def healthy():
    prev = Year(net_income=50, total_assets=1000, cfo=60, total_debt=300, current_assets=400, current_liabilities=300,
                gross_profit=300, revenue=900, shares=100)
    cur = Year(net_income=100, total_assets=1050, cfo=150, total_debt=280, current_assets=500, current_liabilities=300,
               gross_profit=400, revenue=1000, shares=100)
    return Inputs("H", cur=cur, prev=prev)


def test_piotroski_perfect_and_failures_and_partial():
    p = fd.piotroski(healthy())
    assert p["score"] == 9 and p["evaluated"] == 9 and p["reading"].startswith("strong")
    i = healthy()
    i.cur.shares, i.cur.cfo = 120, 80                                              # dilution; cash flow below net income
    q = fd.piotroski(i)
    res = {c["id"]: c["result"] for c in q["criteria"]}
    assert res["no_dilution"] == "fail" and res["accruals"] == "fail" and q["score"] == 7
    i.prev = None
    r = fd.piotroski(i)
    assert r["evaluated"] == 3 and r["reading"] == "not enough data"
    assert {c["result"] for c in r["criteria"] if c["id"] in ("roa_improving", "leverage_down")} == {"na"}


def test_altman_hand_computed_and_not_applicable_for_banks():
    i = Inputs("T", sector="Industrials", market_cap=1200, cur=Year(total_assets=1000, current_assets=400, current_liabilities=200,
               retained_earnings=300, ebit=150, total_liabilities=600, revenue=1100))
    a = fd.altman_z(i)
    assert a["z"] == pytest.approx(3.455, abs=1e-3) and a["zone"] == "safe"       # 0.24+0.42+0.495+1.2+1.1
    i.cur.ebit = -600
    assert fd.altman_z(i)["zone"] == "distress"
    bank = Inputs("B", sector="Financial Services", market_cap=1, cur=Year())
    assert fd.altman_z(bank)["applicable"] is False and fd.altman_z(bank)["z"] is None
    missing = Inputs("M", sector="Energy", cur=Year(total_assets=1000))
    assert "missing inputs" in fd.altman_z(missing)["note"]


def test_graham_number():
    g = fd.graham_number(5, 20, 40)
    assert g["value"] == pytest.approx(math.sqrt(2250), abs=0.01) and g["price_vs_graham"] == pytest.approx(40 / 47.4342 - 1, abs=1e-3)
    assert fd.graham_number(-1, 20, 40)["value"] is None


def test_dcf_hand_computed():
    d = fd.dcf(100, 10, 150, r=0.10, g1=0.10, g2=0.03, years=2)
    tv = 121 * 1.03 / 0.07
    expect = (100 + 100 + tv / 1.21) / 10
    assert d["intrinsic_per_share"] == pytest.approx(expect) and d["pv_stage1"] == pytest.approx(200)
    assert d["upside_pct"] == pytest.approx(round((expect / 150 - 1) * 100, 1)) and d["terminal_share_pct"] > 80


def test_dcf_validation_and_unusable_inputs():
    with pytest.raises(ValueError, match="greater than terminal"):
        fd.dcf(100, 10, 100, r=0.05, g1=0.1, g2=0.05)
    with pytest.raises(ValueError):
        fd.dcf(100, 10, 100, years=0)
    assert fd.dcf(-5, 10, 100)["intrinsic_per_share"] is None
    assert fd.dcf(100, 0, 100)["intrinsic_per_share"] is None


def test_dcf_sensitivity_grid_centre_matches_base_and_monotonic():
    grid = fd.dcf_sensitivity(100, 10, 100, 0.12, 0.08, 0.05, 5)
    base = fd.dcf(100, 10, 100, 0.12, 0.08, 0.05, 5)["intrinsic_per_share"]
    assert any(abs(g["intrinsic"] - base) < 1e-9 for g in grid)
    lo = [g for g in grid if g["r"] == 0.14 and g["g1"] == 0.08][0]["intrinsic"]
    hi = [g for g in grid if g["r"] == 0.10 and g["g1"] == 0.08][0]["intrinsic"]
    assert hi > lo                                                                # higher discount rate -> lower value


def test_default_assumptions_clamped():
    def i(g):
        return Inputs("T", cur=Year(revenue=100 * (1 + g)), prev=Year(revenue=100)) if g is not None else Inputs("T")
    assert fd.default_dcf_assumptions(i(0.5))["g1"] == 0.20 and fd.default_dcf_assumptions(i(-0.1))["g1"] == 0.02
    assert fd.default_dcf_assumptions(i(None))["g1"] == 0.08 and fd.default_dcf_assumptions(i(0.1))["g1"] == 0.1


def test_sector_percentiles():
    peers = [{"pe": v} for v in (10, 20, 30, 40)]
    p = fd.sector_percentiles({"pe": 15}, peers)
    assert p["pe"]["percentile"] == 25.0 and p["pe"]["peers"] == 4 and p["pe"]["higher_is_better"] is False
    assert fd.sector_percentiles({"pe": 20}, peers)["pe"]["percentile"] == 37.5    # one below, one tie counts half
    assert fd.sector_percentiles({"pe": 15}, peers[:2])["pe"]["percentile"] is None   # too few peers: no fake precision
    assert fd.sector_percentiles({"pe": None}, peers)["pe"]["percentile"] is None
