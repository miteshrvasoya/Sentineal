from pydantic import BaseModel, Field


class Bar(BaseModel):
    t: int = Field(description="UTC epoch seconds of bar start")
    o: float
    h: float
    l: float
    c: float
    v: float


class PricesResponse(BaseModel):
    symbol: str
    interval: str
    adjusted: bool
    source: str | None
    count: int
    downsampled: bool = False
    warnings: list[str] = []
    bars: list[Bar]


class QuoteResponse(BaseModel):
    symbol: str
    last: float
    prev_close: float
    change: float
    change_pct: float
    source: str


class SymbolOut(BaseModel):
    symbol: str
    name: str
    sector: str
    exchange: str = "NSE"
    source: str = "local"


class WatchlistAdd(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)


class ErrorOut(BaseModel):
    error: str
    detail: str | None = None
    provider_errors: dict[str, str] | None = None
