import asyncio
import time

import pytest
from sqlalchemy import func, select

from app.data import db as dbmod
from app.data.models import Article, ArticleScore, ArticleTicker
from app.data.news_ingest import (
    NewsRouter,
    article_id,
    ingest_symbol,
    normalize_url,
    score_pending,
    store_articles,
    title_hash,
)
from app.nlp import factory
from app.nlp.entities import AliasResolver, top_terms
from app.nlp.finbert import FinBertScorer
from app.nlp.scoring import Probs
from app.nlp.vader import VaderScorer
from app.providers.base import NewsProvider, NewsQuery, ProviderError, RawArticle

R = AliasResolver()


@pytest.fixture
def db():
    dbmod.init_engine("sqlite:///:memory:")
    gen = dbmod.get_session()
    yield next(gen)


def raw(url="https://a.com/x", title="Reliance Industries profit jumps", pub=None, **kw):
    return RawArticle(url=url, title=title, published=pub or int(time.time()) - 3600, provider=kw.pop("provider", "t"), **kw)


def test_url_normalisation():
    a = normalize_url("HTTPS://www.Example.com/news/story/?utm_source=x&b=2&a=1#frag")
    assert a == normalize_url("https://example.com/news/story?a=1&b=2&fbclid=zzz")
    assert article_id("https://www.a.com/x/") == article_id("https://a.com/x")
    assert article_id("https://a.com/x") != article_id("https://a.com/y")


def test_title_hash_ignores_case_and_punctuation():
    assert title_hash("Reliance: Q2 profit UP!") == title_hash("reliance q2 profit up")


def test_dedupe_by_url_and_by_title_and_ticker_merge(db):
    n1 = store_articles(db, [raw("https://a.com/x?utm_campaign=1"), raw("https://www.a.com/x/")], R, "RELIANCE")
    assert n1 == {"new": 1, "duplicates": 1}
    # same story, different outlet URL, found while querying another symbol: dedup by title, tag both
    n2 = store_articles(db, [raw("https://other.com/copy", title="Reliance Industries profit jumps!")], R, "TCS")
    assert n2 == {"new": 0, "duplicates": 1}
    assert db.scalar(select(func.count()).select_from(Article)) == 1
    assert set(db.scalars(select(ArticleTicker.symbol))) == {"RELIANCE", "TCS"}


def test_provider_tags_and_alias_hits_are_combined(db):
    store_articles(db, [raw(title="Infosys and Wipro results", tickers=["TCS"])], R)
    assert set(db.scalars(select(ArticleTicker.symbol))) == {"INFY", "WIPRO", "TCS"}


def test_alias_resolution_rules():
    r = R.resolve
    assert r("Reliance Industries posts record profit") == {"RELIANCE"}
    assert r("reliance industries posts record profit") == {"RELIANCE"}      # long names: case-insensitive
    assert "TCS" in r("TCS wins deal") and "TCS" not in r("tcs wins deal")  # short: exact case only
    assert "ITC" in r("ITC Ltd shares rise") and r("it is a nice day, its capital") == set()
    assert "LT" in r("L&T bags orders") and "M&M" in r("M&M launches SUV")
    assert "SBIN" in r("SBI cuts rates") and r("SBINX unrelated") == set()    # no sub-word matches
    assert r("Hindustan Unilever and HDFC Bank") == {"HINDUNILVR", "HDFCBANK"}


def test_top_terms_drops_stopwords():
    t = dict(top_terms(["Reliance profit surges as profit beats", "Profit at Reliance"]))
    assert t["profit"] == 3 and "as" not in t and "the" not in t


def test_vader_polarity():
    pos, neg = VaderScorer().score(["Company reports record profit, shares surge", "Fraud probe triggers heavy loss and plunge"])
    assert pos.score > 0.3 and neg.score < -0.3
    assert abs(pos.pos + pos.neg + pos.neu - 1) < 1e-9


def test_finbert_wrapper_label_mapping_and_validation():
    calls = []
    def predict(texts):
        calls.append(len(texts))
        return [{"negative": 0.1, "neutral": 0.2, "positive": 0.7}] * len(texts)
    sc = FinBertScorer(predict=predict, batch=2)
    out = sc.score(["a", "b", "c"])
    assert calls == [2, 1] and out[0] == Probs(pos=0.7, neg=0.1, neu=0.2) and out[0].score == pytest.approx(0.6)
    with pytest.raises(ValueError):
        FinBertScorer(predict=lambda t: [{"positive": 0.9, "negative": 0.9, "neutral": 0.0}]).score(["x"])


def test_factory_falls_back_to_vader_when_finbert_unavailable(monkeypatch):
    factory.set_scorer(None)
    sc = factory.get_scorer()           # transformers/torch are not installed in the test env
    assert sc.name in {"vader", "finbert"}
    factory.set_scorer(None)
    monkeypatch.setenv("QUANTLENS_DISABLE_FINBERT", "1")
    assert factory.get_scorer().name == "vader"
    factory.set_scorer(None)


def test_each_article_is_scored_once_per_model(db):
    store_articles(db, [raw("https://a.com/1", "Profit surges"), raw("https://a.com/2", "Loss widens")], R, "RELIANCE")
    v = VaderScorer()
    assert score_pending(db, v) == 2 and score_pending(db, v) == 0
    class Fake:
        name = "finbert"
        def score(self, texts): return [Probs(0.5, 0.2, 0.3)] * len(texts)
    assert score_pending(db, Fake()) == 2          # a new model scores independently
    assert db.scalar(select(func.count()).select_from(ArticleScore)) == 4


class FakeNews(NewsProvider):
    def __init__(self, name, arts=None, fail=False, budget=None, configured=True):
        super().__init__()
        self.name, self.arts, self.fail, self.daily_budget, self._cfg = name, arts or [], fail, budget, configured
    def is_configured(self): return self._cfg
    async def fetch(self, q: NewsQuery):
        if self.fail:
            raise ProviderError("down")
        return self.arts


async def test_router_survives_one_failing_provider_and_skips_unconfigured():
    good, bad, off = FakeNews("good", [raw()]), FakeNews("bad", fail=True), FakeNews("off", [raw("https://z.com")], configured=False)
    arts, errors = await asyncio.wait_for(NewsRouter([good, bad, off]).fetch_all(NewsQuery("RELIANCE", "Reliance", 3)), 30)
    assert len(arts) == 1 and "bad" in errors and "off" not in errors


async def test_daily_budget_stops_calls(db):
    from app.data.prices import record_health
    from app.deps import _session_ctx
    p = FakeNews("capped", [raw()], budget=2)
    r = NewsRouter([p], db_factory=_session_ctx)
    for _ in range(2):
        record_health(_session_ctx, "capped", None)
    arts, errors = await r.fetch_all(NewsQuery("RELIANCE", "Reliance", 3))
    assert arts == [] and "budget" in errors["capped"]


async def test_ingest_symbol_end_to_end(db):
    r = NewsRouter([FakeNews("a", [raw("https://a.com/1", "Reliance profit surges"), raw("https://a.com/2", "Reliance faces probe and loss")])])
    out = await ingest_symbol(db, r, R, VaderScorer(), "RELIANCE", "Reliance Industries", 7)
    assert out["new"] == 2 and out["scored"] == 2 and out["model"] == "vader" and out["errors"] == {}
    again = await ingest_symbol(db, r, R, VaderScorer(), "RELIANCE", "Reliance Industries", 7)
    assert again["new"] == 0 and again["duplicates"] == 2 and again["scored"] == 0
