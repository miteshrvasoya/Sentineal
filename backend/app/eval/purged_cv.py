"""Purged and embargoed K-fold cross-validation for time series with overlapping labels.

Ordinary K-fold shuffles rows, which lets a model train on days AFTER the days it is tested on, and on days whose label window
overlaps a test day's label window. Both leak the future. Here:

  * folds are contiguous blocks of time (never shuffled);
  * PURGE: training rows whose label window [t, t + horizon] overlaps the test block are removed;
  * EMBARGO: training rows in a short stretch AFTER the test block are removed too, because volatility and news persist
    and the first days after a test block are not independent of it.

Training rows may sit before AND after the test block (that is fine and uses more data); what matters is that nothing
overlapping the test window is in them.
"""
from __future__ import annotations

from collections.abc import Iterator

import numpy as np


class PurgedKFold:
    def __init__(self, n_splits: int = 5, horizon: int = 5, embargo: int | float = 0.01) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be at least 2")
        self.n_splits, self.horizon, self.embargo = n_splits, horizon, embargo

    def _embargo_bars(self, n: int) -> int:
        return int(self.embargo) if self.embargo >= 1 else int(np.ceil(self.embargo * n))

    def split(self, n: int) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (train_idx, test_idx) over rows 0..n-1, which must be in time order and one row per forecast origin."""
        if n < self.n_splits * 2:
            raise ValueError("too few rows for the requested number of splits")
        edges = np.linspace(0, n, self.n_splits + 1, dtype=int)
        emb = self._embargo_bars(n)
        idx = np.arange(n)
        for k in range(self.n_splits):
            lo, hi = edges[k], edges[k + 1]
            test = idx[lo:hi]
            # a train row t has label window [t, t+h]; it overlaps the test block if t + h >= lo and t < hi
            bad_before = (idx + self.horizon >= lo) & (idx < lo)
            bad_after = (idx >= hi) & (idx < hi + emb)
            train = idx[~((idx >= lo) & (idx < hi)) & ~bad_before & ~bad_after]
            yield train, test

    def get_n_splits(self) -> int:
        return self.n_splits
