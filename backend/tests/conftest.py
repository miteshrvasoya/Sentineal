import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.data import db as dbmod
from app.data.prices import clear_refresh_cache
from app.providers.base import MarketDataProvider, ProviderError, ProviderRouter


def make_frame(n: int = 60, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    end_ts = pd.Timestamp.now(tz="UTC").normalize()
    idx = pd.date_range(end=end_ts, periods=n, freq="B", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    open_ = close + rng.normal(0, 0.3, n)
    high = np.maximum(open_, close) + rng.uniform(0.1, 1, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "adj_close": close * 0.98, "volume": rng.integers(1e5, 1e6, n).astype(float)}, index=idx)


class FakeProvider(MarketDataProvider):
    def __init__(self, name="fake", frame=None, fail=False):
        self.name = name
        self.frame = frame
        self.fail = fail
        self.calls = 0
        super().__init__()

    async def fetch_ohlcv(self, symbol, interval, start, end):
        self.calls += 1
        if self.fail:
            raise ProviderError("boom")
        return self.frame if self.frame is not None else make_frame()

    async def fetch_quote(self, symbol):
        return {"last": 101.0, "prev_close": 100.0, "change": 1.0, "change_pct": 1.0}


@pytest.fixture
def fake():
    return FakeProvider()


@pytest.fixture
def client(fake):
    from app.deps import get_router
    from app.main import app

    dbmod.init_engine("sqlite:///:memory:")
    clear_refresh_cache()
    router = ProviderRouter([fake])
    app.dependency_overrides[get_router] = lambda: router
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
