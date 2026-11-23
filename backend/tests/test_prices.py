import pandas as pd
import pytest

from app.data.prices import to_epoch_seconds


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_epoch_seconds_independent_of_resolution(unit):
    idx = pd.DatetimeIndex(pd.to_datetime(["2026-01-05", "2026-01-06"], utc=True)).as_unit(unit)
    assert to_epoch_seconds(idx) == [1767571200, 1767657600]
