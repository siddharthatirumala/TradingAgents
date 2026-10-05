"""Synthetic price data for the screening tests (fixed seeds: deterministic)."""

import numpy as np
import pandas as pd

from sid_trading_firm.backtest.data import PricePanel


def frame(closes, volume=1_000_000, start="2025-01-01"):
    closes = np.asarray(closes, dtype=float)
    volume = np.broadcast_to(np.asarray(volume, dtype=float), closes.shape)
    return pd.DataFrame({"date": pd.bdate_range(start, periods=len(closes)), "open": closes,
                         "high": closes * 1.01, "low": closes * 0.99, "close": closes, "volume": volume})


def walk(n, drift, vol, seed, start_price=100.0):
    rng = np.random.default_rng(seed)
    return start_price * np.cumprod(1 + rng.normal(drift, vol, n))


def panel(**frames):
    return PricePanel.from_frames(frames)
