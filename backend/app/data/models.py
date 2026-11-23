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
