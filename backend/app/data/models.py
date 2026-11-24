"""ORM tables. Timestamps are UTC epoch seconds (ints)."""
from sqlalchemy import BigInteger, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.data.db import Base


class Symbol(Base):
    __tablename__ = "symbols"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    sector: Mapped[str] = mapped_column(String(64), default="")
    exchange: Mapped[str] = mapped_column(String(8), default="NSE")


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    added_at: Mapped[int] = mapped_column(BigInteger, default=0)


class Price(Base):
    __tablename__ = "prices"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    interval: Mapped[str] = mapped_column(String(8), primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(32), default="")


class ProviderHealth(Base):
    __tablename__ = "provider_health"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_success: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error_msg: Mapped[str] = mapped_column(Text, default="")
    calls_today: Mapped[int] = mapped_column(Integer, default=0)
    day: Mapped[str] = mapped_column(String(10), default="")


class Article(Base):
    __tablename__ = "articles"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)        # sha1(normalized url)[:16]
    title_hash: Mapped[str] = mapped_column(String(16), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(128), default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    published: Mapped[int] = mapped_column(BigInteger, index=True)       # UTC epoch seconds
    fetched: Mapped[int] = mapped_column(BigInteger, default=0)
    provider_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class ArticleTicker(Base):
    __tablename__ = "article_tickers"
    article_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)


class ArticleScore(Base):
    """One row per (article, model): every article is scored at most once per model."""
    __tablename__ = "article_scores"
    article_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    model: Mapped[str] = mapped_column(String(32), primary_key=True)
    pos: Mapped[float] = mapped_column(Float)
    neg: Mapped[float] = mapped_column(Float)
    neu: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)                           # pos - neg, in [-1, 1]
    scored_at: Mapped[int] = mapped_column(BigInteger, default=0)


class LLMUsage(Base):
    """One row per LLM attempt (including cache hits and failures) for spend tracking and the usage chart."""
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)             # IST date
    task: Mapped[str] = mapped_column(String(48))
    provider: Mapped[str] = mapped_column(String(24), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)          # ESTIMATE from config pricing
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cached: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str] = mapped_column(String(200), default="")


class LLMCache(Base):
    """key = sha256(task | prompt id+version | model | content hash)."""
    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created: Mapped[int] = mapped_column(BigInteger)


class ArticleEnrichment(Base):
    """LLM understanding of one article. `generated_at` matters: see the look-ahead warning in the guide."""
    __tablename__ = "article_enrichment"
    article_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    prompt_id: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(24))
    model: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[int] = mapped_column(BigInteger, index=True)
    tickers: Mapped[str] = mapped_column(Text, default="[]")             # JSON list
    event_type: Mapped[str] = mapped_column(String(24))
    direction: Mapped[str] = mapped_column(String(12))
    materiality: Mapped[str] = mapped_column(String(8))
    horizon: Mapped[str] = mapped_column(String(12))
    is_new_information: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text, default="")
    flags: Mapped[str] = mapped_column(Text, default="[]")               # JSON list: injection_suspected, summary_removed...


class FundamentalsSnapshot(Base):
    """Latest raw inputs per symbol (JSON of features.fundamentals.Inputs). Ratios are recomputed on read so DCF
    assumptions and sector percentiles never need a re-fetch."""
    __tablename__ = "fundamentals_snapshot"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    sector: Mapped[str] = mapped_column(String(64), default="", index=True)
    fetched_at: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[str] = mapped_column(Text)


class ModelRun(Base):
    """Model registry: one row per (symbol, model, run). Keeps the forecast, parameters, data window and walk-forward
    metrics so performance drift and decay can be tracked across versions."""
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(32), index=True)
    horizon: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="statistical")
    trained_at: Mapped[int] = mapped_column(BigInteger)
    train_start: Mapped[str] = mapped_column(String(10), default="")
    train_end: Mapped[str] = mapped_column(String(10), default="")
    n_train: Mapped[int] = mapped_column(Integer, default=0)
    feature_hash: Mapped[str] = mapped_column(String(32), default="")
    params: Mapped[str] = mapped_column(Text, default="{}")
    view: Mapped[str] = mapped_column(Text, default="{}")
    metrics: Mapped[str] = mapped_column(Text, default="")


class JobRecord(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    symbol: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(12), default="queued")      # queued | running | done | failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    created: Mapped[int] = mapped_column(BigInteger, default=0)
    started: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    finished: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
