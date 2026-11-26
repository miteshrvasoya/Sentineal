"""Discover: transparent short/long-term scores, plain-English reasons, honest handling of missing data, loader job, API."""
import time

import pytest

from app import ideas
from app.data import db as dbmod
from app.screener import engine as scr
from tests.test_screener import seed


def row(**kw):
    base = {"symbol": "AAA", "sector": "IT", "bars": 500, "price": 1000.0, "close_vs_sma50": 0.05, "above_sma50": True, "above_sma200": True, "rs_rank_126": 90.0, "rs_rank_63": 85.0,
            "rsi": 58.0, "pct_from_52w_high": -0.04, "rvol": 1.2, "vol_21d_annual": 0.2}
    return base | kw


def test_a_strong_trending_stock_scores_high_for_the_short_term_with_reasons():
    a = ideas.assess_row(None, row(), "short", with_flags=False)
    assert a["score"] >= 90 and a["label"] == "Looks strong" and a["risk"] == "Lower" and a["ranked"]
    joined = " ".join(a["why"])
    assert "Stronger than 90%" in joined and "Still strong" in joined and "uptrend" in joined and "Not overheated" in joined and "1-year high" in joined
    assert "about ₹952" in a["change_my_mind"][0]                                 # 1000 / 1.05


def test_weak_overheated_or_wild_stocks_get_warnings_not_praise():
    weak = ideas.assess_row(None, row(rs_rank_126=10, rs_rank_63=15, above_sma50=False, above_sma200=False, rsi=30, pct_from_52w_high=-0.4, rvol=0.5, vol_21d_annual=0.7), "short", with_flags=False)
    assert weak["label"] == "Looks weak" and weak["risk"] == "Higher" and any("downtrend" in w for w in weak["watch_out"]) and any("bumpy" in w for w in weak["watch_out"])
    hot = ideas.assess_row(None, row(rsi=82), "short", with_flags=False)
    assert any("very stretched" in w for w in hot["watch_out"]) and hot["score"] < ideas.assess_row(None, row(), "short", with_flags=False)["score"]


def good_company(**kw):
    return row(roe=0.22, net_margin=0.18, debt_equity=0.2, piotroski=8, altman_zone="safe", revenue_growth=0.14, earnings_growth=0.16, pe=22, dividend_yield=0.02,
               cagr_3y=0.15, max_dd_3y=-0.22, has_fundamentals=True) | kw


def test_long_term_rewards_quality_and_punishes_distress_and_expensive_loss_makers():
    good = ideas.assess_row(None, good_company(), "long", with_flags=False)
    assert good["score"] >= 90 and good["label"] == "Looks strong" and good["checks"] == "12 of 12 checks"
    assert any("Low debt" in w for w in good["why"]) and any("₹22 for each ₹1" in w for w in good["why"])
    bad = ideas.assess_row(None, good_company(roe=0.02, net_margin=-0.05, debt_equity=3.5, piotroski=2, altman_zone="distress", revenue_growth=-0.2, earnings_growth=-0.5, pe=-10,
                                              dividend_yield=0, cagr_3y=-0.1, max_dd_3y=-0.6), "long", with_flags=False)
    assert bad["score"] <= 10 and bad["label"] == "Looks weak" and len(bad["watch_out"]) >= 6
    assert any("Heavy debt" in w for w in bad["watch_out"]) and any("distress" in w for w in bad["watch_out"])


def test_missing_fundamentals_are_skipped_not_guessed_and_low_confidence_is_not_ranked():
    a = ideas.assess_row(None, row(has_fundamentals=False), "long", with_flags=False)               # only price-history checks exist
    assert a["ranked"] is False and a["label"] == "Not enough data" and a["confidence"] < ideas.MIN_CONFIDENCE_LONG
    assert any("not loaded" in w for w in a["watch_out"])
    partial = ideas.assess_row(None, good_company(piotroski=None, altman_zone=None, cagr_3y=None, max_dd_3y=None), "long", with_flags=False)
    assert partial["ranked"] and partial["checks"] == "8 of 12 checks" and 0.55 <= partial["confidence"] < 1


def test_eligibility_needs_enough_history_and_risk_filter_works():
    assert ideas.eligible(row(bars=130), "short") and not ideas.eligible(row(bars=130), "long") and not ideas.eligible(row(bars=100), "short")
    rows = [row(symbol="CALM", vol_21d_annual=0.15), row(symbol="MID", vol_21d_annual=0.3), row(symbol="WILD", vol_21d_annual=0.7)]
    assert {i["symbol"] for i in ideas.top_ideas(None, rows, "short", 10, "low")["ideas"]} == {"CALM"}
    assert {i["symbol"] for i in ideas.top_ideas(None, rows, "short", 10, "medium")["ideas"]} == {"CALM", "MID"}
    assert len(ideas.top_ideas(None, rows, "short", 10)["ideas"]) == 3
    with pytest.raises(ValueError):
        ideas.top_ideas(None, rows, "forever")


def test_no_advice_language_in_any_generated_text():
    from app.llm import guardrails as gr
    texts = []
    for r in (row(), row(rsi=82, vol_21d_annual=0.8, above_sma200=False), good_company(), good_company(pe=-5, debt_equity=3, piotroski=1, altman_zone="distress", cagr_3y=-0.2, max_dd_3y=-0.7)):
        for h in ("short", "long"):
            a = ideas.assess_row(None, r, h, with_flags=False)
            texts += a["why"] + a["watch_out"] + a["change_my_mind"]
    assert texts and not [t for t in texts if gr.contains_advice(t)], [t for t in texts if gr.contains_advice(t)]


@pytest.fixture
def db():
    dbmod.init_engine("sqlite:///:memory:")
    scr._cache.clear()
    s = next(dbmod.get_session())
    for i, (sym, sec, dr) in enumerate([("UPA", "IT", 0.004), ("UPB", "IT", 0.003), ("FLAT", "Banks", 0.0), ("DNA", "Banks", -0.004), ("DNB", "Energy", -0.003)]):
        seed(s, sym, sec, dr, n=400, seed_=i)
    return s


def test_ideas_api_ranks_short_term_and_is_honest_about_long_term_without_company_numbers(client, db):
    r = client.get("/discover/ideas?horizon=short&limit=3").json()
    ids = [i["symbol"] for i in r["ideas"]]
    assert r["universe"] == 5 and len(ids) == 3 and ids[0] in ("UPA", "UPB") and "DNB" not in ids and "not recommendations" in r["disclaimer"]
    assert all(i["why"] is not None and i["checks"] for i in r["ideas"])
    long = client.get("/discover/ideas?horizon=long").json()
    assert long["ideas"] == [] and long["unranked"] >= 1                                         # no fundamentals loaded: nothing is ranked on guesswork
    assert client.get("/discover/ideas?horizon=weekly").status_code == 422
    v = client.get("/discover/stock/UPA").json()
    assert v["short"]["label"] in ("Looks strong", "Mixed") and v["long"]["label"] == "Not enough data" and v["compared_with"] == 5
    assert client.get("/discover/stock/NOPE").status_code == 404


def test_status_and_loader_job_with_fake_providers(client, db):
    from app.deps import get_router
    from app.main import app
    from app.providers.base import FundamentalsProvider, ProviderError

    class NoFunds(FundamentalsProvider):
        name = "none"

        async def fetch(self, symbol):
            raise ProviderError("offline")
    from app.api.routes_fund import get_fund_provider
    app.dependency_overrides[get_fund_provider] = lambda: NoFunds()
    st = client.get("/discover/status").json()
    assert st["popular"] > 60 and st["loaded"] <= st["popular"] and st["enough_to_compare"] is False
    job = client.post("/discover/load").json()
    assert job["kind"] == "discover_load"
    for _ in range(90):
        j = client.get(f"/jobs/{job['id']}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j
    assert j["result"]["loaded"] == st["popular"] and len(j["result"]["company_number_problems"]) == st["popular"]
    after = client.get("/discover/status").json()
    assert after["loaded"] == st["popular"] and after["enough_to_compare"] is True
    _ = get_router
